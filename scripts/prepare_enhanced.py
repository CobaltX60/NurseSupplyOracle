# scripts/prepare_enhanced.py
import pdfplumber
import json
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import pytesseract
from PIL import Image
import io

def extract_text_from_pdf_enhanced(pdf_path, textbook_name):
    """Enhanced text extraction that can handle image-based PDFs"""
    print(f"Extracting text from {pdf_path}...")
    texts = []
    text_pages = 0
    image_pages = 0
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pg_num, pg in enumerate(pdf.pages):
                # Try regular text extraction first
                txt = pg.extract_text() or ''
                
                if len(txt.strip()) < 50:  # If very little text, try OCR
                    print(f"   Page {pg_num + 1}: Little text found, attempting OCR...")
                    try:
                        # Convert page to image
                        img = pg.to_image()
                        if img:
                            # Convert to PIL Image
                            pil_img = Image.fromarray(img.original)
                            # Use OCR to extract text
                            ocr_text = pytesseract.image_to_string(pil_img)
                            if len(ocr_text.strip()) > len(txt.strip()):
                                txt = ocr_text
                                image_pages += 1
                                print(f"   Page {pg_num + 1}: OCR extracted {len(ocr_text)} characters")
                    except Exception as e:
                        print(f"   Page {pg_num + 1}: OCR failed - {e}")
                
                if txt.strip():
                    text_pages += 1
                
                texts.append(txt)
                
    except FileNotFoundError:
        print(f"Warning: {pdf_path} not found, skipping...")
        return []
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []
    
    print(f"Extracted text from {text_pages} text pages and {image_pages} OCR pages from {textbook_name}")
    
    # Chunk the text
    joined = "\n\n".join(texts)
    tokens = joined.split()   # naive tokenization
    chunks, size, overlap = [], 1200, 200
    
    for i in range(0, len(tokens), size - overlap):
        chunk_text = " ".join(tokens[i:i+size])
        if chunk_text.strip():  # Only add non-empty chunks
            # Add source information to each chunk
            chunk_with_source = {
                "text": chunk_text,
                "source": textbook_name,
                "chunk_id": len(chunks)
            }
            chunks.append(chunk_with_source)
    
    return chunks

def main():
    print("Loading sentence transformer model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Define textbooks to process
    textbooks = [
        ("textbook.pdf", "Primary Nursing Textbook"),
        ("textbook2.pdf", "Secondary Nursing Textbook"),
        ("textbook3.pdf", "Tertiary Nursing Textbook")
    ]
    
    all_chunks = []
    
    # Process each textbook
    for pdf_path, textbook_name in textbooks:
        if os.path.exists(pdf_path):
            chunks = extract_text_from_pdf_enhanced(pdf_path, textbook_name)
            all_chunks.extend(chunks)
        else:
            print(f"Skipping {pdf_path} - file not found")
    
    if not all_chunks:
        print("Error: No textbooks found to process!")
        print("Please ensure at least one of the following files exists:")
        print("- textbook.pdf")
        print("- textbook2.pdf")
        print("- textbook3.pdf")
        return
    
    print(f"Total chunks created: {len(all_chunks)}")
    
    # Extract just the text for embedding
    chunk_texts = [chunk["text"] for chunk in all_chunks]
    
    # Create embeddings
    print("Creating embeddings...")
    embeddings = model.encode(chunk_texts, convert_to_numpy=True)
    dim = embeddings.shape[1]
    
    # Build FAISS index
    print("Building FAISS index...")
    idx = faiss.IndexFlatL2(dim)
    idx.add(embeddings)
    faiss.write_index(idx, 'faiss_index_enhanced.idx')
    
    # Save chunks with source information
    print("Saving chunks to JSON...")
    with open('chunks_enhanced.json', 'w') as f:
        json.dump(all_chunks, f, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("PROCESSING SUMMARY:")
    print("="*60)
    
    # Count chunks by source
    source_counts = {}
    for chunk in all_chunks:
        source = chunk["source"]
        source_counts[source] = source_counts.get(source, 0) + 1
    
    for source, count in source_counts.items():
        print(f"📚 {source}: {count} chunks")
    
    print(f"📊 Total chunks: {len(all_chunks)}")
    print(f"🔍 Index dimension: {dim}")
    print("="*60)
    print("Done! Created faiss_index_enhanced.idx and chunks_enhanced.json")
    print("Your system now includes multiple textbooks with enhanced text extraction!")

if __name__ == "__main__":
    main() 
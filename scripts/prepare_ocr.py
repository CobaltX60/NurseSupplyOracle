# scripts/prepare_ocr.py
import fitz  # PyMuPDF
import json
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import pytesseract
from PIL import Image
import io

def extract_text_from_pdf_ocr(pdf_path, textbook_name):
    """Extract text from PDF using OCR for image-based PDFs"""
    print(f"Extracting text from {pdf_path} using OCR...")
    texts = []
    ocr_pages = 0
    text_pages = 0
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            
            # First try regular text extraction
            text = page.get_text("text")
            
            # If very little text, try OCR
            if len(text.strip()) < 200:
                try:
                    # Convert page to image
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Higher resolution
                    img_data = pix.tobytes("png")
                    
                    # Convert to PIL Image
                    img = Image.open(io.BytesIO(img_data))
                    
                    # Use OCR to extract text
                    ocr_text = pytesseract.image_to_string(img)
                    
                    # Use OCR text if it's longer
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        ocr_pages += 1
                        print(f"   Page {page_num + 1}: OCR extracted {len(ocr_text)} characters")
                    
                except Exception as e:
                    print(f"   Page {page_num + 1}: OCR failed - {e}")
            
            if len(text.strip()) > 50:
                text_pages += 1
            
            texts.append(text)
            
            # Progress indicator
            if (page_num + 1) % 100 == 0:
                print(f"   Processed {page_num + 1}/{total_pages} pages...")
        
        doc.close()
        
    except FileNotFoundError:
        print(f"Warning: {pdf_path} not found, skipping...")
        return []
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []
    
    print(f"Extracted text from {text_pages} pages ({ocr_pages} via OCR) from {textbook_name}")
    
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
    
    # Define textbooks to process (now in source_files directory)
    textbooks = [
        ("source_files/textbook.pdf", "Primary Nursing Textbook"),
        ("source_files/textbook2.pdf", "Secondary Nursing Textbook"),
        ("source_files/textbook3.pdf", "Tertiary Nursing Textbook")
    ]
    
    all_chunks = []
    
    # Process each textbook
    for pdf_path, textbook_name in textbooks:
        if os.path.exists(pdf_path):
            chunks = extract_text_from_pdf_ocr(pdf_path, textbook_name)
            all_chunks.extend(chunks)
        else:
            print(f"Skipping {pdf_path} - file not found")
    
    if not all_chunks:
        print("Error: No textbooks found to process!")
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
    faiss.write_index(idx, 'faiss_index_ocr.idx')
    
    # Save chunks with source information
    print("Saving chunks to JSON...")
    with open('chunks_ocr.json', 'w') as f:
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
    print("Done! Created faiss_index_ocr.idx and chunks_ocr.json")

if __name__ == "__main__":
    main() 
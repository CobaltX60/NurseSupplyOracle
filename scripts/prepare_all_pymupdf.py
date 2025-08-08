# scripts/prepare_all_pymupdf.py
import fitz  # PyMuPDF
import json
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os

def extract_text_from_pdf_pymupdf(pdf_path, textbook_name):
    """PyMuPDF text extraction for all textbooks"""
    print(f"Extracting text from {pdf_path} using PyMuPDF...")
    texts = []
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"   Total pages: {total_pages}")
        
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            texts.append(text)
            
            # Progress indicator
            if (page_num + 1) % 100 == 0:
                print(f"   Processed {page_num + 1}/{total_pages} pages...")
        
        doc.close()
        
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []
    
    # Count pages with actual text
    text_pages = sum(1 for t in texts if len(t.strip()) > 50)
    total_chars = sum(len(t) for t in texts)
    print(f"   Pages with text: {text_pages}/{len(texts)}")
    print(f"   Total characters: {total_chars:,}")
    
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
            chunks = extract_text_from_pdf_pymupdf(pdf_path, textbook_name)
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
    faiss.write_index(idx, 'faiss_index_all_pymupdf.idx')
    
    # Save chunks with source information
    print("Saving chunks to JSON...")
    with open('chunks_all_pymupdf.json', 'w') as f:
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
    print("Done! Created faiss_index_all_pymupdf.idx and chunks_all_pymupdf.json")
    print("Your system now includes all textbooks with optimal text extraction!")

if __name__ == "__main__":
    main() 
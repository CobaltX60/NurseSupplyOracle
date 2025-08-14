#!/usr/bin/env python3
"""
Enhanced PDF processing with page number tracking
Extracts text from PDFs and includes page numbers in chunks
"""

import fitz  # PyMuPDF
import json
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import re

def extract_text_from_pdf_with_pages(pdf_path, textbook_name):
    """Extract text from PDF using PyMuPDF with page number tracking"""
    print(f"Extracting text from {pdf_path} using PyMuPDF with page tracking...")
    texts_with_pages = []
    
    try:
        print(f"   Opening {pdf_path}...")
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"   Found {total_pages} pages")
        
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            
            # Try different text extraction methods
            text = ""
            
            # Method 1: Get text with layout preservation
            text = page.get_text("text")
            
            # Method 2: If little text, try HTML extraction
            if len(text.strip()) < 100:
                html_text = page.get_text("html")
                # Extract text from HTML (simple approach)
                clean_text = re.sub(r'<[^>]+>', '', html_text)
                if len(clean_text.strip()) > len(text.strip()):
                    text = clean_text
            
            # Method 3: If still little text, try dict extraction
            if len(text.strip()) < 100:
                try:
                    dict_text = page.get_text("dict")
                    # Extract text from dict format
                    dict_content = ""
                    for block in dict_text.get("blocks", []):
                        if "lines" in block:
                            for line in block["lines"]:
                                for span in line.get("spans", []):
                                    dict_content += span.get("text", "") + " "
                    if len(dict_content.strip()) > len(text.strip()):
                        text = dict_content
                except:
                    pass  # Skip if dict extraction fails
            
            # Only add pages with substantial content
            if len(text.strip()) > 50:
                texts_with_pages.append({
                    "text": text,
                    "page_number": page_num + 1,  # 1-based page numbering
                    "source": textbook_name
                })
            
            # Progress indicator
            if (page_num + 1) % 100 == 0:
                print(f"   Processed {page_num + 1}/{total_pages} pages...")
        
        doc.close()
        
    except FileNotFoundError:
        print(f"Warning: {pdf_path} not found, skipping...")
        return []
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    print(f"Extracted text from {len(texts_with_pages)} pages from {textbook_name}")
    
    # Create chunks with page tracking
    chunks = []
    chunk_id = 0
    
    for page_data in texts_with_pages:
        text = page_data["text"]
        page_number = page_data["page_number"]
        source = page_data["source"]
        
        # Split page text into smaller chunks if needed
        tokens = text.split()
        chunk_size = 1200
        overlap = 200
        
        for i in range(0, len(tokens), chunk_size - overlap):
            chunk_text = " ".join(tokens[i:i+chunk_size])
            if chunk_text.strip():  # Only add non-empty chunks
                chunk_with_metadata = {
                    "text": chunk_text,
                    "source": source,
                    "page_number": page_number,
                    "chunk_id": chunk_id,
                    "type": "textbook"
                }
                chunks.append(chunk_with_metadata)
                chunk_id += 1
    
    return chunks

def create_embeddings_and_index(chunks):
    """Create embeddings and FAISS index for chunks"""
    print("Creating embeddings and FAISS index...")
    
    # Load sentence transformer model
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Extract text for embedding
    texts = [chunk["text"] for chunk in chunks]
    
    # Create embeddings
    embeddings = model.encode(texts, show_progress_bar=True)
    
    # Create FAISS index
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity
    
    # Normalize embeddings for cosine similarity
    faiss.normalize_L2(embeddings)
    index.add(embeddings.astype('float32'))
    
    return index

def main():
    print("🚀 Enhanced PDF Processing with Page Numbers")
    print("=" * 50)
    
    # Define textbooks to process (now from source_files directory)
    textbooks = [
        ("source_files/textbook.pdf", "Primary Nursing Textbook"),
        ("source_files/textbook2.pdf", "Secondary Nursing Textbook"),
        ("source_files/textbook3.pdf", "Tertiary Nursing Textbook")
    ]
    
    all_chunks = []
    
    # Process each textbook
    for pdf_path, textbook_name in textbooks:
        if os.path.exists(pdf_path):
            print(f"\n📖 Processing {textbook_name}...")
            chunks = extract_text_from_pdf_with_pages(pdf_path, textbook_name)
            all_chunks.extend(chunks)
            print(f"✅ Added {len(chunks)} chunks from {textbook_name}")
        else:
            print(f"⚠️ Skipping {pdf_path} - file not found")
    
    if not all_chunks:
        print("❌ No chunks created. Check if PDF files exist in source_files/ directory.")
        return
    
    print(f"\n📊 Total chunks created: {len(all_chunks)}")
    
    # Create embeddings and index
    index = create_embeddings_and_index(all_chunks)
    
    # Save chunks with page numbers
    chunks_file = "chunks_with_pages.json"
    with open(chunks_file, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)
    
    # Save FAISS index
    index_file = "faiss_index_with_pages.idx"
    faiss.write_index(index, index_file)
    
    print(f"\n✅ Processing complete!")
    print(f"📄 Chunks saved to: {chunks_file}")
    print(f"🔍 FAISS index saved to: {index_file}")
    
    # Show sample of chunks with page numbers
    print(f"\n📋 Sample chunks with page numbers:")
    for i, chunk in enumerate(all_chunks[:3]):
        print(f"   Chunk {i+1}: {chunk['source']} - Page {chunk['page_number']}")
        print(f"   Text preview: {chunk['text'][:100]}...")
        print()

if __name__ == "__main__":
    main() 
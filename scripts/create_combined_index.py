#!/usr/bin/env python3
"""
Create FAISS index for combined chunks with page numbers and product data
"""

import json
import os
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

def create_combined_index():
    """Create FAISS index for combined chunks"""
    
    print("🔄 Creating FAISS index for combined chunks...")
    
    # Load combined chunks
    chunks_path = "chunks_combined_with_pages.json"
    if not os.path.exists(chunks_path):
        print(f"❌ Combined chunks file not found: {chunks_path}")
        return False
    
    # Try multiple encodings to handle special characters
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    chunks_data = None
    
    for encoding in encodings:
        try:
            with open(chunks_path, 'r', encoding=encoding) as f:
                chunks_data = json.load(f)
            print(f"✅ Successfully loaded chunks with {encoding} encoding")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"⚠️ Error with {encoding} encoding: {e}")
            continue
    
    if chunks_data is None:
        print("❌ Failed to load chunks with any encoding")
        return False
    
    print(f"📊 Loaded {len(chunks_data)} total chunks")
    
    # Count chunks by type
    product_count = 0
    textbook_count = 0
    
    for chunk in chunks_data:
        if isinstance(chunk, dict):
            if chunk.get('type') == 'product':
                product_count += 1
            else:
                textbook_count += 1
    
    print(f"📚 Textbook chunks: {textbook_count}")
    print(f"🛍️ Product chunks: {product_count}")
    
    # Load sentence transformer model
    print("📥 Loading sentence transformer model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Extract text for embedding
    texts = [chunk["text"] for chunk in chunks_data]
    
    # Create embeddings
    print("🔍 Creating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True)
    
    # Create FAISS index
    print("🏗️ Building FAISS index...")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity
    
    # Normalize embeddings for cosine similarity
    faiss.normalize_L2(embeddings)
    index.add(embeddings.astype('float32'))
    
    # Save index
    index_path = "faiss_index_with_pages.idx"
    faiss.write_index(index, index_path)
    
    print(f"✅ FAISS index saved to: {index_path}")
    print(f"📊 Index dimension: {dimension}")
    print(f"📊 Total vectors: {index.ntotal}")
    
    return True

if __name__ == "__main__":
    create_combined_index() 
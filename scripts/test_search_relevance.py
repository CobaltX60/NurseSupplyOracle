#!/usr/bin/env python3
"""
Test search relevance to see why product chunks aren't being found
"""

import json
import os
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss

def test_search_relevance():
    """Test why product chunks aren't being found in searches"""
    
    print("🔍 Testing Search Relevance")
    print("=" * 50)
    
    # Load combined chunks
    chunks_path = "chunks_combined_with_pages.json"
    faiss_path = "faiss_index_with_pages.idx"
    
    if not os.path.exists(chunks_path) or not os.path.exists(faiss_path):
        print("❌ Required files not found")
        return
    
    # Load chunks
    with open(chunks_path, 'r', encoding='utf-8') as f:
        chunks_data = json.load(f)
    
    # Load FAISS index
    faiss_index = faiss.read_index(faiss_path)
    
    # Load embedding model
    print("📥 Loading embedding model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Test questions
    test_questions = [
        "What syringe products do we have?",
        "What Medline products are available?",
        "What Cardinal Health products do we carry?",
        "What supplies do I need for wound care?",
        "What equipment is needed for IV therapy?"
    ]
    
    for question in test_questions:
        print(f"\n🔍 Testing: '{question}'")
        print("-" * 40)
        
        # Generate embedding
        question_embedding = model.encode([question], convert_to_numpy=True)
        
        # Search
        k = 10  # Get more results to see what's being found
        distances, indices = faiss_index.search(question_embedding, k)
        
        # Analyze results
        product_results = 0
        textbook_results = 0
        
        print(f"Top {k} search results:")
        for i, idx in enumerate(indices[0]):
            if idx < len(chunks_data):
                chunk = chunks_data[idx]
                chunk_type = chunk.get('type', 'textbook')
                source = chunk.get('source', 'Unknown')
                
                if chunk_type == 'product':
                    product_results += 1
                    print(f"  {i+1}. PRODUCT - {source} (Row {chunk.get('row_index', 'N/A')})")
                    print(f"     Text: {chunk['text'][:100]}...")
                else:
                    textbook_results += 1
                    page_num = chunk.get('page_number', 'N/A')
                    print(f"  {i+1}. TEXTBOOK - {source} (Page {page_num})")
                    print(f"     Text: {chunk['text'][:100]}...")
        
        print(f"\n📊 Results Summary:")
        print(f"   Textbook chunks: {textbook_results}")
        print(f"   Product chunks: {product_results}")
        
        if product_results == 0:
            print("   ⚠️ No product chunks found in search results!")
        else:
            print("   ✅ Product chunks found in search results!")

if __name__ == "__main__":
    test_search_relevance() 
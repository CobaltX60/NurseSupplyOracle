#!/usr/bin/env python3
"""
Combine textbook chunks with page numbers and product data
"""

import json
import os

def combine_chunks_with_products():
    """Combine textbook chunks (with pages) and product chunks"""
    
    print("🔄 Combining textbook chunks with page numbers and product data...")
    
    # Load textbook chunks with page numbers
    textbook_chunks_path = "chunks_with_pages.json"
    if not os.path.exists(textbook_chunks_path):
        print(f"❌ Textbook chunks file not found: {textbook_chunks_path}")
        return False
    
    with open(textbook_chunks_path, 'r', encoding='utf-8') as f:
        textbook_chunks = json.load(f)
    
    print(f"✅ Loaded {len(textbook_chunks)} textbook chunks with page numbers")
    
    # Load product chunks
    product_chunks_path = "product_chunks.json"
    if not os.path.exists(product_chunks_path):
        print(f"❌ Product chunks file not found: {product_chunks_path}")
        return False
    
    with open(product_chunks_path, 'r', encoding='utf-8') as f:
        product_chunks = json.load(f)
    
    print(f"✅ Loaded {len(product_chunks)} product chunks")
    
    # Combine chunks
    combined_chunks = textbook_chunks + product_chunks
    
    # Save combined chunks
    combined_path = "chunks_combined_with_pages.json"
    with open(combined_path, 'w', encoding='utf-8') as f:
        json.dump(combined_chunks, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Combined {len(textbook_chunks)} textbook chunks + {len(product_chunks)} product chunks")
    print(f"✅ Saved combined chunks to: {combined_path}")
    
    # Show sample of combined chunks
    print(f"\n📋 Sample combined chunks:")
    for i, chunk in enumerate(combined_chunks[:5]):
        if chunk.get('type') == 'product':
            print(f"   Chunk {i+1}: {chunk['source']} - Product ID {chunk.get('row_index', 'N/A')}")
        else:
            print(f"   Chunk {i+1}: {chunk['source']} - Page {chunk.get('page_number', 'N/A')}")
        print(f"   Text preview: {chunk['text'][:80]}...")
        print()
    
    return True

if __name__ == "__main__":
    combine_chunks_with_products() 
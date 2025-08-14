#!/usr/bin/env python3
"""
Examine product chunks to verify Excel data is properly loaded
"""

import json
import os

def examine_product_chunks():
    """Examine product chunks in the combined file"""
    
    print("🔍 Examining Product Chunks")
    print("=" * 50)
    
    # Load combined chunks
    chunks_path = "chunks_combined_with_pages.json"
    if not os.path.exists(chunks_path):
        print(f"❌ File not found: {chunks_path}")
        return
    
    # Try multiple encodings
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    data = None
    
    for encoding in encodings:
        try:
            with open(chunks_path, 'r', encoding=encoding) as f:
                data = json.load(f)
            print(f"✅ Loaded with {encoding} encoding")
            break
        except Exception as e:
            continue
    
    if data is None:
        print("❌ Failed to load chunks")
        return
    
    # Find product chunks
    product_chunks = [c for c in data if c.get('type') == 'product']
    textbook_chunks = [c for c in data if c.get('type') != 'product']
    
    print(f"📊 Total chunks: {len(data)}")
    print(f"📚 Textbook chunks: {len(textbook_chunks)}")
    print(f"🛍️ Product chunks: {len(product_chunks)}")
    
    if not product_chunks:
        print("❌ No product chunks found!")
        return
    
    print(f"\n📋 Sample Product Chunks:")
    print("-" * 50)
    
    for i, chunk in enumerate(product_chunks[:5]):
        print(f"\nChunk {i+1}:")
        print(f"  Keys: {list(chunk.keys())}")
        print(f"  Source: {chunk.get('source', 'N/A')}")
        print(f"  Row Index: {chunk.get('row_index', 'N/A')}")
        print(f"  Text preview: {chunk['text'][:150]}...")
        
        # Check for specific product types
        text = chunk['text'].lower()
        if 'syringe' in text:
            print(f"  🎯 Contains: SYRINGE")
        if 'medline' in text:
            print(f"  🎯 Contains: MEDLINE")
        if 'cardinal' in text:
            print(f"  🎯 Contains: CARDINAL HEALTH")
    
    # Check for specific product types
    print(f"\n🔍 Product Type Analysis:")
    print("-" * 50)
    
    syringe_products = [c for c in product_chunks if 'syringe' in c['text'].lower()]
    medline_products = [c for c in product_chunks if 'medline' in c['text'].lower()]
    cardinal_products = [c for c in product_chunks if 'cardinal' in c['text'].lower()]
    
    print(f"💉 Syringe products: {len(syringe_products)}")
    print(f"🏥 Medline products: {len(medline_products)}")
    print(f"🏢 Cardinal Health products: {len(cardinal_products)}")
    
    if syringe_products:
        print(f"\n💉 Sample Syringe Product:")
        print(f"  {syringe_products[0]['text'][:200]}...")
    
    if medline_products:
        print(f"\n🏥 Sample Medline Product:")
        print(f"  {medline_products[0]['text'][:200]}...")

if __name__ == "__main__":
    examine_product_chunks() 
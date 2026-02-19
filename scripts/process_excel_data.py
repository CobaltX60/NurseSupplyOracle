#!/usr/bin/env python3
"""
Process Excel data for Instrument Oracle
Integrates product data with textbook knowledge for enhanced responses
"""

import pandas as pd
import json
import os
from pathlib import Path
import re

def load_excel_data():
    """Load and process the Excel file from source_files directory"""
    
    # Path to the Excel file in source_files
    excel_path = Path(__file__).parent.parent / "source_files" / "ItemData.xlsx"
    
    if not excel_path.exists():
        print(f"❌ Excel file not found at: {excel_path}")
        return None
    
    try:
        print(f"📥 Loading Excel data from: {excel_path}")
        
        # Read the Excel file
        df = pd.read_excel(excel_path)
        
        print(f"✅ Loaded {len(df)} rows with {len(df.columns)} columns")
        print(f"📊 Columns: {list(df.columns)}")
        
        # Display first few rows for inspection
        print("\n📋 First 5 rows:")
        print(df.head())
        
        return df
        
    except Exception as e:
        print(f"❌ Error loading Excel file: {e}")
        return None

def process_product_data(df):
    """Process the product data and create searchable chunks"""
    
    if df is None:
        return []
    
    chunks = []
    
    # Process each row as a product entry
    for index, row in df.iterrows():
        # Create a comprehensive product description
        product_info = []
        
        for column in df.columns:
            value = row[column]
            if pd.notna(value) and str(value).strip():
                product_info.append(f"{column}: {value}")
        
        # Create the full product description
        product_text = " | ".join(product_info)
        
        # Create a chunk for this product
        chunk = {
            "text": product_text,
            "source": "ItemData.xlsx",
            "type": "product",
            "row_index": index,
            "metadata": {
                "product_id": index,
                "columns": list(df.columns),
                "data_type": "product_catalog"
            }
        }
        
        chunks.append(chunk)
    
    print(f"✅ Created {len(chunks)} product chunks")
    return chunks

def create_product_search_index(chunks):
    """Create a searchable index for products"""
    
    # Create a simple keyword-based search index
    product_index = {}
    
    for chunk in chunks:
        text = chunk["text"].lower()
        
        # Extract potential keywords
        words = re.findall(r'\b\w+\b', text)
        
        for word in words:
            if len(word) > 2:  # Skip very short words
                if word not in product_index:
                    product_index[word] = []
                product_index[word].append(chunk["row_index"])
    
    return product_index

def save_processed_data(chunks, product_index):
    """Save the processed data for use by the AI system"""
    
    # Save chunks to JSON
    chunks_path = Path(__file__).parent.parent / "product_chunks.json"
    with open(chunks_path, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    
    # Save product index
    index_path = Path(__file__).parent.parent / "product_index.json"
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(product_index, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Saved product chunks to: {chunks_path}")
    print(f"✅ Saved product index to: {index_path}")

def integrate_with_existing_chunks():
    """Integrate product data with existing textbook chunks"""
    
    # Load existing chunks
    existing_chunks_path = Path(__file__).parent.parent / "chunks_all_pymupdf.json"
    
    if not existing_chunks_path.exists():
        print("⚠️ No existing chunks found, creating new combined file")
        return
    
    try:
        with open(existing_chunks_path, 'r', encoding='utf-8') as f:
            existing_chunks = json.load(f)
        
        # Load product chunks
        product_chunks_path = Path(__file__).parent.parent / "product_chunks.json"
        if product_chunks_path.exists():
            with open(product_chunks_path, 'r', encoding='utf-8') as f:
                product_chunks = json.load(f)
            
            # Combine chunks
            combined_chunks = existing_chunks + product_chunks
            
            # Save combined chunks
            combined_path = Path(__file__).parent.parent / "chunks_combined.json"
            with open(combined_path, 'w', encoding='utf-8') as f:
                json.dump(combined_chunks, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Combined {len(existing_chunks)} textbook chunks with {len(product_chunks)} product chunks")
            print(f"✅ Saved combined chunks to: {combined_path}")
            
        else:
            print("⚠️ No product chunks found to integrate")
            
    except Exception as e:
        print(f"❌ Error integrating chunks: {e}")

def main():
    """Main processing function"""
    
    print("🚀 Instrument Oracle - Excel Data Processing")
    print("=" * 50)
    
    # Load Excel data
    df = load_excel_data()
    
    if df is None:
        print("❌ Failed to load Excel data")
        return
    
    # Process product data
    chunks = process_product_data(df)
    
    if not chunks:
        print("❌ No product chunks created")
        return
    
    # Create search index
    product_index = create_product_search_index(chunks)
    
    # Save processed data
    save_processed_data(chunks, product_index)
    
    # Integrate with existing chunks
    integrate_with_existing_chunks()
    
    print("\n✅ Excel data processing complete!")
    print("\n📋 Next steps:")
    print("1. The product data is now available for the AI system")
    print("2. You can ask questions about products and get recommendations")
    print("3. The system will link textbook knowledge with product solutions")

if __name__ == "__main__":
    main() 
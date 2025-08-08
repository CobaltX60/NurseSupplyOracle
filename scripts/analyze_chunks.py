# scripts/analyze_chunks.py
import json
import os

def analyze_chunks():
    """Analyze the chunks to understand the distribution"""
    
    # Load chunks
    with open('chunks.json', 'r') as f:
        chunks = json.load(f)
    
    print("📊 CHUNK ANALYSIS")
    print("=" * 50)
    
    # Group by source
    by_source = {}
    for chunk in chunks:
        source = chunk['source']
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(chunk)
    
    # Analyze each source
    for source, source_chunks in by_source.items():
        print(f"\n📚 {source}:")
        print(f"   Total chunks: {len(source_chunks)}")
        
        if source_chunks:
            # Calculate text statistics
            text_lengths = [len(chunk['text']) for chunk in source_chunks]
            avg_length = sum(text_lengths) / len(text_lengths)
            min_length = min(text_lengths)
            max_length = max(text_lengths)
            
            print(f"   Average chunk length: {avg_length:.0f} characters")
            print(f"   Min chunk length: {min_length} characters")
            print(f"   Max chunk length: {max_length} characters")
            
            # Show first chunk preview
            first_chunk = source_chunks[0]
            preview = first_chunk['text'][:200].replace('\n', ' ')
            print(f"   First chunk preview: {preview}...")
            
            # Check for empty or very short chunks
            short_chunks = [c for c in source_chunks if len(c['text']) < 100]
            if short_chunks:
                print(f"   ⚠️  {len(short_chunks)} chunks are very short (<100 chars)")
    
    print("\n" + "=" * 50)
    print(f"📊 Total chunks across all sources: {len(chunks)}")

if __name__ == "__main__":
    analyze_chunks() 
#!/usr/bin/env python3
"""
Test script to verify improved product integration
"""

import requests
import json
import time

def test_product_integration():
    """Test various product-related questions to verify integration"""
    
    base_url = "http://localhost:5001"
    
    # Test questions that should trigger product responses
    test_questions = [
        "What syringe products do we have available?",
        "What Medline products are in our inventory?",
        "What wound care supplies do we carry?",
        "What IV therapy products are available?",
        "What face shield products do we have?",
        "What BD products are available?",
        "What products do we have for dressing changes?",
        "What sterile products do we carry?"
    ]
    
    print("🧪 Testing Improved Product Integration")
    print("=" * 50)
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔍 Test {i}: {question}")
        print("-" * 40)
        
        try:
            # Send request
            response = requests.post(
                f"{base_url}/chat",
                json={"question": question},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                print(f"✅ Response received in {data.get('responseTime', 0)}ms")
                print(f"📏 Response length: {len(data.get('answer', ''))} characters")
                print(f"📝 Response: {data.get('answer', '')}")
                
                # Check for product references
                answer = data.get('answer', '').lower()
                sources = data.get('sources', [])
                
                product_indicators = [
                    'product', 'medline', 'bd', 'syringe', 'dressing', 
                    'shield', 'sterile', 'kit', 'erp', 'manufacturer'
                ]
                
                has_product_refs = any(indicator in answer for indicator in product_indicators)
                has_product_sources = any('product' in source.lower() or 'itemdata' in source.lower() for source in sources)
                
                if has_product_refs:
                    print("✅ Contains product references")
                else:
                    print("❌ No product references found")
                    
                if has_product_sources:
                    print("✅ Contains product sources")
                else:
                    print("❌ No product sources found")
                    
                print(f"📚 Sources: {sources}")
                
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
        
        # Brief pause between requests
        time.sleep(1)
    
    print("\n✅ Product integration test complete!")

if __name__ == "__main__":
    test_product_integration() 
#!/usr/bin/env python3
"""
Test script to verify page numbers in source citations
"""

import requests
import time

def test_page_numbers():
    """Test that page numbers appear in source citations"""
    
    print("🧪 Testing Page Numbers in Source Citations")
    print("=" * 50)
    
    # Test questions that should trigger different sources
    test_questions = [
        "What are the principles of infection control?",
        "How do you perform hand hygiene?",
        "What is surgical asepsis?",
        "What are the vital signs assessment procedures?",
        "How do you position a patient in bed?"
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔍 Test {i}: {question}")
        print("-" * 40)
        
        try:
            start_time = time.time()
            response = requests.post(
                "http://localhost:5001/chat",
                json={"question": question},
                timeout=30
            )
            end_time = time.time()
            
            if response.status_code == 200:
                result = response.json()
                response_time = result.get('responseTime', int((end_time - start_time) * 1000))
                is_cached = result.get('cached', False)
                
                print(f"✅ Response: {result['answer']}")
                print(f"⏱️ Response Time: {response_time}ms")
                print(f"📚 Sources: {result['sources']}")
                print(f"🔄 Cached: {is_cached}")
                
                # Check if page numbers are present
                has_page_numbers = any("Page" in source for source in result['sources'])
                if has_page_numbers:
                    print("✅ Page numbers found in sources!")
                else:
                    print("⚠️ No page numbers found in sources")
                
                # Check if product data was used
                if "ItemData.xlsx" in str(result['sources']):
                    print("🛍️ Product data was referenced!")
                    
            else:
                print(f"❌ Error: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed: {e}")
        
        # Wait between requests
        time.sleep(2)
    
    print("\n✅ Page number test complete!")

if __name__ == "__main__":
    test_page_numbers() 
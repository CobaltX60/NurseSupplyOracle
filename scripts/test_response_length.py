#!/usr/bin/env python3
"""
Test the improved response length from the Nurse Supply Oracle
"""

import requests
import json
import time

def test_response_length():
    """Test if responses are now longer and more complete"""
    
    print("🧪 Testing Response Length Improvements")
    print("=" * 50)
    
    # Test questions that should generate longer responses
    test_questions = [
        "What specific IV therapy products do we have in our inventory and how should they be used?",
        "What wound care products are available and what are their specifications?",
        "What syringe products do we carry and what are their different uses?",
        "What Medline products do we have and what are their features?"
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔍 Test {i}: {question}")
        print("-" * 60)
        
        try:
            # Send request
            response = requests.post('http://localhost:5001/chat', 
                                   json={'question': question},
                                   timeout=120)
            
            if response.status_code == 200:
                result = response.json()
                answer = result.get('answer', '')
                sources = result.get('sources', [])
                
                # Analyze response
                print(f"✅ Response received")
                print(f"📏 Response length: {len(answer)} characters")
                print(f"📝 Response preview: {answer[:200]}...")
                
                # Check if response is complete (ends with proper punctuation)
                if answer and not answer.endswith(('.', '!', '?')):
                    print("⚠️ Response appears to be truncated")
                else:
                    print("✅ Response appears complete")
                
                # Count sentences
                sentences = answer.split('.')
                print(f"📊 Number of sentences: {len(sentences)}")
                
                # Check for product sources
                product_sources = [s for s in sources if 'Product ID' in s]
                print(f"🛍️ Product sources found: {len(product_sources)}")
                
                if product_sources:
                    print(f"   Product IDs: {[s.split('Product ID: ')[1].split(')')[0] for s in product_sources]}")
                
            else:
                print(f"❌ Server error: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            print("❌ Server not running. Please start the server first.")
            break
        except requests.exceptions.Timeout:
            print("❌ Request timed out")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Wait between requests
        time.sleep(2)
    
    print(f"\n✅ Response length test complete!")

if __name__ == "__main__":
    test_response_length() 
#!/usr/bin/env python3
"""
Test script to verify response completeness and proper sentence-based truncation
"""

import requests
import json
import time

def test_response_completeness():
    """Test that responses are complete and well-formed"""
    
    print("🧪 Testing Response Completeness")
    print("=" * 50)
    
    # Test questions that should generate longer responses
    test_questions = [
        "What specific IV therapy products do we have and how should they be used?",
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
                response_time = result.get('responseTime', 0)
                
                # Analyze response
                print(f"✅ Response received in {response_time}ms")
                print(f"📏 Response length: {len(answer)} characters")
                print(f"📝 Full response: {answer}")
                
                # Check for completeness indicators
                if answer and answer.endswith(('.', '!', '?')):
                    print("✅ Response ends with proper punctuation")
                else:
                    print("⚠️ Response may be incomplete (no ending punctuation)")
                
                # Count sentences
                sentences = [s.strip() for s in answer.split('.') if s.strip()]
                print(f"📊 Number of complete sentences: {len(sentences)}")
                
                # Check for truncation indicators
                if '...' in answer:
                    print("⚠️ Response contains ellipsis (may be truncated)")
                else:
                    print("✅ No truncation indicators found")
                
                # Check for product references
                if any(word in answer.lower() for word in ['product', 'medline', 'cardinal', 'syringe']):
                    print("✅ Contains product references")
                else:
                    print("ℹ️ No product references found")
                
                # Check for textbook references
                if any(word in answer.lower() for word in ['nursing', 'patient', 'care', 'treatment']):
                    print("✅ Contains nursing textbook information")
                else:
                    print("ℹ️ Limited nursing textbook information")
                
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
    
    print(f"\n✅ Response completeness test complete!")

if __name__ == "__main__":
    test_response_completeness() 
#!/usr/bin/env python3
"""
Test new question performance
"""

import requests
import time

def test_new_question():
    """Test performance with a new question"""
    
    print("🧪 Testing New Question Performance")
    print("=" * 40)
    
    # Test a new question that shouldn't be cached
    test_question = "What equipment is needed for IV therapy?"
    print(f"🔍 Testing: {test_question}")
    
    start_time = time.time()
    response = requests.post(
        "http://localhost:5001/chat",
        json={"question": test_question},
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
        
        if "ItemData.xlsx" in result['sources']:
            print("🛍️ Product data was referenced!")
        
        return response_time, is_cached
    else:
        print(f"❌ Error: {response.status_code}")
        return None, None

if __name__ == "__main__":
    response_time, is_cached = test_new_question()
    if response_time is not None:
        print(f"\n📊 Performance Summary:")
        print(f"   • Response Time: {response_time}ms")
        print(f"   • Cached: {is_cached}")
        if not is_cached:
            print(f"   • This was a new question processed by the AI")
        else:
            print(f"   • This was a cached response") 
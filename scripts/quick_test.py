#!/usr/bin/env python3
"""
Quick test for optimized server
"""

import requests
import time

def test_optimized_server():
    """Quick test of the optimized server"""
    
    print("🧪 Quick Test - Optimized Server")
    print("=" * 40)
    
    # Test health endpoint
    try:
        health_response = requests.get("http://localhost:5001/health", timeout=5)
        if health_response.status_code == 200:
            health_data = health_response.json()
            print("✅ Server is running!")
            print(f"📊 Models Loaded: {health_data.get('models_loaded', False)}")
            print(f"📊 GPU Memory: {health_data.get('gpu_info', {}).get('allocated_gb', 'N/A')}GB")
            
            # Test a simple question
            test_question = "What supplies do I need for wound care?"
            print(f"\n🔍 Testing: {test_question}")
            
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
                
                print(f"✅ Response: {result['answer']}")
                print(f"⏱️ Response Time: {response_time}ms")
                print(f"📚 Sources: {result['sources']}")
                
                if "ItemData.xlsx" in result['sources']:
                    print("🛍️ Product data was referenced!")
                
                return True
            else:
                print(f"❌ Chat error: {response.status_code}")
                return False
                
        else:
            print(f"❌ Health check failed: {health_response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Server not responding: {e}")
        return False

if __name__ == "__main__":
    success = test_optimized_server()
    if success:
        print("\n✅ Optimized server test passed!")
    else:
        print("\n❌ Optimized server test failed!") 
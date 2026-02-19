#!/usr/bin/env python3
"""
Test script for product integration in Instrument Oracle
"""

import requests
import json
import time

def test_product_integration():
    """Test the enhanced system with product-related questions"""
    
    print("🧪 Testing Product Integration in Instrument Oracle")
    print("=" * 60)
    
    # Test questions that should trigger product recommendations
    test_questions = [
        "What supplies do I need for wound care?",
        "What products are available for patient monitoring?",
        "What equipment is needed for IV therapy?",
        "What are the best products for infection control?",
        "What supplies should I have for emergency care?"
    ]
    
    base_url = "http://localhost:5001"
    
    # Check if server is running
    try:
        health_response = requests.get(f"{base_url}/health", timeout=5)
        if health_response.status_code != 200:
            print("❌ Server is not responding properly")
            return
        print("✅ Server is running")
    except requests.exceptions.RequestException:
        print("❌ Server is not running. Please start it with: python scripts/chat_server_hf.py")
        return
    
    print(f"\n📊 Server Health: {health_response.json()}")
    
    # Test each question
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔍 Test {i}: {question}")
        print("-" * 50)
        
        try:
            response = requests.post(
                f"{base_url}/chat",
                json={"question": question},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Response: {result['answer']}")
                print(f"📚 Sources: {result['sources']}")
                print(f"⏱️ Response time: {result['responseTime']}ms")
                
                # Check if product data was used
                if "ItemData.xlsx" in result['sources']:
                    print("🛍️ Product data was referenced!")
                else:
                    print("⚠️ No product data referenced")
                    
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed: {e}")
        
        # Wait between requests
        time.sleep(2)
    
    print("\n✅ Product integration test complete!")

if __name__ == "__main__":
    test_product_integration() 
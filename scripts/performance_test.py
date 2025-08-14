#!/usr/bin/env python3
"""
Performance test script for Nurse Supply Oracle
Compares optimized vs original versions
"""

import requests
import json
import time
import statistics
from datetime import datetime

def test_server_performance(server_url, test_questions, server_name):
    """Test server performance with multiple questions"""
    
    print(f"\n🧪 Testing {server_name}")
    print("=" * 50)
    
    response_times = []
    cache_hits = 0
    total_requests = len(test_questions)
    
    # Check if server is running
    try:
        health_response = requests.get(f"{server_url}/health", timeout=5)
        if health_response.status_code != 200:
            print(f"❌ {server_name} is not responding properly")
            return None
        print(f"✅ {server_name} is running")
        
        health_data = health_response.json()
        print(f"📊 GPU Memory: {health_data.get('gpu_info', {}).get('allocated_gb', 'N/A')}GB")
        print(f"📊 Models Loaded: {health_data.get('models_loaded', False)}")
        
    except requests.exceptions.RequestException:
        print(f"❌ {server_name} is not running")
        return None
    
    # Test each question
    for i, question in enumerate(test_questions, 1):
        print(f"\n🔍 Test {i}/{total_requests}: {question[:40]}...")
        
        try:
            start_time = time.time()
            response = requests.post(
                f"{server_url}/chat",
                json={"question": question},
                timeout=30
            )
            end_time = time.time()
            
            if response.status_code == 200:
                result = response.json()
                response_time = result.get('responseTime', int((end_time - start_time) * 1000))
                is_cached = result.get('cached', False)
                
                response_times.append(response_time)
                
                if is_cached:
                    cache_hits += 1
                    print(f"   ⚡ Cached: {response_time}ms")
                else:
                    print(f"   🔄 New: {response_time}ms")
                
                # Check if product data was used
                sources = result.get('sources', [])
                if "ItemData.xlsx" in sources:
                    print(f"   🛍️ Product data referenced")
                    
            else:
                print(f"   ❌ Error: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Request failed: {e}")
        
        # Small delay between requests
        time.sleep(0.5)
    
    # Calculate statistics
    if response_times:
        avg_time = statistics.mean(response_times)
        min_time = min(response_times)
        max_time = max(response_times)
        cache_rate = (cache_hits / total_requests) * 100
        
        print(f"\n📊 {server_name} Performance Summary:")
        print(f"   • Average Response Time: {avg_time:.1f}ms")
        print(f"   • Fastest Response: {min_time}ms")
        print(f"   • Slowest Response: {max_time}ms")
        print(f"   • Cache Hit Rate: {cache_rate:.1f}%")
        print(f"   • Total Requests: {total_requests}")
        
        return {
            'server_name': server_name,
            'avg_time': avg_time,
            'min_time': min_time,
            'max_time': max_time,
            'cache_rate': cache_rate,
            'response_times': response_times
        }
    
    return None

def main():
    """Main performance test function"""
    
    print("🚀 Nurse Supply Oracle - Performance Test")
    print("=" * 60)
    print(f"⏰ Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test questions covering different scenarios
    test_questions = [
        "What supplies do I need for wound care?",
        "What products are available for patient monitoring?",
        "What equipment is needed for IV therapy?",
        "What are the best products for infection control?",
        "What supplies should I have for emergency care?",
        "How do I properly clean a wound?",
        "What monitoring equipment is essential for critical care?",
        "What are the safety protocols for IV administration?",
        "What products help prevent hospital-acquired infections?",
        "What emergency supplies should be readily available?"
    ]
    
    # Test both servers
    results = []
    
    # Test optimized server
    optimized_result = test_server_performance(
        "http://localhost:5001", 
        test_questions, 
        "Optimized Server"
    )
    if optimized_result:
        results.append(optimized_result)
    
    # Test original server (if running on different port)
    original_result = test_server_performance(
        "http://localhost:5002", 
        test_questions, 
        "Original Server"
    )
    if original_result:
        results.append(original_result)
    
    # Compare results
    if len(results) >= 2:
        print(f"\n🏆 Performance Comparison")
        print("=" * 50)
        
        optimized = results[0] if results[0]['server_name'] == 'Optimized Server' else results[1]
        original = results[1] if results[1]['server_name'] == 'Original Server' else results[0]
        
        speed_improvement = ((original['avg_time'] - optimized['avg_time']) / original['avg_time']) * 100
        
        print(f"⚡ Speed Improvement: {speed_improvement:.1f}% faster")
        print(f"📈 Average Response Time Improvement: {original['avg_time'] - optimized['avg_time']:.1f}ms")
        print(f"🎯 Cache Hit Rate Difference: {optimized['cache_rate'] - original['cache_rate']:.1f}%")
        
        if speed_improvement > 0:
            print(f"✅ Optimized server is {speed_improvement:.1f}% faster!")
        else:
            print(f"⚠️ Original server appears faster (check if both are running)")
    
    elif len(results) == 1:
        print(f"\n📊 Single Server Results")
        print("=" * 50)
        result = results[0]
        print(f"Server: {result['server_name']}")
        print(f"Average Response Time: {result['avg_time']:.1f}ms")
        print(f"Cache Hit Rate: {result['cache_rate']:.1f}%")
    
    else:
        print(f"\n❌ No servers responded to tests")
        print("Make sure at least one server is running:")
        print("  • Optimized: python scripts/chat_server_optimized.py")
        print("  • Original: python scripts/chat_server_hf.py")
    
    print(f"\n⏰ Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main() 
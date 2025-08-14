#!/usr/bin/env python3
"""
Check the status of both backend and frontend servers
"""

import requests
import json

def check_servers():
    """Check if both servers are running"""
    
    print("🔍 Checking Server Status")
    print("=" * 40)
    
    # Check backend
    try:
        response = requests.get('http://localhost:5001/health')
        if response.status_code == 200:
            data = response.json()
            print("✅ Backend Server (Port 5001):")
            print(f"   Status: {data['status']}")
            print(f"   Models Loaded: {data['models_loaded']}")
            print(f"   GPU: {data['gpu_info']['total_gb']}GB total")
            print(f"   GPU Memory: {data['gpu_info']['allocated_gb']}GB allocated")
            print(f"   Cache Size: {data['cache_size']}")
            print(f"   Total Requests: {data['performance_stats']['total_requests']}")
        else:
            print(f"❌ Backend Server: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Backend Server: {e}")
    
    print()
    
    # Check frontend
    try:
        response = requests.get('http://localhost:3001')
        if response.status_code == 200:
            print("✅ Frontend Server (Port 3001):")
            print("   Status: Running")
            print("   URL: http://localhost:3001")
        else:
            print(f"❌ Frontend Server: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Frontend Server: {e}")
    
    print()
    print("🎯 Application URLs:")
    print("   Frontend: http://localhost:3001")
    print("   Backend Health: http://localhost:5001/health")
    print("   Backend Chat: http://localhost:5001/chat")

if __name__ == "__main__":
    check_servers() 
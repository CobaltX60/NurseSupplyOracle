# scripts/download_model.py
import requests
import os
import sys

def download_model():
    """Download a Hugging Face model for testing"""
    
    print("🚀 Nurse Supply Oracle - Model Download")
    print("=" * 50)
    print("This application now uses Hugging Face models directly!")
    print("No manual model downloads are required.")
    print()
    print("The system will automatically download and cache models from:")
print("  - mistralai/Mistral-7B-Instruct")
print("  - microsoft/DialoGPT-large")
    print()
    print("✅ Models are downloaded automatically on first use")
    print("✅ 4-bit quantization for optimal GPU performance")
    print("✅ Cached locally for faster subsequent loads")
    print()
    print("To start using the application:")
    print("1. Run: python scripts/chat_server_hf.py")
    print("2. Open: http://localhost:3000")
    print("3. Ask your first question!")
    print()
    print("The first question will take longer as the model downloads.")
    print("Subsequent questions will be much faster.")

if __name__ == "__main__":
    download_model() 
# scripts/download_model.py
"""Instrument Oracle - Model / API setup info.
The chat LLM is Google Gemini 2.0 Flash (API). Only the embedding model is downloaded locally."""

def download_model():
    print("🚀 Instrument Oracle - Setup")
    print("=" * 50)
    print("Chat LLM: Google Gemini 2.0 Flash (API). Set GEMINI_API_KEY in .env.")
    print("Embeddings: sentence-transformers/all-MiniLM-L6-v2 (downloaded on first rebuild or chat server start).")
    print()
    print("To run the application:")
    print("1. Copy .env.example to .env and set GEMINI_API_KEY (get one at https://aistudio.google.com/apikey)")
    print("2. Run: python scripts/chat_server.py")
    print("3. Run: npm run dev  (Next.js on port 3001)")
    print("4. Put PDFs in scripts/source_files/ and run: python scripts/rebuild.py")
    print("5. Restart the chat server, then ask questions in the browser.")

if __name__ == "__main__":
    download_model() 
# scripts/test_setup.py
import sys

def test_imports():
    """Test that all required packages can be imported"""
    print("Testing imports...")
    
    try:
        import pdfplumber
        print("✓ pdfplumber imported successfully")
    except ImportError as e:
        print(f"✗ pdfplumber import failed: {e}")
        return False
    
    try:
        import sentence_transformers
        print("✓ sentence-transformers imported successfully")
    except ImportError as e:
        print(f"✗ sentence-transformers import failed: {e}")
        return False
    
    try:
        import faiss
        print("✓ faiss imported successfully")
    except ImportError as e:
        print(f"✗ faiss import failed: {e}")
        return False
    
    try:
        import numpy as np
        print("✓ numpy imported successfully")
    except ImportError as e:
        print(f"✗ numpy import failed: {e}")
        return False
    
    try:
        import torch
        print("✓ torch imported successfully")
    except ImportError as e:
        print(f"✗ torch import failed: {e}")
        return False
    
    return True

def test_model_loading():
    """Test that the sentence transformer model can be loaded"""
    print("\nTesting model loading...")
    
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✓ Sentence transformer model loaded successfully")
        
        # Test encoding
        test_text = ["This is a test sentence."]
        embeddings = model.encode(test_text)
        print(f"✓ Model encoding test passed (embedding shape: {embeddings.shape})")
        return True
    except Exception as e:
        print(f"✗ Model loading failed: {e}")
        return False

def test_faiss():
    """Test FAISS functionality"""
    print("\nTesting FAISS...")
    
    try:
        import faiss
        import numpy as np
        
        # Create a simple test index
        dimension = 384  # all-MiniLM-L6-v2 dimension
        index = faiss.IndexFlatL2(dimension)
        
        # Create some test vectors
        test_vectors = np.random.random((10, dimension)).astype('float32')
        index.add(test_vectors)
        
        # Test search
        query_vector = np.random.random((1, dimension)).astype('float32')
        D, I = index.search(query_vector, 3)
        
        print("✓ FAISS index creation and search test passed")
        return True
    except Exception as e:
        print(f"✗ FAISS test failed: {e}")
        return False

def main():
    print("=== Textbook Chat Setup Test ===\n")
    
    # Test imports
    if not test_imports():
        print("\n❌ Setup test failed: Import errors")
        sys.exit(1)
    
    # Test model loading
    if not test_model_loading():
        print("\n❌ Setup test failed: Model loading errors")
        sys.exit(1)
    
    # Test FAISS
    if not test_faiss():
        print("\n❌ Setup test failed: FAISS errors")
        sys.exit(1)
    
    print("\n✅ All tests passed! Your setup is ready.")
    print("\nNext steps:")
    print("1. Place your textbook.pdf in the project root")
    print("2. Run: python scripts/prepare.py")
    print("3. Run: npm run dev")
    print("4. Open http://localhost:3000")

if __name__ == "__main__":
    main() 
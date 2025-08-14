# scripts/test_pdf_extraction.py
import os
import fitz  # PyMuPDF
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

def test_pymupdf(pdf_path):
    """Test PyMuPDF extraction"""
    print("🔍 Testing PyMuPDF...")
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"   Found {total_pages} pages")
        
        text_pages = 0
        total_chars = 0
        
        for i in range(min(10, total_pages)):  # Test first 10 pages
            page = doc.load_page(i)
            text = page.get_text("text")
            if len(text.strip()) > 0:
                text_pages += 1
                total_chars += len(text)
        
        doc.close()
        print(f"   Pages with text: {text_pages}/10")
        print(f"   Total characters: {total_chars}")
        return text_pages > 0
    except Exception as e:
        print(f"   Error: {e}")
        return False

def test_pymupdf(pdf_path):
    """Test PyMuPDF extraction"""
    print("🔍 Testing PyMuPDF...")
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        text_pages = 0
        total_chars = 0
        
        for i in range(min(10, total_pages)):  # Test first 10 pages
            page = doc.load_page(i)
            text = page.get_text("text")
            if len(text.strip()) > 0:
                text_pages += 1
                total_chars += len(text)
        
        doc.close()
        print(f"   Pages with text: {text_pages}/10")
        print(f"   Total characters: {total_chars}")
        return text_pages > 0
    except Exception as e:
        print(f"   Error: {e}")
        return False

def test_ocr(pdf_path):
    """Test OCR extraction"""
    print("🔍 Testing OCR...")
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        ocr_pages = 0
        total_chars = 0
        
        for i in range(min(3, total_pages)):  # Test first 3 pages (OCR is slow)
            page = doc.load_page(i)
            
            # Convert to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Extract text with OCR
            ocr_text = pytesseract.image_to_string(img)
            if len(ocr_text.strip()) > 0:
                ocr_pages += 1
                total_chars += len(ocr_text)
                print(f"   Page {i+1}: {len(ocr_text)} characters")
        
        doc.close()
        print(f"   Pages with OCR text: {ocr_pages}/3")
        print(f"   Total characters: {total_chars}")
        return ocr_pages > 0
    except Exception as e:
        print(f"   Error: {e}")
        return False

def main():
    pdf_path = "source_files/textbook3.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ {pdf_path} not found")
        return
    
    print(f"📄 Testing PDF extraction methods for {pdf_path}")
    print("=" * 60)
    
    # Test each method
    results = {}
    
    results['pymupdf'] = test_pymupdf(pdf_path)
    print()
    
    results['pymupdf'] = test_pymupdf(pdf_path)
    print()
    
    results['ocr'] = test_ocr(pdf_path)
    print()
    
    # Summary
    print("📊 SUMMARY:")
    print("=" * 60)
    for method, success in results.items():
        status = "✅ Works" if success else "❌ Failed"
        print(f"   {method}: {status}")
    
    print("\n💡 RECOMMENDATIONS:")
    if results['pymupdf']:
        print("   - Use PyMuPDF for best text extraction")
    elif results['ocr']:
        print("   - Use OCR for image-based PDFs")
    else:
        print("   - PDF may be corrupted or password-protected")
        print("   - Try finding a different version of the textbook")

if __name__ == "__main__":
    main() 
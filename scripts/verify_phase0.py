#!/usr/bin/env python3
"""
Phase 0 verification for Instrument Oracle.
Run from project root: python scripts/verify_phase0.py
"""
import json
import os
import sys

# Project root (parent of scripts/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def step(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    sym = "[OK]" if ok else "[--]"
    print(f"  {sym} {name}: {status}" + (f" - {detail}" if detail else ""))
    return ok

def main():
    print("=" * 60)
    print("Instrument Oracle - Phase 0 Verification")
    print("=" * 60)
    os.chdir(ROOT)
    all_ok = True

    # 0.1 Chunk JSON and FAISS index
    print("\n[0.1] Chunk data and FAISS index")
    chunks_path = os.path.join(ROOT, "chunks_combined_with_pages.json")
    faiss_path = os.path.join(ROOT, "faiss_index_with_pages.idx")
    if not os.path.exists(chunks_path):
        chunks_path = os.path.join(ROOT, "chunks_combined.json")
        faiss_path = os.path.join(ROOT, "faiss_index_all_pymupdf.idx")
    if not os.path.exists(chunks_path):
        chunks_path = os.path.join(ROOT, "chunks_all_pymupdf.json")
    chunk_ok = os.path.exists(chunks_path)
    all_ok &= step("Chunk JSON exists", chunk_ok, os.path.basename(chunks_path) if chunk_ok else "No chunks_*.json found")
    faiss_ok = os.path.exists(faiss_path)
    all_ok &= step("FAISS index exists", faiss_ok, os.path.basename(faiss_path) if faiss_ok else "No faiss_index_*.idx found")

    if chunk_ok and faiss_ok:
        try:
            with open(chunks_path, "r", encoding="utf-8") as f:
                chunks = json.load(f)
            import faiss
            idx = faiss.read_index(faiss_path)
            match = len(chunks) == idx.ntotal
            all_ok &= step("Chunk count matches FAISS", match, f"{len(chunks)} chunks, index ntotal={idx.ntotal}")
            all_ok &= step("Embedding dimension", idx.d == 384, f"dim={idx.d} (expected 384)")
        except Exception as e:
            all_ok &= step("Chunk/FAISS consistency", False, str(e))

    # 0.2 CUDA / GPU
    print("\n[0.2] CUDA / GPU")
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        all_ok &= step("CUDA available", cuda_ok)
        if cuda_ok:
            all_ok &= step("GPU device", True, torch.cuda.get_device_name(0))
    except Exception as e:
        all_ok &= step("PyTorch/CUDA", False, str(e))

    # 0.3 Backend dependencies (quick import check)
    print("\n[0.3] Backend dependencies")
    for mod in ["flask", "faiss", "sentence_transformers", "transformers", "torch"]:
        try:
            __import__(mod)
            all_ok &= step(f"  {mod}", True)
        except ImportError as e:
            all_ok &= step(f"  {mod}", False, str(e))

    # 0.4 Node/frontend (optional: only check if node exists)
    print("\n[0.4] Frontend")
    node_modules = os.path.join(ROOT, "node_modules")
    package_json = os.path.join(ROOT, "package.json")
    has_package = os.path.exists(package_json)
    has_node_modules = os.path.exists(node_modules)
    all_ok &= step("package.json exists", has_package)
    all_ok &= step("node_modules installed", has_node_modules, "Run: npm install" if not has_node_modules else "")

    # Summary and next steps
    print("\n" + "=" * 60)
    if all_ok:
        print("Phase 0 automated checks: PASSED")
        print("\nNext steps (manual):")
        print("  1. Start backend:  python scripts/chat_server.py")
        print("     Wait until you see: 'All models loaded successfully!' and 'Flask server on port 5001'")
        print("  2. In another terminal, start frontend:  npm run dev")
        print("  3. Open http://localhost:3001 and send a test question")
        print("  4. Confirm you get an answer with sources")
        print("\nOptional: GET http://localhost:5001/health after backend is up")
    else:
        print("Phase 0 automated checks: FAILED — fix the items above and re-run.")
        sys.exit(1)
    print("=" * 60)

if __name__ == "__main__":
    main()

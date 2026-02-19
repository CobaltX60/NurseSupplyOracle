# Instrument Oracle — Current Build

This document describes the **current state** of the application after implementing SQLite, structured responses, catalog ingestion, image extraction, and product cards.

## Architecture Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | Next.js 15 (React 19), TypeScript, Tailwind | Chat UI; Catalog setup UI; calls Next.js API |
| API | Next.js routes (`/api/chat`, `/api/catalogs/*`, `/api/image/*`) | Proxies to Flask backend; serves images |
| Backend | Flask (Python) on port 5001 | Loads models, runs search + LLM, catalog/product/listing APIs |
| Embeddings | SentenceTransformer `all-MiniLM-L6-v2` | Encode question and chunk text for FAISS |
| Vector search | FAISS | Find top-k chunks by similarity (index in `data/faiss_index.idx`) |
| LLM | **Qwen2.5-7B-Instruct** (Hugging Face, 8-bit quantized) | Generate answer from context; product extraction from page text |
| Storage | **SQLite** (`data/instrument_oracle.db`) + FAISS index | Sources, chunks, images, products, catalog_config, catalog_samples |

## Data Flow (Current)

1. **Ingest / Rebuild** (`python scripts/rebuild.py`)
   - Reads PDFs from `scripts/source_files/`.
   - Extracts text → chunks (size/overlap in `rebuild.py`); inserts into **sources** and **chunks**.
   - Extracts images: XObject refs (`get_images(full=True)`), inline (BI/ID/EI via `get_text("dict", TEXT_PRESERVE_IMAGES)`), orphan xrefs (Form XObjects), small vector regions (`cluster_drawings` / `get_drawings` + clip render), no full-page render. Writes files under `data/images/<source_id>/` and rows in **images**.
   - Builds FAISS from chunk text; writes `data/faiss_index.idx`.
   - Clears legacy response cache.

2. **Startup (Flask)**  
   - Load embedding model (SentenceTransformer).  
   - Load **chunks from SQLite** (joined with sources); load **FAISS index** from `data/faiss_index.idx`.  
   - Load **Qwen2.5-7B-Instruct** (8-bit) and tokenizer.  
   - No JSON chunk files; DB + FAISS file are the source of truth.

3. **Request (Chat)**  
   - Client POSTs `{ "question": "..." }` to Next.js `/api/chat` → Flask `POST /chat`.  
   - Flask: content-signature cache check → embed question → FAISS search (k=10, max 5 chunks in context) → build context → optional product/image refs for part numbers in question → **Qwen** generate → clean response (ChatML + Mistral artifacts stripped) → return JSON.

4. **Response (structured)**  
   - `answer`: string.  
   - `sources`: list of source citations (e.g. "Catalog Name (Page N)").  
   - `image_refs`: list of image URLs for products whose part number appears in the question.  
   - `product_cards`: list of full product objects (id, manufacturer_part_number, product_name, description, secondary_description, category, manufacturer, image_refs) for the same part-number match.  
   - `responseTime`, `cached`, `gpu_utilization`.

5. **Frontend**  
   - Chat: shows answer, sources, and **right panel**: if `product_cards` present, shows **product information cards** (part number, name, description, images); else shows `image_refs` as image list.  
   - Catalog setup: select catalog, view pages/images/products, **Build product listing** (all or by-page), **Assign image to part number** (modal), export products.

## Key Files and Paths

### Backend (Python)

- **`scripts/chat_server.py`** — Flask app: model loading (embedding + Qwen2.5-7B 8-bit), chunk load from SQLite, FAISS load from file, chat endpoint, product cards, catalog/product/listing/assign-image APIs, image serve.
- **`scripts/rebuild.py`** — Single ingest script: PDFs from `scripts/source_files/` → text chunks + image extraction (XObject, inline, orphans, vector regions) → SQLite (sources, chunks, images) + FAISS index. Config: `CHUNK_SIZE`, `CHUNK_OVERLAP`, `INCLUDE_VECTOR_REGIONS`, etc.

### Data

- **`data/instrument_oracle.db`** — SQLite: sources, chunks, images, products, product_images, catalog_config, catalog_samples.
- **`data/faiss_index.idx`** — FAISS index (built by rebuild; dimension 384).
- **`data/images/<source_id>/page_<n>_<i>.<ext>`** — Extracted and rendered images.

### Frontend

- **`src/app/page.tsx`** — Chat UI: question input, message list, **product cards** or image list in right panel, sources, response time.
- **`src/app/catalog-setup/page.tsx`** — Catalog selection, pages/images, products list, Build product listing (all / by page), Assign image to part number, export.
- **`src/app/api/chat/route.ts`** — Proxies to Flask; returns answer, sources, image_refs, product_cards.
- **`src/app/api/image/[...path]/route.ts`** — Proxies image requests to Flask.

### Config / Docs

- **`requirements.txt`** / **`requirements-gpu.txt`** — Python deps (Flask, FAISS, PyTorch, transformers, sentence-transformers, PyMuPDF, etc.).
- **`documents/`** — Markdown docs (overview, plan, GPU, images, catalog model, etc.).

## Chunk and Product Schema (Current)

- **chunks**: id, source_id, page_number, chunk_index, text, type, metadata_json.  
- **sources**: id, name, file_path.  
- **images**: id, source_id, page_number, image_index, file_path, width, height.  
- **products**: id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, etc.  
- **product_images**: product_id, image_id, display_order.  
- **catalog_config**, **catalog_samples**: per-catalog instructions and part-number/image samples for extraction and chat.

## What Exists vs What’s Missing

| Capability | Status |
|------------|--------|
| Run Qwen2.5-7B locally (8-bit, GPU) | ✅ In place |
| Ingest PDFs → text chunks + images → SQLite + FAISS | ✅ Via `scripts/rebuild.py` |
| Semantic search (FAISS) over chunks from DB | ✅ In place |
| Ask a question, get structured answer + sources + image_refs + product_cards | ✅ In place |
| Response cache (content-signature keyed) | ✅ In place |
| SQLite for long-term storage | ✅ Implemented |
| Structured response (product cards, image refs) | ✅ Implemented |
| Image extraction (XObject, inline, orphans, vector regions) | ✅ In rebuild.py |
| Catalog setup UI (Build listing, Assign image, export) | ✅ In place |
| Product listing build (all or by-page; 10 min timeout per page) | ✅ In place |
| Vision LLM / OCR on images | ❌ LLM is text-only; no vision or OCR in pipeline |
| Optional: test set and refinement loop | ❌ Documented in plan; not automated |

## Verification Checklist

1. **Environment**  
   - Python 3.8+ with `requirements-gpu.txt` (or `requirements.txt`).  
   - Node.js 18+; `npm install` in project root.  
   - Optional: `HF_TOKEN` if the model is gated.

2. **Data**  
   - PDFs in `scripts/source_files/`.  
   - Run `python scripts/rebuild.py` → creates/updates `data/instrument_oracle.db`, `data/faiss_index.idx`, `data/images/`.

3. **Backend**  
   - `python scripts/chat_server.py` → loads embedding, chunks from DB, FAISS, Qwen2.5-7B; listens on 5001.  
   - `GET http://localhost:5001/health` returns healthy and (if GPU) memory info.

4. **Frontend**  
   - `npm run dev` → Next.js (e.g. 3001).  
   - Chat: ask a question → response with answer, sources, and (if part number in question) product cards or image refs in right panel.  
   - Catalog setup: select catalog → Build product listing (by page recommended for large catalogs); assign image to part number as needed.

5. **Optional**  
   - `python scripts/verify_phase0.py` — may still reference legacy JSON paths; primary path is now rebuild → SQLite + FAISS.

---

*For the phased plan and future work, see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). For image extraction details (xRef, inline, vector regions), see [NEXT_STEPS_SECONDARY_IMAGES.md](NEXT_STEPS_SECONDARY_IMAGES.md).*

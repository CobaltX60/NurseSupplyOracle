# Instrument Oracle — Implementation Plan

This plan describes the path to a **starting point where users can ask questions of the LLM and receive a structured result**, with **SQLite** used for long-term data storage. The **current build** (see [CURRENT_BUILD.md](CURRENT_BUILD.md)) has already implemented most of these phases.

---

## Current Status (as of latest build)

| Phase | Status | Notes |
|-------|--------|--------|
| **0** | ✅ Done | Verify build: SQLite + FAISS + Qwen2.5-7B; rebuild from `scripts/source_files/`. |
| **1** | ✅ Done | SQLite schema (sources, chunks, images, products, product_images, catalog_config, catalog_samples); chunks and FAISS built by `rebuild.py`. |
| **2** | ✅ Done | Single ingest script `scripts/rebuild.py` reads PDFs from `source_files/`, writes to SQLite and FAISS. |
| **3** | ✅ Done | Structured API response: `answer`, `sources`, `image_refs`, `product_cards`; UI shows product info cards or image list. |
| **4** | ✅ Done | Image extraction in rebuild (XObject, inline, orphans, vector regions); images table and `data/images/`; image_refs and product_cards in chat. |
| **5** | Optional | Refinement: test set, chunk/prompt tuning; not automated. |

The **LLM** in use is **Qwen2.5-7B-Instruct (8-bit)**, not Mistral 7B. Catalog setup UI provides Build product listing (all or by-page) and Assign image to part number.

---

## Target Starting Point (Definition of Done)

- User asks a natural-language question in the UI.  
- Backend retrieves relevant chunks (from SQLite + FAISS).  
- **Qwen2.5-7B** (or current LLM) generates an answer using that context.  
- API returns a **structured result**, e.g.:
  - `answer`: string (main answer text).  
  - `sources`: list of source citations (document + page).  
  - `product_cards` / `image_refs`: list of product matches with part numbers, names, and image refs.  
- Chunk text and metadata (and product entities) are stored in **SQLite**.  
- FAISS index is built from SQLite by `rebuild.py` so search remains fast.

---

## Phase 0: Verify Current Build

**Goal:** Confirm the existing pipeline works before adding SQLite or changing response shape.

| Step | Action |
|------|--------|
| 0.1 | Run **`python scripts/verify_phase0.py`** from project root. This checks: chunk JSON + FAISS index exist and match; CUDA/GPU; backend deps; `node_modules`. |
| 0.2 | Start Flask: `python scripts/chat_server.py`; wait until you see "All models loaded successfully!" and server on port 5001; then `GET http://localhost:5001/health` returns OK. |
| 0.3 | In another terminal, start Next.js: `npm run dev`; open http://localhost:3001 and send a test question; confirm answer and sources return. |
| 0.4 | Optionally run `scripts/check_cuda.py` and `scripts/performance_test.py` to confirm LLM and GPU. |

**Exit criteria:** User can ask a question and receive a coherent answer with sources; no SQLite or structured response yet.

---

## Phase 1: SQLite Schema and Storage

**Goal:** Introduce SQLite as the source of truth for chunks and metadata; keep FAISS for vector search.

### 1.1 Database Location and Tooling

- Create a single SQLite database file, e.g. `instrument_oracle.db` in the project root (or a `data/` directory).  
- Add `data/` to `.gitignore` if the DB lives there; optionally commit an empty DB or schema-only script.  
- Use Python’s `sqlite3` (stdlib) or a thin wrapper; no ORM required for the initial build.

### 1.2 Suggested Schema (Minimal for Chunks)

```sql
-- Source documents (PDFs, etc.)
CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  file_path TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- Chunks: text + metadata (one row per chunk)
CREATE TABLE chunks (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  page_number INTEGER,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  type TEXT,  -- e.g. 'text', 'product', 'instrument'
  metadata_json TEXT,  -- flexible: part_number, product_name, etc.
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(source_id, page_number, chunk_index)
);

-- Optional: product/instrument entities for structured response
CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  chunk_id INTEGER NOT NULL REFERENCES chunks(id),
  part_number TEXT,
  name TEXT,
  description TEXT,
  attributes_json TEXT,
  image_path_or_ref TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- Embeddings: store vector for FAISS rebuild (or keep FAISS index file and sync from chunks)
-- Option A: store blob per chunk (dim 384 for all-MiniLM-L6-v2)
CREATE TABLE chunk_embeddings (
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id),
  embedding BLOB NOT NULL
);
```

- **sources** — One row per ingested document (e.g. one PDF catalog).  
- **chunks** — One row per text chunk; `metadata_json` can hold part numbers, product names, etc., until a fuller schema is added.  
- **products** — Optional; for structured “instrument matches” in the API (can be populated from chunk metadata or a separate parser).  
- **chunk_embeddings** — Optional if you prefer to rebuild FAISS from SQLite on startup; otherwise keep generating FAISS index files from the same chunks that are in the DB.

### 1.3 Migration from Current JSON

- Write a one-off script that:
  - Reads existing `chunks_combined_with_pages.json` (or current primary chunk file).  
  - Inserts into `sources` and `chunks` (and optionally `products` if you parse product chunks).  
  - Builds FAISS from chunk text (existing embedding model), then either:  
    - Writes `faiss_index_*.idx` as today, or  
    - Stores vectors in `chunk_embeddings` and rebuilds FAISS in memory at startup from DB.  
- After migration, **chat_server** can either:  
  - Keep loading chunks from JSON for a transition period, or  
  - Load chunks from SQLite and build/load FAISS from DB (or from a file that was built from DB).

**Exit criteria:** Chunk data exists in SQLite; FAISS index (file or in-memory from DB) works for search; chat still returns answers as today.

---

## Phase 2: Ingest Pipeline Writes to SQLite

**Goal:** New PDF (and other) ingest writes to SQLite and updates the vector index.

| Step | Action |
|------|--------|
| 2.1 | Refactor or add a script (e.g. `ingest_pdf_to_db.py`) that: uses PyMuPDF to extract text and page numbers; chunks text; inserts into `sources` and `chunks`; computes embeddings and updates FAISS (and optionally `chunk_embeddings`). |
| 2.2 | Reuse or adapt `prepare_pymupdf_with_pages.py` logic so chunk size and overlap match current behavior. |
| 2.3 | Ensure `source_files/` (or a configurable path) is the default location for PDFs; document in `documents/PDF_PATH_UPDATES.md` or PROJECT_OVERVIEW. |

**Exit criteria:** Running the ingest script on a new PDF adds rows to SQLite and makes that content searchable via the existing chat flow.

---

## Phase 3: Structured API Response

**Goal:** Chat endpoint returns a structured result (answer + sources + product/instrument matches).

### 3.1 Response Shape (Example)

```json
{
  "answer": "Main answer text from the LLM.",
  "sources": [
    { "document": "Catalog A", "page": 12 },
    { "document": "Product List", "page": null }
  ],
  "instruments": [
    {
      "part_number": "ABC-123",
      "name": "Forceps Type X",
      "snippet": "Short text from chunk",
      "source_id": 1,
      "page_number": 12,
      "image_ref": null
    }
  ],
  "responseTime": 1500,
  "cached": false
}
```

### 3.2 Backend Changes

- In `chat_server.py`, after retrieving top-k chunks from FAISS:  
  - Resolve chunk IDs to full rows from SQLite (if chunks are loaded from DB) or keep current in-memory chunk list that was seeded from DB.  
  - Build context string for the LLM as today.  
  - Optionally: from the same chunks, extract or look up product/instrument rows (part number, name, page, image ref) from `chunks.metadata_json` or from `products` table.  
- Add a simple **structure layer**: e.g. parse LLM output for “product lines” or rely on chunk metadata to build `instruments` list.  
- Return the structured JSON above from `/chat`.

### 3.3 Frontend

- Update `src/app/api/chat/route.ts` to pass through the new fields.  
- Update `src/app/page.tsx` to display `sources` and `instruments` (e.g. part number, name, snippet, “View page” or image link if present).

**Exit criteria:** One question returns JSON with `answer`, `sources`, and `instruments` (or `products`); UI shows them in a clear way.

---

## Phase 4: PDF Image Extraction and References (Optional for “Starting Point”)

**Goal:** Extract images from PDF catalogs and store references so structured results can include “visual elements.”

| Step | Action |
|------|--------|
| 4.1 | In ingest script, use PyMuPDF to extract images per page; save under e.g. `data/images/{source_id}/{page}_{index}.png`. |
| 4.2 | Store in DB: `chunks.image_path_or_ref` or an `images` table (page, path, optional link to chunk). |
| 4.3 | In structured response, include `image_ref` (path or URL) for each instrument/product when available. |
| 4.4 | Frontend: show thumbnail or link for “View in catalog” where `image_ref` is present. |

This can be deferred until after Phase 3 if the priority is “ask and get structured result” first.

---

## Phase 5: Refinement and Evaluation

**Goal:** Improve recall and accuracy of answers from the PDFs.

- Add a small set of **test questions** with expected instrument/part number or source.  
- After each change (chunk size, prompt, k, or schema), run the test set and compare expected vs actual.  
- Document findings in `documents/` (e.g. “Refinement log” or a short section in PROJECT_OVERVIEW).  
- Iterate on:  
  - Chunking strategy (by section, by product, token size).  
  - Prompt wording for “instrument catalog” and “structured” answers.  
  - Retrieval (k, filters by source or type).

---

## Summary: Order of Work

| Phase | Focus | Outcome |
|-------|--------|---------|
| **0** | Verify current build | Qwen + FAISS + SQLite chunks working end-to-end |
| **1** | SQLite schema + migration | Chunks (and optional products) in DB; search still works |
| **2** | Ingest → SQLite | New PDFs populate DB and index |
| **3** | Structured response | API and UI return/show answer + sources + instruments |
| **4** | Images (optional) | Image extraction and refs in structured result |
| **5** | Refinement | Test set and iteration for accuracy |

**Starting point** for “ask questions and get structured result” is achieved at the end of **Phase 3**, with SQLite in use from **Phase 1** and ingest writing to DB in **Phase 2**.

---

## References

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — Vision, goals, and high-level flow.  
- [CURRENT_BUILD.md](CURRENT_BUILD.md) — What exists today (SQLite, structured response, images, catalog setup).  
- [PDF_PATH_UPDATES.md](PDF_PATH_UPDATES.md) — Source paths and PyMuPDF usage.  
- [README-GPU.md](README-GPU.md) — GPU and Hugging Face model setup.

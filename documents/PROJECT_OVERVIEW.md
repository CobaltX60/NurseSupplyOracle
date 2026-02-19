# Instrument Oracle — Project Overview

## Purpose

Instrument Oracle is an application that **data mines PDF and other source files** for information related to **instrumentation for surgical procedures**. The system builds a searchable library from instrument catalogs and related documents so users can quickly recall accurate information via natural-language questions, with optional access to visual elements from the source PDFs.

## Goals

1. **Data mining** — Ingest PDF catalogs and other source files that contain:
   - Instrument product names  
   - Instrument descriptions  
   - Part numbers  
   - Product characteristics (materials, dimensions, use cases, etc.)  
   - Images and diagrams  

2. **Searchable library** — Chunk and index all extracted information so it can be:
   - Retrieved quickly via semantic search (e.g. FAISS + embeddings)  
   - Used as context for an LLM to answer questions accurately  
   - Refined iteratively until recall from the PDFs is reliable  

3. **Visual access** — Expose visual elements from PDF catalogs (product images, diagrams) so users can see what they are asking about when relevant.

4. **Local-first** — Run on local hardware using a local LLM (**Qwen2.5-7B-Instruct**, 8-bit) so that:
   - Data stays on-premises  
   - No dependency on external LLM APIs for core Q&A  
   - GPU-optimized build with Hugging Face + bitsandbytes  

5. **Structured results** — **Implemented:** API returns structured responses (answer, sources, product_cards, image_refs); UI shows product information cards when part numbers match.

6. **Durable storage** — **Implemented:** **SQLite** holds:
   - Chunk text and metadata  
   - Source document and page references  
   - Product/instrument entities (part numbers, names, attributes)  
   - References to extracted images  
   - Query/response history or cache if desired  

## Source Data (Inputs)

- **Primary:** PDF documents (instrument catalogs, procedure guides, product sheets) containing:
  - Product names, descriptions, part numbers  
  - Specifications and characteristics  
  - Embedded images and diagrams  
- **Other:** Any additional source files (e.g. Excel, CSV) that describe instruments; these can be ingested and chunked similarly.

## High-Level Flow

1. **Ingest** — Read PDFs (and other sources), extract text and metadata, optionally extract images.  
2. **Chunk** — Split content into meaningful chunks (e.g. by section, product, or fixed token size) with source and page (and image) references.  
3. **Store** — Persist chunks and metadata in **SQLite**; maintain a vector index (e.g. FAISS) for semantic search, built from or synced with the DB.  
4. **Query** — User asks a question in natural language; system retrieves relevant chunks from the index, optionally from SQLite.  
5. **Answer** — **Qwen2.5-7B-Instruct** (running locally, 8-bit) generates an answer using retrieved context; output is shaped into a **structured result** (answer text, sources, product_cards, image_refs).  
6. **Refine** — Evaluate recall and accuracy; tune chunking, prompts, and retrieval (see IMPLEMENTATION_PLAN Phase 5).

## Success Criteria (Initial)

- PDF and other source files are ingested and chunked into a library. ✅  
- Users can ask questions and receive answers grounded in the ingested data. ✅  
- Responses are **structured** (JSON with answer, sources, product_cards, image_refs). ✅  
- Long-term data lives in **SQLite**; vector search (FAISS) is used for retrieval. ✅  
- Qwen2.5-7B runs locally (8-bit) and is verified working. ✅  
- The pipeline can be refined to improve accuracy of recall from the PDFs. (Ongoing.)

## Out of Scope (For Now)

- Real-time sync with live catalogs; focus is on batch ingest of provided files.  
- Multi-user auth or complex deployment; local/single-machine use is the starting point.  
- Vision/OCR: LLM is text-only; images are stored and displayed but not sent to the model.

---

*This overview should be used to align development and to give LLMs and developers clear context when working on Instrument Oracle.*

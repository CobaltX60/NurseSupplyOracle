# Instrument Oracle — Documentation

This folder contains markdown documentation for **Instrument Oracle**. These documents are used to:

- **Enhance the solution** — Architecture, performance, and integration details for developers
- **Guide the LLM** — Structured context and instructions that can be provided to AI assistants when working on this project

## Contents

| Document | Description |
|----------|-------------|
| **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** | **Vision and goals:** data mining PDF catalogs for surgical instrumentation, searchable library, Qwen2.5-7B local, SQLite, structured results |
| **[CURRENT_BUILD.md](CURRENT_BUILD.md)** | **Current build:** what exists today (Flask, SQLite, FAISS, rebuild.py, Qwen2.5-7B, structured response, product cards, catalog setup) |
| **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** | **Phased plan:** status of phases 0–4 (done); Phase 5 refinement optional |
| [PDF_PATH_UPDATES.md](PDF_PATH_UPDATES.md) | PDF paths, `source_files/` layout, and PyMuPDF migration |
| [PERFORMANCE_OPTIMIZATIONS.md](PERFORMANCE_OPTIMIZATIONS.md) | Performance tuning, GPU usage, caching, and server optimization |
| [PRODUCT_INTEGRATION.md](PRODUCT_INTEGRATION.md) | Product/Excel data integration and combined knowledge base |
| [README-GPU.md](README-GPU.md) | GPU setup, CUDA, and Hugging Face model configuration |
| [SOURCE_AND_REBUILD.md](SOURCE_AND_REBUILD.md) | Source files in `scripts/source_files/`; rebuild only when prompted via `scripts/rebuild.py` |
| [CHUNK_SIZE_EVALUATION.md](CHUNK_SIZE_EVALUATION.md) | Pros/cons of more smaller chunks vs fewer larger chunks; recommendation for very specific data |
| [IMAGE_CONSUMPTION_AND_MANAGEMENT.md](IMAGE_CONSUMPTION_AND_MANAGEMENT.md) | How to extract, store, and serve images from PDFs; SQLite and API design |
| [CATALOG_DATA_MODEL_AND_ASSOCIATION_PLAN.md](CATALOG_DATA_MODEL_AND_ASSOCIATION_PLAN.md) | Data model (Product, images), per-catalog parsing rules, user association workflow, foreign language, phased plan |
| [EXTRACTION_APPROACH_EVALUATION.md](EXTRACTION_APPROACH_EVALUATION.md) | Evaluation of LLM vs spatial extraction; current design: LLM-only extraction + proximity-based image association |
| [TESTING_NEW_EXTRACTION_ARCHITECTURE.md](TESTING_NEW_EXTRACTION_ARCHITECTURE.md) | How to test the new pipeline: one-page API test, test script, UI, and validation checklist |

## Usage

- Keep project-specific instructions and architecture notes here.
- Add new docs as the solution grows (e.g. deployment, prompts, data schemas).
- Reference this folder when giving context to an LLM working on Instrument Oracle.

The main project overview and quick start remain in the repository root [README.md](../README.md).

# Knowledge Base and Gemini: End-to-End Review

This document walks from **rebuilding the knowledge base** through **what the Gemini LLM receives and how it should respond**, and notes where the app was updated from the old local-LLM approach.

---

## 1. Rebuilding the Knowledge Base (for the LLM)

The LLM (Gemini) never sees raw PDFs. It only sees **text and structure** produced by the rebuild pipeline.

### 1.1 Source and run

- **Source location:** `scripts/source_files/` (PDFs only for rebuild).
- **Command:** From project root: `python scripts/rebuild.py`.
- **Outputs:** `data/instrument_oracle.db` (SQLite) and `data/faiss_index.idx` (vector index). Optional: `data/images/` for extracted images.

### 1.2 What rebuild produces (what the LLM ultimately uses)

| Output | Purpose for the LLM |
|--------|---------------------|
| **Chunks** | Text is split into overlapping chunks (e.g. 200 words, 50 overlap). Each chunk is stored in `chunks` with `source_id`, `page_number`, `text`, `type`. These are **the only text the chat LLM sees**—retrieved by similarity to the user question. |
| **Embeddings + FAISS** | Same embedding model as at runtime (`all-MiniLM-L6-v2`). Each chunk is embedded; vectors are stored in FAISS. At query time, the question is embedded and the top‑k similar chunks are fetched → that text becomes the **CONTEXT** sent to Gemini. |
| **Images** | Stored and served by the app; the **chat** LLM does not receive image pixels. Image URLs are attached to answers for the UI. (Future: vision could send images to Gemini; see PAGE_IMAGES_AND_VISION.md.) |
| **Products / catalog_config / catalog_samples** | Used for product cards, field-guide instructions, and product–image links. Samples and config are turned into a short **field_guide** string appended to the instruction so Gemini knows how part numbers, product names, and descriptions look in this catalog. |

So: **what the Gemini chat model “knows”** is exactly (1) the **retrieved chunk text** (plus any product context and image-association lines we inject), and (2) the **instructions and field_guide** we send in the prompt.

### 1.3 Chunking parameters (rebuild)

- **CHUNK_SIZE** (e.g. 200 words) and **CHUNK_OVERLAP** (e.g. 50) in `scripts/rebuild.py` control granularity. Smaller chunks → more precise retrieval but more chunks; the chat server then takes the top few (e.g. 5) and concatenates them into CONTEXT.
- Rebuild uses the **same embedding model** as the chat server so that retrieval at runtime matches the index.

---

## 2. What the Gemini Chat LLM Sees (per question)

When a user asks a question in the UI:

1. **Retrieval (chat server)**  
   - Question (and optional search hint from catalog samples) is embedded.  
   - FAISS returns top **k** (e.g. 10) chunk indices; we keep the first **max_context_chunks** (e.g. 5) for the answer.  
   - If the question looks like it contains a part number, we also run **keyword search** and prepend matching chunks so the model is more likely to see the right product.

2. **Context assembly**  
   - **CONTEXT** = “RELEVANT EXCERPTS FROM KNOWLEDGE BASE:” + the concatenated text of those chunks (each chunk truncated to 1200 chars).  
   - Optionally we prepend:  
     - **product_context**: DB product row when the question mentions a known part number.  
     - **product_image_context**: line like “The following image(s) are linked to product(s) …” when we have product–image associations.

3. **Field guide (optional)**  
   - Built from **catalog_samples** and **catalog_config** for the sources of the retrieved chunks.  
   - Tells Gemini how part numbers, product names, descriptions, etc. look in this catalog (examples and rules).  
   - Appended to the **instruction** (capped so the prompt doesn’t explode).

4. **Instruction**  
   - **If the question looks like a part number:**  
     “You are answering from a catalog knowledge base. Find that part number in the CONTEXT below and state the exact information given (product name, description, specifications). Copy relevant lines. Do NOT say the information is not in the context if you can see the part number or product name. If the part number truly does not appear, only then say it was not found.”  
   - **Otherwise:**  
     “Using ONLY the context below from the instrument/product knowledge base, answer the question. Include part numbers, product names, and specifications when they appear in the context. Do not say information is unavailable if it is present in the context below.”

5. **Final prompt to Gemini**  
   - Single user turn: `instruction` (+ optional `field_guide` snippet) + `CONTEXT` (trimmed to ~14k chars) + `QUESTION`.  
   - No chat history is sent; each request is stateless.

So the **Gemini model should**:

- Answer **only from the provided CONTEXT** (and any injected product/image lines).  
- Prefer **exact quotes/specs** from the context when available.  
- For part-number questions: say “not found” only when the part truly does not appear in CONTEXT.  
- Use the field_guide to interpret catalog-specific formats (part numbers, names, descriptions).

---

## 3. Product Extraction (Build Product Listing)

A **separate** use of Gemini is **product extraction** per page:

- Input: **Page text** (from chunks or assembled page text) + **field_guide**.  
- Output: **JSON array** of product objects (manufacturer_part_number, product_name, description, secondary_description, category).  
- Used by “Build product listing” in catalog setup to populate the `products` table.  
- Same Gemini model and API; different prompt (extraction instructions + “Output ONLY a JSON array”).

This is independent of the chat flow; the only link is that both use the same knowledge base (sources, chunks, samples, config) and the same Gemini model.

---

## 4. What Changed From the Local-LLM Approach

| Area | Old (local LLM) | Current (Gemini) |
|------|------------------|------------------|
| **Model loading** | Qwen/Mistral loaded at startup (4-bit, GPU). | No local LLM; Gemini API client only. |
| **Prompt format** | Chat templates ([INST]/[/INST], ChatML) and tokenizer-based truncation to fit context window. | Plain instruction + CONTEXT + QUESTION; context trimmed by character count (~14k). |
| **Response cleaning** | `clean_response()` stripped Mistral/Qwen artifacts ([INST], <\|im_end\|>, etc.). | Same function kept for robustness; Gemini usually returns plain text, so those regexes rarely match but do no harm. |
| **Context length** | Token-based budget (e.g. 8192) and reserve for instruction/response; truncation via tokenizer. | Character-based trim (e.g. 14000 chars for context). No tokenizer. |
| **Config** | Optional HF_TOKEN for model download. | **GEMINI_API_KEY** and **GEMINI_MODEL** in `.env`; required for chat. |
| **Rebuild** | Same chunks/FAISS; no change. Cache cleared so old Q&A not reused. | Same; rebuild still clears response cache. No LLM-specific rebuild steps. |

The **knowledge base pipeline** (rebuild → chunks, FAISS, samples, products, images) is **unchanged**. Only the **consumer** of the retrieved context switched from a local model to Gemini.

---

## 5. Remnants to Keep vs Clean Up

- **clean_response()**  
  - Still removes [INST]/[/INST] and ChatML tokens.  
  - **Keep:** Harmless for Gemini; useful if we ever add another backend or reuse in a tool that might see such artifacts.

- **Comments/docstrings**  
  - Some comments still say “local LLM” or “4-bit” or “Qwen”.  
  - **Clean:** Update to “Gemini” where it describes current behavior.

- **download_model.py**  
  - Still mentions Qwen and 8-bit download.  
  - **Clean:** Update to say the app uses Gemini for the LLM and only embedding model is downloaded (or remove/redirect to README).

- **Footer / UI text**  
  - e.g. “Powered by … local LLM” or “Processing with GPU”.  
  - **Clean:** Say “Gemini” (and optionally “embeddings run locally”) so it’s accurate.

- **Response cache**  
  - Still keyed by question hash and content signature; **unchanged and correct** for Gemini.

---

## 6. Summary

- **Rebuild** defines what the LLM “can know”: chunked text, embeddings, and optional product/sample/config data.  
- **Chat server** retrieves chunks, builds CONTEXT + instruction + field_guide, and sends one user turn to **Gemini**.  
- **Gemini** should answer only from CONTEXT, cite specs/part numbers accurately, and use the field_guide to interpret catalog formatting.  
- **Product extraction** is a separate Gemini call for building the product table; same model, different prompt.  
- **Local-LLM-specific logic** (tokenizer, chat templates, token limits) has been removed or bypassed; remaining references are mostly comments and helper text and can be updated for clarity.

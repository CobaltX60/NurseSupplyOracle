# How Retrieval and Sources Work

This document explains how chat questions are turned into answers and how the "sources" you see relate to the response.

---

## 1. How results are found

1. **Query**  
   Your question (e.g. "Penfield dissector No. 1") is optionally combined with a short **search hint** built from your catalog samples (part numbers, product names, categories, etc.) so retrieval is biased toward similar catalog content.

2. **Embedding**  
   The combined string is turned into a **vector** (embedding) using the same sentence-transformers model that was used when the PDFs were chunked and indexed.

3. **FAISS search**  
   That vector is compared to every chunk in the index. FAISS returns the **k** chunks whose vectors are **closest** to the query vector (nearest-neighbor search).  
   - **Order** = by similarity: index 0 is the most similar chunk, then 1, 2, …  
   - **No keyword match**: retrieval is purely **semantic** (meaning). A chunk that contains "Penfield dissector No. 1" might rank 4th if other chunks are closer in meaning (e.g. other dissectors, "No. 1" in another context).

4. **Why you see a fixed number of sources**  
   The code requests **k = 10** nearest chunks, then uses the **top 5** in the context (and only those 5 are shown as sources). So you see at most 5 sources, in relevance order. If the index has fewer chunks, you see fewer.

5. **Why the “right” page can be 4th**  
   The chunk that actually contains "Penfield dissector No. 1" is only ranked higher if its **embedding** is among the top-k closest. Other chunks (e.g. similar product names, same category, other “No. 1” items) can be closer in vector space, so the exact-match chunk can appear at position 4 (or not at all if k is too small).

---

## 2. How results are organized and returned

- **Chunks** come back from FAISS in **relevance order** (most similar first).
- The **context** sent to the LLM is built from the **first N** of those chunks (N = 5). Only those N chunks are used to generate the answer.
- **Sources** are the “source name (Page X)” strings for those same chunks. They are now returned **in the same order** as the chunks used in the context, so the first listed source is the most relevant chunk, and so on.
- Only chunks that are **actually in the context** are listed as sources; the list is not padded to k.

So: **displayed sources = chunks that were used for the answer, in relevance order.**

---

## 3. How the displayed sources match the answer

- The **answer** is generated from the **context** only (the first N chunks).
- The **sources** shown in the UI are exactly the citations for those N chunks, in the same order.
- So every listed source corresponds to a chunk that the model had when it wrote the answer. There is no 6th source that wasn’t in the context.

Improvements made in code:

- Sources are kept in **retrieval order** (most relevant first).
- Only chunks that are included in the context are returned as sources (no extra citations).
- The code uses **k=10** and **5 chunks in context** so the answer stays focused on the most relevant excerpts.

---

## 4. Why recall can feel off

- **Semantic vs. exact**: Search is by meaning, not by “contains this exact phrase.” So the best-matching chunk by embedding might not be the one with the exact product name.
- **Chunking**: Each page is split into overlapping chunks (e.g. 200 words, 50 overlap). One page can produce several chunks; the one with “Penfield dissector No. 1” might be one of many from that page.
- **k and N**: If k or N is small, the relevant chunk might not be in the top N, so it won’t be in the context or in the sources.

Using a moderate N (e.g. 5 chunks) keeps the context focused; increasing N can add noise and reduce accuracy.

---

## 5. When to rebuild the knowledge base

**Rebuild** (`python scripts/rebuild.py`) re-extracts text and images from the PDFs in `scripts/source_files/`, re-chunks, and rebuilds the FAISS index. It **does not** change your products, samples, or catalog config.

- **Do rebuild** when:
  - You added, replaced, or updated PDFs in `scripts/source_files/`.
  - You suspect a bad or out-of-date index (e.g. you deleted or moved files and the index still references old content).
- **Rebuild alone usually does not fix “answers got worse”** if the PDFs and the last build were already correct. Accuracy is driven by retrieval (k, number of chunks in context), the search hint, and the prompt—not by re-running the same rebuild.

If chat became **more inaccurate** after no PDF changes:
- Try **restarting the chat server** (to clear any in-memory state).
- The code uses **5 chunks in context** (reduced from 8) to keep answers focused; if it’s still off, we can tune retrieval or the search hint further.

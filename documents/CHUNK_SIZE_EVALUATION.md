# Chunk Size: More (Smaller) vs Fewer (Larger) Chunks

For Instrument Oracle you want **very specific data** (part numbers, product names, specs) and **rebuilds are relatively static**. Below is a direct comparison and recommendation.

---

## More chunks (smaller chunk size)

**Pros**

- **Better precision** — Retrieval tends to return the exact sentence or product block that matches the question instead of a long page. Good for “what’s part number X?” or “which instrument for procedure Y?”
- **Less noise in context** — Each chunk sent to the LLM is more focused, so the model sees less irrelevant text and can answer from the right detail.
- **Clearer attribution** — You can point to “Page 12, product block 2” rather than “Page 12” with a full page of content.
- **Fits “very specific” use case** — Part numbers and product names are easier to match when they sit in a small chunk; the chunk embedding is more aligned with that specific fact.
- **Rebuild cost is one-time** — With static rebuilds, the extra embedding work for more chunks is acceptable.

**Cons**

- **Possible loss of context** — A tiny chunk (e.g. “Part #123”) might lack product name or description; the LLM may need the next chunk too. Mitigate with modest overlap and/or retrieval that returns several chunks.
- **Slightly larger index and DB** — More rows and vectors; at the scale you’re at (hundreds to low thousands), this is negligible.
- **Overlap can duplicate text** — If overlap is large relative to chunk size, you repeat content; keep overlap modest (e.g. 50–150 tokens).

---

## Fewer chunks (larger chunk size)

**Pros**

- **More context per chunk** — The LLM may see a full product block or section, which can help coherence.
- **Fewer vectors** — Slightly smaller FAISS index and fewer DB rows (minor at your scale).
- **Less fragmentation** — One product description plus specs and caption can stay in one chunk.

**Cons**

- **Worse for specific lookup** — A query about one part number may pull a long chunk where that part is one line; the rest is noise and uses up context.
- **Diluted embeddings** — The vector for a long chunk averages many topics, so it may rank lower for a narrow question.
- **Wasted context window** — You send a lot of irrelevant text to the LLM, leaving less room for other relevant chunks.

---

## Recommendation for Instrument Oracle

**Prefer more, smaller chunks** for your goals:

1. You want **very specific** data (part numbers, names, specs) — smaller chunks improve retrieval precision and give the model focused context.
2. Rebuild is **relatively static** — the cost of more chunks (rebuild time, index size) is acceptable.
3. Catalog pages often have **multiple products** — splitting into smaller chunks (e.g. by token size or by section) gives you more targeted hits per page.

**Practical settings (in `scripts/rebuild.py`):**

| Strategy        | Chunk size (tokens) | Overlap | Effect |
|----------------|---------------------|--------|--------|
| Current        | 1200                | 200    | ~1 chunk per page when content is short; good baseline. |
| **Recommended**| **400–600**         | **75–100** | More chunks per page; better for part-number and product-specific questions. |
| Aggressive     | 200–300             | 50      | Very fine; best for “one product per chunk” if you add section splitting later. |

Start with **chunk size 500–600 and overlap 100**. Run a rebuild and try questions like “part number for X” and “instruments for procedure Y.” If answers are still vague or pull whole pages, reduce to **400** (or add splitting by headings/product blocks later). If you lose too much context, increase to **600–700**.

---

## Summary

| Goal                         | Prefer          |
|-----------------------------|-----------------|
| Very specific data (parts, names) | **More, smaller chunks** |
| Static rebuild              | **More chunks is fine**  |
| Clear source (page + block) | **More, smaller chunks** |
| Maximum context per chunk   | Fewer, larger chunks     |

**Bottom line:** For instrument catalogs and very specific recall, use **smaller chunk size (400–600 tokens)** and **modest overlap (75–100)** so you get more chunks and more precise retrieval. Adjust overlap down if you see too much duplication in the context sent to the LLM.

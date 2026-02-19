# Data Ingestion Options

This document describes how Instrument Oracle gets data from PDFs and how to improve it when the reader does not seem to parse everything or when part-number lookups fail.

---

## 1. Current pipeline (rebuild)

- **Text**: PyMuPDF `get_text("text")` per page; if a page returns no text, a block-based fallback (`get_text("dict")`) is used so sparse or layout-heavy pages (e.g. part numbers only) are not dropped.
- **No page skip by length**: Pages are only skipped when they have *no* extracted text (previously pages with &lt; 50 characters were skipped; that was removed).
- **Chunking**: Text is split into overlapping word chunks (200 words, 50 overlap), stored in SQLite, and embedded for FAISS.
- **Images**: Embedded images are extracted and stored under `data/images/`.

If part numbers or product names are missing from answers, the cause can be:

1. **Extraction**: The PDF has no text layer (scanned/image-only), or the layout is such that PyMuPDF does not output that text.
2. **Retrieval**: The text is in the index but semantic search does not rank the right chunk highly (e.g. query “information on NL3006” does not surface the chunk that contains “NL3006”).

---

## 2. Hybrid retrieval (part-number and product boost)

To make part-number queries reliable even when vector search misses them:

- **Keyword boost**: If the question contains something that looks like a part number (e.g. `NL3006`, `NL3720`), the server does a **keyword search** on the chunks table for that string and **prepends** matching chunks to the context (before the top vector results). So “information on NL3006” will pull in any chunk that contains “NL3006”.
- **Product table**: If the question mentions a part number that exists in the `products` table (from “Build product listing” or manual entry), that product’s name, description, and category are injected into the context so the model can answer even when no chunk mentions it.

So:

- **“Malis Scissors”** → vector search can return the chunk with NL3006; if the answer includes the part number, that’s normal.
- **“Information on NL3006”** → keyword search finds chunks containing “NL3006” and adds them to context; if that part is in `products`, that row is also added. The answer should now be able to describe NL3006.

No rebuild is required for this; restart the chat server to use the new retrieval logic.

---

## 3. Extract all text from a PDF (full dump)

To see **every piece of text** PyMuPDF can extract from a PDF (and compare with what you see on screen), use the full extraction script. It writes one file per page plus a summary so you can tell if the problem is missing data or chunking/retrieval.

```bash
# From project root. Use your PDF name (no .pdf) or full path.
python scripts/extract_all_pdf_text.py YourCatalog
python scripts/extract_all_pdf_text.py YourCatalog --pages 1-5,20   # only those pages
python scripts/extract_all_pdf_text.py YourCatalog --full-dump      # also full_dump.txt for grep
python scripts/extract_all_pdf_text.py YourCatalog --words 20       # word-level dump for page 20
```

**Output:** `data/pdf_text_export/<source_name>/`

- **summary.txt** — Per-page character counts for `get_text("text")` vs `get_text("dict")`. If dict has more than text on a page, the plain-text mode may be dropping content.
- **page_0001.txt, page_0002.txt, ...** — Full text for each page from dict extraction (every block/line/span in order). This is the most complete extraction PyMuPDF provides.
- **full_dump.txt** (with `--full-dump`) — All pages concatenated; search for part numbers (e.g. NL3006) in one file.
- **page_NNNN_words.txt** (with `--words N`) — Word-level list with coordinates for that page.

Compare the exported text to the PDF: if part numbers or product names are missing from the export, the issue is extraction (PyMuPDF or the PDF’s text layer). If they appear in the export but not in chat answers, the issue is chunking or retrieval.

---

## 4. Verify what is actually extracted (single page)

Before changing the ingestion pipeline, you can also spot-check one page with:

```bash
python scripts/inspect_page_text.py YourCatalog 20
```

This prints the **raw text** for page 20 (same logic as rebuild). Check if the part number and product name appear:

- If **yes** → the problem is retrieval or context length; hybrid retrieval (above) should help.
- If **no** → the problem is extraction; run the full export above and consider OCR or a different parsing strategy (below).

---

## 5. Option A: OCR for image-only or image-heavy PDFs

If the PDF is scanned or the text you care about is inside images/figures, PyMuPDF’s text layer will be empty or incomplete. In that case you need OCR.

- **Scripts**: The repo has OCR-related scripts (e.g. `prepare_ocr.py`, `test_pdf_extraction.py`). These typically render each page to an image and run Tesseract (or similar) to get text.
- **Integration**: To use OCR in the main pipeline you would either:
  - Add an OCR path in `rebuild.py` (e.g. for pages that yield very little text, run OCR and use that text), or
  - Run a separate OCR pipeline that writes text/chunks into the same SQLite schema and then run the usual embedding + FAISS step.
- **Cost**: OCR is slower and needs `pytesseract` (and Tesseract installed). Use it only for PDFs that really have no or poor text layer.

---

## 6. Option B: Structured extraction into the products table

Catalog data (part number, product name, description) can be stored in the **products** table so that:

- Part-number lookups can use the database (as in the hybrid retrieval above).
- The UI can show and edit product records; “Build product listing” already uses an LLM to extract products per page and insert them into `products`.

Ways to improve “foundation” data:

- **Run “Build product listing”** on your catalog(s) so that as many pages as possible have at least one product row with `manufacturer_part_number`, `product_name`, `description`. Then “information on NL3006” can be answered from the products table even when no chunk contains NL3006.
- **Refine catalog samples and instructions** so the LLM associates the right text to part number vs. product name vs. description. Better samples → better extraction.
- **Manual correction**: Use the catalog setup UI to assign part numbers to images and correct product fields; that both fixes data and adds samples for future runs.

This does not replace chunk ingestion; it adds a second, structured layer that retrieval (and the new product-context injection) can use.

---

## 7. Option C: Different chunking or indexing

- **Smaller chunks / more overlap**: In `rebuild.py`, `CHUNK_SIZE = 200` and `CHUNK_OVERLAP = 50` mean part number and product name often share a chunk. If you go smaller (e.g. 100/25), you get more chunks and more precise retrieval at the cost of more context and index size.
- **Dual indexing**: Keep the current FAISS index and add a **keyword index** (e.g. part number → chunk ids). The chat server already does a form of this by querying chunks by substring when a part-number-like token is detected; you could extend that with a dedicated table or search index if needed.

---

## 8. Recommended order of actions

1. **Run the full text export** (`extract_all_pdf_text.py YourCatalog --full-dump`) and open `data/pdf_text_export/<source>/summary.txt` and a few `page_*.txt` files. Search for a known part number (e.g. NL3006). If it’s missing from the export, the issue is extraction; if it’s present, the issue is chunking or retrieval. Optionally use **`inspect_page_text.py YourCatalog 20`** for a quick single-page check.
2. **Rebuild** with the current pipeline (no 50-char skip, block fallback): `python scripts/rebuild.py`. Restart the chat server.
3. **Rely on hybrid retrieval**: Ask “information on NL3006” again; the server will keyword-match “NL3006” and, if you have a product row, inject it into context.
4. If extraction is still missing text (step 1 shows it’s not there): consider **OCR** for that PDF or those pages.
5. If you want more robust part-number answers regardless of chunks: **run “Build product listing”** and optionally refine samples so the **products** table is populated; then product-context injection will cover known part numbers even when no chunk is found.

---

## Summary

| Problem | What to do |
|--------|------------|
| “Malis Scissors” returns NL3006 but “information on NL3006” finds nothing | Use **hybrid retrieval** (keyword + product context). Restart chat server. |
| Part number not in extracted text | Run **inspect_page_text.py** to confirm; if missing, add **OCR** or fix PDF (e.g. use a text-layer version). |
| Want answers to always use structured product data | Populate **products** via “Build product listing” and samples; hybrid retrieval injects product rows when the question mentions a known part number. |
| PDF reader clearly not parsing all data | Verify with **inspect_page_text.py**; then improve extraction (block fallback already in place, or OCR), and use **hybrid retrieval** so whatever *is* ingested is findable by part number. |

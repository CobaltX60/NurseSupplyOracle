# Page Images, Slicing, and LLM Image Recognition

**Revisit later:** Smaller images / slicing and LLM image recognition are deferred. Proceeding with current behavior (extracted images only; text-only LLM).

---

## Current state

- **Rebuild** produces **no full-page render**. It extracts only: XObject refs (`get_images(full=True)`), **inline** (BI/ID/EI via `get_text("dict", TEXT_PRESERVE_IMAGES)`), **orphan xrefs** (Form XObjects), and **small vector regions** (xRef-style icons via `cluster_drawings` / `get_drawings` + clip render). See [NEXT_STEPS_SECONDARY_IMAGES.md](NEXT_STEPS_SECONDARY_IMAGES.md). So each page has only these embedded/vector-region images.
- **Chat/LLM**: The model is **text-only** (Qwen2.5-7B-Instruct). It receives:
  - Text context (FAISS chunks, product rows, product–image links as text).
  - **No image pixels** are sent to the model. The API returns `image_refs` and `product_cards` (with image URLs) so the **UI** can show product info cards or images; the LLM never “sees” them.
- There is **no image slicing** (beyond vector-region clip renders), **no OCR on images**, and **no vision model** in the pipeline today.

So you have only extracted/vector-region images; the LLM does not interpret page content from those images.

---

## 1. Getting smaller images or slicing the full-page image

### A. Clip-render at rebuild (recommended if you know regions)

- In `rebuild.py`, call **`page.get_pixmap(clip=rect)`** for specific rectangles (e.g. “left column”, “product block”).
- Each clip becomes a separate image (e.g. `page_21_1.png`, `page_21_2.png`) stored and linked like today.
- **Requires** defining regions: fixed grid (e.g. 2×2), or layout rules (e.g. from chunk/product bboxes), or manual coordinates per page type.

### B. Post-process: slice a rendered full-page PNG (if you add full-page render back)

- If you re-enable a full-page render in rebuild, you could run a script that:
  - Reads each full-page image from `data/images/<source_id>/page_<n>_<last>.png`.
  - Crops it into tiles (e.g. 2×2 or 3×2 grid) or into regions from a config file.
  - Writes new files and inserts new rows into images (or a separate slices table).
- The app can then show these tiles as smaller images for that page.

### C. Current: extracted images only (no full-page)

- The build **does not** produce a full-page render. Only embedded images (direct + inline + orphans) and small vector regions are stored. Vector-only content (e.g. large line drawings) does not appear as images unless you add clip-renders (Option A).

**Practical next step for smaller images:**  
- If you want **automatic regions**: add a **fixed grid** (e.g. 2×2) in rebuild: for each page, render four clips and append them as four extra images.  


---

## 2. Letting the LLM interpret more page content via images (image recognition)

Today the LLM only sees **text**. To use the scans so the model can “interpret” page content, you need at least one of the following.

### Option 1: Vision-capable LLM (multimodal)

- Use a model that accepts **image + text** (e.g. OpenAI GPT-4V, Anthropic Claude with images, or open-source vision-language models).
- **Flow**: For each user question, (1) retrieve relevant chunks and **relevant page images** (e.g. same source_id/page as the chunks), (2) send the question + text context + **image(s)** to the vision API, (3) return the answer and existing `image_refs`.
- **Pros**: Model can describe or use what it sees (tables, diagrams, line drawings).  
- **Cons**: Extra cost (vision APIs), or local GPU for open-source vision models; you must decide which images to send (e.g. extracted images for cited pages).

### Option 2: OCR on page images → text → current LLM

- Run **OCR** (e.g. Tesseract, or a cloud OCR API) on page images (e.g. clip-rendered regions, or a full-page render if re-added).
- Store the OCR text (e.g. in a new column on `chunks`, or a separate “page_ocr” table keyed by source_id + page_number).
- At chat time, **add this OCR text to the context** for the retrieved pages, then call your **existing text-only** `generate_response_optimized(question, context, ...)`.
- **Pros**: No vision model; reuses current stack; good for “text on the page” that didn’t make it into the PDF text layer.  
- **Cons**: Doesn’t “understand” diagrams or line drawings, only text; OCR quality and layout matter.

### Option 3: Image captioning / description → text → current LLM

- Use a **vision model** (or API) only to produce **one short description per page image** (or per slice) at rebuild or on first use.
- Store the description as text (e.g. in chunk metadata or a dedicated table).
- At chat time, **append these descriptions to context** and keep using the text-only LLM.
- **Pros**: Model gets a summary of what’s in the image without sending pixels at query time.  
- **Cons**: One-off caption quality; less detail than sending the image to a vision model at query time.

---

## Summary

| Goal | What you have now | Possible next steps |
|------|-------------------|---------------------|
| **Smaller images** | Extracted images only (no full-page) | Clip-render regions in rebuild (grid or layout) if you want more coverage. |
| **Slice full-page** | No full-page image | Add a full-page render in rebuild and/or clip-renders, then optionally slice into tiles. |
| **LLM interprets page content** | No; LLM is text-only, no image input | (1) Vision LLM: send image(s) + text to a vision API or local vision model; (2) OCR on page images and add OCR text to context; (3) Pre-caption images and add captions to context. |

If you say which direction you prefer (e.g. “2×2 grid slices in rebuild” vs “OCR on full-page and add to context”), the next step can be outlined in more concrete code/API form.

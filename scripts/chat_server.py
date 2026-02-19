#!/usr/bin/env python3
"""
Optimized Hugging Face GPU-accelerated chat server for Instrument Oracle
Features: Model preloading, in-process inference, and aggressive optimization
"""

import json
import os
import sqlite3
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import pickle
import hashlib
from pathlib import Path
import threading
import time
import torch
import psutil
from datetime import datetime
import sys
import re
import subprocess
import traceback

try:
    import fitz  # PyMuPDF for text spans with bbox (image association by proximity to catalog numbers)
except ImportError:
    fitz = None

# Data paths (SQLite + FAISS from rebuild)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "instrument_oracle.db")
FAISS_PATH = os.path.join(DATA_DIR, "faiss_index.idx")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Load application-level config from .env in the project root.
# This sets GEMINI_API_KEY, etc., so you don't need to set them at the system level.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))  # no-op if file doesn't exist
except ImportError:
    pass  # python-dotenv optional; env vars can still be set by the shell

# Set LOG_PROMPT=1 or LOG_PROMPT=true in .env or environment to print the full prompt (Flask console).
LOG_PROMPT = os.environ.get("LOG_PROMPT", "").strip().lower() in ("1", "true", "yes")
# Set RETURN_CHAT_ERROR=1 to include the last Gemini/chat exception in the API response (for debugging).
RETURN_CHAT_ERROR = os.environ.get("RETURN_CHAT_ERROR", "").strip().lower() in ("1", "true", "yes")
# Set LOG_PRODUCT_EXTRACTION_RAW=1 to print raw Gemini output for product extraction (for debugging empty extractions).
LOG_PRODUCT_EXTRACTION_RAW = os.environ.get("LOG_PRODUCT_EXTRACTION_RAW", "").strip().lower() in ("1", "true", "yes")
# Quiet image logs: set to 0 or false to log every GET /api/image/ 200 (noisy). Default True = suppress those lines.
QUIET_IMAGE_LOGS = os.environ.get("QUIET_IMAGE_LOGS", "1").strip().lower() not in ("0", "false", "no")

# Patch werkzeug request logging before Flask imports it (so GET /api/image/ 200 lines are suppressed).
if QUIET_IMAGE_LOGS:
    try:
        import werkzeug._internal as _wk_internal
        _orig_log = _wk_internal._log
        def _quiet_image_log(type: str, message: str, *args, **kwargs):
            try:
                if args:
                    formatted = message % args
                else:
                    formatted = message
                if "/api/image/" in formatted and "200" in formatted:
                    return
            except (TypeError, ValueError):
                pass
            _orig_log(type, message, *args, **kwargs)
        _wk_internal._log = _quiet_image_log
    except Exception:
        pass  # ignore if werkzeug structure differs

# Google Gemini API: required for chat and product extraction (set in .env).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

from catalog_profile import resolve_profile_for_source, get_product_cells_grid
from catalog_analysis import (
    load_analysis_profile_for_source,
    get_analysis_profile_status,
    run_catalog_analysis,
    load_default_profile,
    should_skip_page_for_products,
)
app = Flask(__name__)
CORS(app)

# Global variables
_model_embed = None
_chunks_data = None
_chunk_sources = None
_faiss_index = None
_content_signature = None  # Hash of chunk count + sources; cache only valid when this matches
_response_cache = {}
_models_loaded = False
_loading_lock = threading.Lock()
_device = None
_genai_client = None  # Google Gemini 2.0 Flash API client
_last_chat_error = None  # Last exception message from generate_response_optimized (for RETURN_CHAT_ERROR debug)
_performance_stats = {
    'total_requests': 0,
    'cached_requests': 0,
    'gpu_requests': 0,
    'avg_response_time': 0,
    'start_time': datetime.now()
}

def get_gpu_memory_info():
    """Get current GPU memory usage"""
    if not torch.cuda.is_available():
        return None
    
    try:
        allocated = torch.cuda.memory_allocated(0) / 1024**3
        reserved = torch.cuda.memory_reserved(0) / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        
        return {
            'allocated_gb': round(allocated, 2),
            'reserved_gb': round(reserved, 2),
            'total_gb': round(total, 2),
            'utilization_percent': round((allocated / total) * 100, 1)
        }
    except Exception as e:
        print(f"Error getting GPU memory info: {e}")
        return None

def clean_response(response: str, original_question: str) -> str:
    """Clean the response: extract the answer, normalize whitespace, optional sentence-based truncation.
    Strips legacy chat artifacts ([INST]/[/INST], ChatML) if present (e.g. from a different backend)."""
    # Remove legacy chat template artifacts if present
    response = re.sub(r'<s>.*?\[/INST\]', '', response, flags=re.DOTALL)
    response = re.sub(r'Context:.*?Question:.*?Answer:', '', response, flags=re.DOTALL)
    response = re.sub(r'\[INST\].*?\[/INST\]', '', response, flags=re.DOTALL)
    # ChatML-style: strip assistant wrapper and end tokens
    response = re.sub(r'<\|im_start\|>\s*assistant\s*\n?', '', response, flags=re.IGNORECASE)
    response = re.sub(r'<\|im_end\|>.*', '', response, flags=re.DOTALL)
    response = re.sub(r'<\|im_start\|>.*', '', response, flags=re.DOTALL)

    # Clean up whitespace and newlines
    response = re.sub(r'\n+', ' ', response)
    response = re.sub(r'\s+', ' ', response).strip()

    # Ensure we don't return the original question
    if response.lower().startswith(original_question.lower()):
        response = response[len(original_question):].strip()

    # Remove any leading punctuation and artifacts
    response = re.sub(r'^[:\-\s]+', '', response)
    response = re.sub(r'Answer:\s*', '', response, flags=re.IGNORECASE)
    response = re.sub(r'^\[/INST\]\s*', '', response)
    response = re.sub(r'^\[INST\]\s*', '', response)
    
    # Smart sentence-based truncation to ensure complete responses
    max_length = 800  # Increased from 150 to allow for 4-line responses
    if len(response) > max_length:
        # Split into sentences more intelligently
        sentences = re.split(r'[.!?]+', response)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Build response sentence by sentence, ensuring we don't exceed max_length
        truncated_response = ""
        for sentence in sentences:
            # Add period if sentence doesn't end with punctuation
            if sentence and not sentence[-1] in '.!?':
                sentence += '.'
            
            # Check if adding this sentence would exceed our limit
            test_response = truncated_response + " " + sentence if truncated_response else sentence
            if len(test_response) <= max_length:
                truncated_response = test_response
            else:
                # If this sentence would exceed the limit, stop here
                break
        
        # Ensure we have at least one complete sentence
        if not truncated_response and sentences:
            # If we can't fit even one sentence, take the first one and truncate it
            truncated_response = sentences[0][:max_length-3] + "..."
        elif truncated_response:
            # Ensure proper ending
            if not truncated_response[-1] in '.!?':
                truncated_response += '.'
        
        response = truncated_response
    
    return response

def _gemini_response_text(response):
    """Get plain text from a Gemini generate_content response. Handles .text and candidates/parts."""
    if response is None:
        return ""
    # Try .text first (can raise ValueError if response has non-text parts)
    try:
        if hasattr(response, "text"):
            t = response.text
            if t is not None and (isinstance(t, str) and t.strip()):
                return t.strip() if isinstance(t, str) else str(t)
    except (ValueError, AttributeError):
        pass
    # Fallback: candidates[0].content.parts
    if hasattr(response, "candidates") and response.candidates:
        c = response.candidates[0]
        if hasattr(c, "content") and c.content and hasattr(c.content, "parts"):
            for p in c.content.parts:
                if hasattr(p, "text") and p.text:
                    return (p.text.strip() if isinstance(p.text, str) else str(p.text))
    return ""


def generate_response_optimized(question: str, context: str, field_guide: str = None, max_tokens: int = 256) -> str:
    """Generate response using Google Gemini 2.0 Flash API."""
    global _genai_client
    try:
        if not _genai_client:
            return "I'm sorry, the model is not loaded (Gemini client missing)."
        part_candidates = extract_part_number_candidates(question)
        if part_candidates:
            instruction = (
                "You are answering from a catalog knowledge base. The user is asking about a specific part number. "
                "Find that part number in the CONTEXT below and state the exact information given (product name, description, specifications). "
                "Copy the relevant lines from the context. If the part number appears in the context, you MUST report what is written there. "
                "Do NOT say the information is not in the context if you can see the part number or product name in the context. "
                "If the part number truly does not appear anywhere in the context, only then say it was not found."
            )
        else:
            instruction = (
                "Using ONLY the context below from the instrument/product knowledge base, answer the question. "
                "Include part numbers, product names, and specifications when they appear in the context. "
                "Do not say information is unavailable if it is present in the context below."
            )
        if field_guide:
            instruction += " " + field_guide[:400]
        context_trimmed = context[:14000] if len(context) > 14000 else context
        user_content = f"{instruction}\n\nCONTEXT:\n{context_trimmed}\n\nQUESTION: {question}"
        if LOG_PROMPT:
            print("[PROMPT] --- Chat prompt (first 2500 chars) ---")
            print(user_content[:2500])
            if len(user_content) > 2500:
                print("... [truncated]")
            print("[PROMPT] --- end ---")
        t0 = time.time()
        print("[LLM] Generating response (Gemini)...")
        response = _genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_content,
        )
        elapsed = time.time() - t0
        print(f"[LLM] Generated in {elapsed:.1f}s")
        raw_response = _gemini_response_text(response) or ""
        if not isinstance(raw_response, str):
            raw_response = str(raw_response)
        cleaned_response = clean_response(raw_response, question)
        if len(cleaned_response) < 10:
            return "Based on the available information, I cannot provide a complete answer at this time."
        return cleaned_response
    except Exception as e:
        global _last_chat_error
        _last_chat_error = f"{type(e).__name__}: {e}"
        print(f"Error generating response: {e}")
        traceback.print_exc()
        print("(Check traceback above. Common causes: invalid GEMINI_API_KEY, wrong GEMINI_MODEL, or network.)")
        return "I'm sorry, but I'm unable to process your question at the moment."


# Max characters of page text sent to LLM for product extraction (catalog pages can list many products).
_PRODUCT_EXTRACTION_PAGE_CHARS = 7000
_PRODUCT_EXTRACTION_MAX_NEW_TOKENS = 1024
# Max page images to send to Gemini for vision-based extraction (avoids context overflow).
_PRODUCT_EXTRACTION_MAX_IMAGES = 20


def _load_page_image_bytes(source_id: int, page_number: int):
    """Load image bytes for a page from DB + disk. Returns list of (image_id, bytes, mime_type) in image_index order. Skips missing files."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, file_path FROM images WHERE source_id=? AND page_number=? ORDER BY image_index",
            (source_id, page_number),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        path = os.path.join(DATA_DIR, (r["file_path"] or "").replace("/", os.sep))
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        ext = (os.path.splitext(path)[1] or "").lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        out.append((r["id"], data, mime))
        if len(out) >= _PRODUCT_EXTRACTION_MAX_IMAGES:
            break
    return out


def generate_product_extraction(page_text: str, field_guide: str, max_tokens: int = None) -> str:
    """Ask Gemini to extract product records from a single page's text. Returns raw response (expect JSON array)."""
    global _genai_client
    if max_tokens is None:
        max_tokens = _PRODUCT_EXTRACTION_MAX_NEW_TOKENS
    instruction = (
        "You are a catalog data extractor. Extract all products from the following catalog page text. "
        "Use the field examples to identify manufacturer part number, product name, description, secondary description, and category. "
        "Output ONLY a JSON array—no explanations, no markdown, no text before or after. "
        "Each element must be an object with keys: manufacturer_part_number (required), product_name, description, secondary_description, category. "
        "Use empty string for missing optional fields. "
        "If the page has no product listings (e.g. title page, index, blank), output exactly: [] "
        "IMPORTANT - Product groups / variants: Often one product name and description is shown once, then multiple part numbers listed below with only a variant-specific detail (e.g. 'Overall length 7in', 'Overall length 8in'). "
        "Treat these as variants of the same product. Output ONE object per part number. For each variant use the SAME product_name and description (from the shared header); put ONLY the variant-specific detail (e.g. length) in secondary_description. "
        "Example: 'CUSHING Dressing Forceps. Serrated. Semi-sharp dissecting end.' then 'NL1480 Overall length 7in (17.8cm).' and 'NL1481 Overall length 8in (20.3cm).' "
        "-> Output two objects: both product_name 'CUSHING Dressing Forceps', description 'Serrated. Semi-sharp dissecting end.'; first secondary_description 'Overall length 7in (17.8cm).', second 'Overall length 8in (20.3cm).'. "
    )
    if field_guide:
        instruction += " " + field_guide[:800]
    page_snippet = page_text[:_PRODUCT_EXTRACTION_PAGE_CHARS]
    user_content = f"{instruction}\n\nPage text:\n{page_snippet}\n\nJSON array:"

    if not _genai_client:
        return "[]"
    try:
        kwargs = {"model": GEMINI_MODEL, "contents": user_content}
        try:
            from google.genai.types import GenerateContentConfig
            kwargs["config"] = GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=max_tokens,
            )
        except (ImportError, TypeError, AttributeError):
            pass  # SDK may not support response_mime_type
        response = _genai_client.models.generate_content(**kwargs)
        raw = _gemini_response_text(response).strip()
        for marker in ["```json", "```", "[/INST]", "<|im_start|>assistant", "<|im_end|>"]:
            if marker in raw:
                raw = raw.split(marker)[-1].strip()
        return raw
    except Exception as e:
        print(f"Product extraction error (Gemini): {e}")
        return "[]"


def generate_product_extraction_with_images(
    page_text: str,
    field_guide: str,
    image_list: list,
    max_tokens: int = None,
) -> str:
    """Ask Gemini to extract product records from page text AND page images. image_list = [(image_id, bytes, mime_type), ...] in display order.
    Returns raw JSON array; each product should include image_indices (0-based list of which images depict that product)."""
    global _genai_client
    if max_tokens is None:
        max_tokens = _PRODUCT_EXTRACTION_MAX_NEW_TOKENS
    if not _genai_client or not image_list:
        return "[]"
    instruction = (
        "You are a catalog data extractor. You will see the TEXT of a catalog page followed by IMAGES from the same page. "
        "The images are in order: Image 0 is the first image, Image 1 is the second, and so on. "
        "Extract all products from the text. Use the field examples to identify manufacturer part number, product name, description, secondary description, and category. "
        "For EACH product you must also set 'image_indices': an array of 0-based indices (0, 1, 2, ...) indicating which image(s) show that product. "
        "Look at the images and the layout: match each product (by part number or position) to the correct image(s). "
        "One image may apply to multiple products (e.g. one photo for several part numbers). If a product has no visible image, use []. "
        "Output ONLY a JSON array—no explanations, no markdown. "
        "Each element: manufacturer_part_number (required), product_name, description, secondary_description, category, image_indices (required, array of integers). "
        "If the page has no product listings, output exactly: [] "
        "Product groups / variants: output ONE object per part number; use the SAME product_name and description for variants; put variant-specific text in secondary_description. "
        "Assign image_indices by looking at which image(s) depict each product."
    )
    if field_guide:
        instruction += " " + field_guide[:600]
    page_snippet = page_text[:_PRODUCT_EXTRACTION_PAGE_CHARS]
    text_part = f"{instruction}\n\nPage text:\n{page_snippet}\n\nThere are {len(image_list)} images below (Image 0 to Image {len(image_list) - 1}). Output JSON array with image_indices for each product:"
    try:
        from google.genai import types
        parts = [types.Part.from_text(text=text_part)]
        for _image_id, img_bytes, mime_type in image_list:
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))
        kwargs = {"model": GEMINI_MODEL, "contents": parts}
        try:
            kwargs["config"] = types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=max_tokens,
            )
        except (TypeError, AttributeError):
            pass
        response = _genai_client.models.generate_content(**kwargs)
        raw = _gemini_response_text(response).strip()
        for marker in ["```json", "```", "[/INST]", "<|im_start|>assistant", "<|im_end|>"]:
            if marker in raw:
                raw = raw.split(marker)[-1].strip()
        return raw
    except Exception as e:
        print(f"Product extraction with images error (Gemini): {e}")
        traceback.print_exc()
        return "[]"


def parse_products_from_response(raw: str) -> list:
    """Parse LLM output into list of product dicts. Tolerates markdown code blocks, extra text, and alternative keys. Accepts bare [...] or object with array (e.g. {"products": [...]})."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    # Try to extract JSON: first look for bare array [...], else use full text (object or array)
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        text = m.group(0)
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        parsed = json.loads(text)
        arr = parsed if isinstance(parsed, list) else None
        if arr is None and isinstance(parsed, dict):
            for key in ("products", "items", "data", "result"):
                if isinstance(parsed.get(key), list):
                    arr = parsed[key]
                    break
        if not isinstance(arr, list):
            return []
        # Unwrap double-nested arrays: [[{...}, {...}]] → [{...}, {...}]
        if arr and all(isinstance(el, list) for el in arr):
            arr = [item for sublist in arr for item in sublist]
        out = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            part = (
                item.get("manufacturer_part_number") or item.get("part_number") or item.get("part_no")
                or item.get("PartNumber") or ""
            )
            if isinstance(part, dict):
                part = ""
            part = str(part).strip()
            if not part:
                continue
            # image_indices: 0-based list of which page images depict this product (from vision extraction)
            raw_indices = item.get("image_indices") or item.get("image_index") or []
            if isinstance(raw_indices, int):
                raw_indices = [raw_indices]
            image_indices = [int(x) for x in raw_indices if isinstance(x, (int, float)) and 0 <= int(x) < 10000]
            out.append({
                "manufacturer_part_number": part,
                "product_name": (item.get("product_name") or item.get("name") or "").strip() or None,
                "description": (item.get("description") or item.get("desc") or "").strip() or None,
                "secondary_description": (item.get("secondary_description") or item.get("secondary_desc") or "").strip() or None,
                "category": (item.get("category") or "").strip() or None,
                "image_indices": image_indices,
            })
        return out
    except (json.JSONDecodeError, TypeError):
        # Try to salvage a partial array (e.g. truncated output)
        try:
            last_brace = text.rfind("}")
            if last_brace > 0:
                truncated = text[: last_brace + 1] + "]"
                arr = json.loads(truncated)
                if isinstance(arr, list):
                    out = []
                    for item in arr:
                        if not isinstance(item, dict):
                            continue
                        part = (item.get("manufacturer_part_number") or item.get("part_number") or item.get("part_no") or "").strip()
                        if not part:
                            continue
                        raw_idx = item.get("image_indices") or item.get("image_index") or []
                        if isinstance(raw_idx, int):
                            raw_idx = [raw_idx]
                        image_indices = [int(x) for x in raw_idx if isinstance(x, (int, float)) and 0 <= int(x) < 10000]
                        out.append({
                            "manufacturer_part_number": part,
                            "product_name": (item.get("product_name") or item.get("name") or "").strip() or None,
                            "description": (item.get("description") or "").strip() or None,
                            "secondary_description": (item.get("secondary_description") or "").strip() or None,
                            "category": (item.get("category") or "").strip() or None,
                            "image_indices": image_indices,
                        })
                    return out
        except Exception:
            pass
        return []


def _apply_image_part_number_samples_for_page(conn, source_id: int, page_number: int) -> None:
    """Apply image_part_number catalog samples for this page: link each (image_index, part_number) to the corresponding product. Preserves user corrections when re-running build."""
    rows = conn.execute(
        "SELECT value_text, notes FROM catalog_samples WHERE source_id=? AND page_number=? AND sample_type='image_part_number'",
        (source_id, page_number),
    ).fetchall()
    if not rows:
        return
    part_to_id = {}
    for r in conn.execute(
        "SELECT id, manufacturer_part_number FROM products WHERE source_id=? AND page_number=?",
        (source_id, page_number),
    ).fetchall():
        part = (r[1] or "").strip()
        if part:
            part_to_id[_normalize_part(part)] = r[0]
    for (value_text, notes) in rows:
        part = (value_text or "").strip()
        if not part:
            continue
        image_index_str = (notes or "").strip()
        if image_index_str.startswith("image_index:"):
            image_index_str = image_index_str.replace("image_index:", "").strip()
        try:
            image_index = int(image_index_str)
        except (ValueError, TypeError):
            continue
        product_id = part_to_id.get(_normalize_part(part))
        if not product_id:
            continue
        img_row = conn.execute(
            "SELECT id FROM images WHERE source_id=? AND page_number=? AND image_index=?",
            (source_id, page_number, image_index),
        ).fetchone()
        if not img_row:
            continue
        image_id = img_row[0]
        try:
            conn.execute(
                "INSERT OR IGNORE INTO product_images (product_id, image_id, display_order) VALUES (?, ?, ?)",
                (product_id, image_id, 0),
            )
        except sqlite3.IntegrityError:
            pass


def _bbox_center(bbox):
    """Return (cx, cy) from bbox [x0, y0, x1, y1] or (x0,y0,x1,y1)."""
    if not bbox or len(bbox) < 4:
        return None
    try:
        x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    except (TypeError, ValueError):
        return None


def _center_distance(c1, c2):
    """Euclidean distance between (cx, cy) points."""
    if not c1 or not c2:
        return float("inf")
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5


def _get_page_text_spans_with_bbox(pdf_path: str, page_index: int) -> list[dict]:
    """Extract text spans with bbox, size, and flags from a PDF page (for spatial extraction). Returns list of {bbox, text, size, flags}."""
    if not fitz:
        return []
    out = []
    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return []
        page = doc.load_page(page_index)
        d = page.get_text("dict")
        doc.close()
    except Exception:
        return []
    for block in d.get("blocks") or []:
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                bbox = span.get("bbox")
                if bbox is None:
                    continue
                if hasattr(bbox, "x0"):
                    bbox = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
                elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    bbox = tuple(float(bbox[i]) for i in range(4))
                else:
                    continue
                size = float(span.get("size") or 0)
                flags = int(span.get("flags") or 0)
                font = (span.get("font") or "") if isinstance(span.get("font"), str) else ""
                out.append({"bbox": bbox, "text": text, "size": size, "flags": flags, "font": font})
    return out


def run_profile_validation(conn, source_id: int, profile: dict, sample_pages: list[int]) -> list:
    """
    Return validation reports for sample pages. Spatial extraction was removed; kept for API compatibility.
    """
    return []


def _apply_proximity_image_links(conn, source_id: int, page_number: int) -> None:
    """Link images to products by layout proximity: each image is linked to the product(s) whose text block (containing its part number) is closest to the image. Uses images.bbox_json and page_blocks. Fallback when PDF-based proximity is not available."""
    try:
        img_rows = conn.execute(
            "SELECT id, bbox_json FROM images WHERE source_id=? AND page_number=? AND bbox_json IS NOT NULL AND bbox_json != ''",
            (source_id, page_number),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    try:
        block_rows = conn.execute(
            "SELECT id, bbox_json, text FROM page_blocks WHERE source_id=? AND page_number=?",
            (source_id, page_number),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not img_rows or not block_rows:
        return
    products = conn.execute(
        "SELECT id, manufacturer_part_number FROM products WHERE source_id=? AND page_number=?",
        (source_id, page_number),
    ).fetchall()
    if not products:
        return
    part_to_ids = {}
    for pid, part in products:
        part = (part or "").strip()
        if part:
            key = _normalize_part(part)
            if key not in part_to_ids:
                part_to_ids[key] = []
            part_to_ids[key].append(pid)
    blocks_with_products = []
    for bid, bbox_json, text in block_rows:
        try:
            bbox = json.loads(bbox_json) if isinstance(bbox_json, str) else bbox_json
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        center = _bbox_center(bbox)
        if center is None:
            continue
        text_ = text or ""
        product_ids_in_block = []
        for part_norm, pids in part_to_ids.items():
            part_raw = next((p[1] or "").strip() for p in products if _normalize_part((p[1] or "").strip()) == part_norm)
            if part_raw and re.search(r"\b" + re.escape(part_raw) + r"\b", text_, re.IGNORECASE):
                product_ids_in_block.extend(pids)
        if not product_ids_in_block:
            continue
        blocks_with_products.append((center, list(set(product_ids_in_block))))
    if not blocks_with_products:
        return
    display_order = 0
    for img_id, bbox_json in img_rows:
        try:
            bbox = json.loads(bbox_json) if isinstance(bbox_json, str) else bbox_json
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        im_center = _bbox_center(bbox)
        if im_center is None:
            continue
        best_dist = float("inf")
        best_product_ids = []
        for bl_center, pids in blocks_with_products:
            d = _center_distance(im_center, bl_center)
            if d < best_dist:
                best_dist = d
                best_product_ids = pids
        if best_product_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO product_images (product_id, image_id, display_order) VALUES (?, ?, ?)",
                    (best_product_ids[0], img_id, display_order),
                )
            except sqlite3.IntegrityError:
                pass
        display_order += 1


def _associate_images_by_catalog_number_proximity(
    conn, source_id: int, page_number: int, pdf_path: str, profile: dict
) -> None:
    """
    Image association step (after products exist): use PyMuPDF text spans and profile regex to find
    catalog number positions, then link each image to the product whose catalog number is nearest.

    When the profile describes a grid layout (orange line-segment markers), product cells are computed
    from those markers and each image is matched only to catalog numbers within the same cell.
    Falls back to page-wide proximity when no grid is detected.
    """
    if not fitz or not os.path.isfile(pdf_path):
        return
    page_index = page_number - 1
    spans = _get_page_text_spans_with_bbox(pdf_path, page_index)
    if not spans:
        return

    # --- compile catalog-number regexes from profile ---
    patterns = profile.get("catalog_number_patterns") or []
    regexes = []
    for p in patterns:
        r = (p.get("regex") or "").strip()
        if not r:
            continue
        if r.startswith("^"):
            r = r[1:]
        if r.endswith("$"):
            r = r[:-1]
        try:
            regexes.append(re.compile(r))
        except re.error:
            continue
    generic_rx = re.compile(r"[A-Z]{1,4}[\-]?\d{3,6}")

    # --- locate every catalog number on the page using profile-specific patterns ---
    catalog_positions = []
    for span in spans:
        text = (span.get("text") or "").strip()
        if not text:
            continue
        bbox = span.get("bbox")
        center = _bbox_center(bbox) if bbox and len(bbox) >= 4 else None
        if center is None:
            continue
        for rx in regexes:
            for m in rx.finditer(text):
                mpn = (m.group(0) or "").strip()
                if mpn:
                    catalog_positions.append((mpn, center[0], center[1]))

    # If profile-specific patterns found nothing at all, try the generic pattern page-wide
    if not catalog_positions:
        for span in spans:
            text = (span.get("text") or "").strip()
            if not text:
                continue
            bbox = span.get("bbox")
            center = _bbox_center(bbox) if bbox and len(bbox) >= 4 else None
            if center is None:
                continue
            for m in generic_rx.finditer(text):
                mpn = (m.group(0) or "").strip()
                if mpn:
                    catalog_positions.append((mpn, center[0], center[1]))

    # --- load products and images from DB ---
    products = conn.execute(
        "SELECT id, manufacturer_part_number FROM products WHERE source_id=? AND page_number=?",
        (source_id, page_number),
    ).fetchall()
    if not products:
        return
    part_to_id = {}
    for pid, part in products:
        part = (part or "").strip()
        if part:
            part_to_id[_normalize_part(part)] = pid
    try:
        img_rows = conn.execute(
            "SELECT id, bbox_json FROM images WHERE source_id=? AND page_number=? AND bbox_json IS NOT NULL AND bbox_json != ''",
            (source_id, page_number),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not img_rows:
        return

    conn.execute(
        "DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id=? AND page_number=?)",
        (source_id, page_number),
    )

    # --- try grid-cell detection from orange line-segment markers ---
    cells = []
    try:
        cells = get_product_cells_grid(pdf_path, page_index, profile)
    except Exception:
        pass

    def _find_cell(cx, cy):
        for idx, (x0, y0, x1, y1) in enumerate(cells):
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return idx
        return None

    if cells:
        cat_by_cell = {}
        for mpn, cx, cy in catalog_positions:
            ci = _find_cell(cx, cy)
            if ci is not None:
                cat_by_cell.setdefault(ci, []).append((mpn, cx, cy))

        # Per-cell fallback: for cells with no catalog numbers from profile patterns,
        # try the generic regex on spans within that cell to catch non-standard prefixes (e.g. CH8586)
        populated_cells = set(cat_by_cell.keys())
        all_cell_indices = set(range(len(cells)))
        empty_cells = all_cell_indices - populated_cells
        if empty_cells:
            for span in spans:
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                bbox = span.get("bbox")
                center = _bbox_center(bbox) if bbox and len(bbox) >= 4 else None
                if center is None:
                    continue
                ci = _find_cell(center[0], center[1])
                if ci not in empty_cells:
                    continue
                for m in generic_rx.finditer(text):
                    mpn = (m.group(0) or "").strip()
                    if mpn:
                        catalog_positions.append((mpn, center[0], center[1]))
                        cat_by_cell.setdefault(ci, []).append((mpn, center[0], center[1]))
            if empty_cells:
                filled = empty_cells - (all_cell_indices - set(cat_by_cell.keys()))
                if filled:
                    print(f"[Build listing] page={page_number} — generic regex filled {len(filled)} empty cell(s)")

    display_order = 0
    for img_id, bbox_json in img_rows:
        try:
            bbox = json.loads(bbox_json) if isinstance(bbox_json, str) else bbox_json
        except (TypeError, ValueError, json.JSONDecodeError):
            display_order += 1
            continue
        im_center = _bbox_center(bbox)
        if im_center is None:
            display_order += 1
            continue

        if cells:
            ci = _find_cell(im_center[0], im_center[1])
            candidates = cat_by_cell.get(ci, []) if ci is not None else catalog_positions
        else:
            candidates = catalog_positions

        best_dist = float("inf")
        best_mpn = None
        for mpn, cx, cy in candidates:
            d = _center_distance(im_center, (cx, cy))
            if d < best_dist:
                best_dist = d
                best_mpn = mpn
        if best_mpn:
            product_id = part_to_id.get(_normalize_part(best_mpn))
            if product_id:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO product_images (product_id, image_id, display_order) VALUES (?, ?, ?)",
                        (product_id, img_id, display_order),
                    )
                except sqlite3.IntegrityError:
                    pass
        display_order += 1

    method = f"grid-constrained ({len(cells)} cells)" if cells else "page-wide proximity"
    print(f"[Build listing] page={page_number} — image association ({method}): {len(img_rows)} image(s)")


def build_product_listing_for_page(source_id: int, page_number: int, field_guide: str, replace_page: bool = True) -> dict:
    """
    Extract products for a single page using only the LLM path (chunks + field guide + images → Gemini 2.0 Flash).
    Then associate images to products by spatial proximity to catalog numbers (PyMuPDF spans + regex).
    Returns {"created": N, "page_number": page_number, "errors": []}.
    """
    t0 = time.time()
    print(f"[Build listing] source_id={source_id} page={page_number} replace_page={replace_page} — starting (LLM-only extraction)")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT text FROM chunks WHERE source_id=? AND page_number=? ORDER BY chunk_index",
            (source_id, page_number),
        ).fetchall()
    except Exception:
        conn.close()
        return {"created": 0, "page_number": page_number, "errors": ["Failed to load chunks"]}
    if not rows:
        conn.close()
        return {"created": 0, "page_number": page_number, "errors": ["No chunks for this page"]}
    profile, _ = get_profile_for_source(conn, source_id)
    src_row = conn.execute("SELECT file_path FROM sources WHERE id=?", (source_id,)).fetchone()
    pdf_path = (src_row["file_path"] if src_row and src_row["file_path"] else None) or None
    if pdf_path and not os.path.isabs(pdf_path):
        pdf_path = os.path.join(ROOT, pdf_path)
    if profile and pdf_path and os.path.isfile(pdf_path):
        try:
            if should_skip_page_for_products(pdf_path, page_number - 1, profile):
                conn.close()
                print(f"[Build listing] page={page_number} — skipped (page type: non-product)")
                return {"created": 0, "page_number": page_number, "errors": [], "skipped": "page_type"}
        except Exception:
            pass
    conn.close()

    t1 = time.time()
    page_text = "\n\n".join(r["text"] or "" for r in rows).strip()
    if not page_text:
        return {"created": 0, "page_number": page_number, "errors": []}
    image_list = _load_page_image_bytes(source_id, page_number)
    use_vision = len(image_list) > 0
    if use_vision:
        print(f"[Build listing] page={page_number} — LLM extraction with {len(image_list)} images (vision)...")
    else:
        print(f"[Build listing] page={page_number} — LLM extraction (text only)...")
    t_llm_start = time.time()
    if use_vision:
        raw = generate_product_extraction_with_images(page_text, field_guide, image_list)
    else:
        raw = generate_product_extraction(page_text, field_guide)
    t_llm_end = time.time()
    print(f"[Build listing] page={page_number} — LLM done in {t_llm_end - t_llm_start:.1f}s")
    products = parse_products_from_response(raw)
    if len(products) == 0 and len(page_text) > 100:
        print(f"  [Build listing] Page {page_number}: 0 products extracted (page has {len(page_text)} chars). Check samples/instructions or LLM output.")
        snippet = (raw or "")[:2000].replace("\n", " ")
        print(f"  [Build listing] Page {page_number} raw LLM output (first 2000 chars): {snippet}")
    if LOG_PRODUCT_EXTRACTION_RAW:
        snippet = (raw or "")[:2000]
        print(f"  [Build listing] Page {page_number} raw LLM output:\n{snippet}")

    t_db_start = time.time()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    errors = []
    try:
        if replace_page:
            conn.execute(
                "DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id=? AND page_number=?)",
                (source_id, page_number),
            )
            conn.execute("DELETE FROM products WHERE source_id=? AND page_number=?", (source_id, page_number))
        created = 0
        for p in products:
            try:
                conn.execute(
                    """INSERT INTO products (source_id, page_number, manufacturer_part_number, product_name, description, secondary_description, category, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (source_id, page_number, p["manufacturer_part_number"], p.get("product_name"), p.get("description"), p.get("secondary_description"), p.get("category")),
                )
                created += 1
            except sqlite3.IntegrityError:
                pass
        # Image association: spatial proximity to catalog numbers (separate step; LLM is sole source for product data)
        if created > 0 and pdf_path and os.path.isfile(pdf_path) and profile:
            _associate_images_by_catalog_number_proximity(conn, source_id, page_number, pdf_path, profile)
        elif created > 0:
            # Fallback when no PDF or profile: use page_blocks if available
            _apply_proximity_image_links(conn, source_id, page_number)
        _apply_image_part_number_samples_for_page(conn, source_id, page_number)
        conn.commit()
        t_total = time.time() - t0
        print(f"[Build listing] page={page_number} — DB write done in {time.time() - t_db_start:.1f}s | total {t_total:.1f}s, created={created}")
        return {"created": created, "page_number": page_number, "errors": errors}
    except Exception as e:
        conn.rollback()
        print(f"[Build listing] page={page_number} — error: {e}")
        return {"created": 0, "page_number": page_number, "errors": [str(e)]}
    finally:
        conn.close()


def build_product_listing_for_catalog(source_id: int, replace: bool = True) -> dict:
    """
    Generate a product listing for one catalog using chunks, samples, and config.
    Writes to the database after each page so progress is saved if the request times out.
    Returns {"created": N, "pages_processed": M, "errors": []}.
    """
    if not load_models_once():
        return {"created": 0, "pages_processed": 0, "errors": ["Models not loaded"]}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        name_row = conn.execute("SELECT name FROM sources WHERE id=?", (source_id,)).fetchone()
        if not name_row:
            return {"created": 0, "pages_processed": 0, "errors": ["Catalog not found"]}
        rows = conn.execute(
            "SELECT page_number, chunk_index, text FROM chunks WHERE source_id=? ORDER BY page_number, chunk_index",
            (source_id,),
        ).fetchall()
        field_guide = build_field_guide_for_source(conn, source_id)
    finally:
        conn.close()
    if not rows:
        return {"created": 0, "pages_processed": 0, "errors": ["No chunks for this catalog"]}
    by_page = {}
    for r in rows:
        pno = r["page_number"] if r["page_number"] is not None else 0
        if pno not in by_page:
            by_page[pno] = []
        by_page[pno].append(r["text"] or "")
    if replace:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id=?)", (source_id,))
            conn.execute("DELETE FROM products WHERE source_id=?", (source_id,))
            conn.commit()
        finally:
            conn.close()
    total_created = 0
    pages_processed = 0
    errors = []
    for page_number in sorted(by_page.keys()):
        page_text = "\n\n".join(by_page[page_number]).strip()
        if not page_text:
            continue
        try:
            result = build_product_listing_for_page(source_id, page_number, field_guide, replace_page=False)
            total_created += result.get("created", 0)
            pages_processed += 1
            errors.extend(result.get("errors", []))
        except Exception as page_err:
            errors.append(f"Page {page_number}: {page_err}")
    return {"created": total_created, "pages_processed": pages_processed, "errors": errors}


def load_models_once():
    """Load embedding + chunks/FAISS + Gemini client. No local LLM (Gemini 2.0 Flash only)."""
    global _model_embed, _chunks_data, _chunk_sources, _faiss_index, _content_signature, _models_loaded, _device
    global _genai_client

    with _loading_lock:
        if _models_loaded:
            return True

        print("🚀 Loading embedding model and knowledge base...")
        
        # Set up device (for embeddings only; LLM is Gemini API)
        if torch.cuda.is_available():
            _device = torch.device('cuda:0')
            print(f"✅ Using GPU: {torch.cuda.get_device_name(0)}")
            
            # Clear GPU cache
            torch.cuda.empty_cache()
            
            # Show initial GPU memory
            gpu_info = get_gpu_memory_info()
            if gpu_info:
                print(f"📊 GPU Memory: {gpu_info['total_gb']}GB total")
        else:
            _device = torch.device('cpu')
            print("⚠️ CUDA not available, using CPU")
        
        # Load embedding model first (smaller, faster)
        print("📥 Loading embedding model...")
        try:
            _model_embed = SentenceTransformer('all-MiniLM-L6-v2', device=str(_device))
            print(f"✅ Embedding model loaded on {_device}")
            
            # Show GPU memory after embedding model
            if torch.cuda.is_available():
                gpu_info = get_gpu_memory_info()
                if gpu_info:
                    print(f"📊 GPU Memory after embedding: {gpu_info['allocated_gb']}GB allocated")
        except Exception as e:
            print(f"❌ Error loading embedding model: {e}")
            return False
        
        # Load chunks and FAISS index from SQLite + data/faiss_index.idx (built by rebuild.py)
        print("📥 Loading chunks and FAISS index...")
        _chunks_data = []
        _faiss_index = None
        _chunk_sources = set()
        try:
            if os.path.exists(DB_PATH) and os.path.exists(FAISS_PATH):
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT c.id, c.source_id, c.page_number, c.text, c.type, s.name AS source
                    FROM chunks c
                    JOIN sources s ON s.id = c.source_id
                    ORDER BY c.id
                """).fetchall()
                conn.close()
                _chunks_data = [
                    {"text": r["text"], "source": r["source"], "source_id": r["source_id"], "page_number": r["page_number"], "type": r["type"] or "text"}
                    for r in rows
                ]
                _faiss_index = faiss.read_index(FAISS_PATH)
                _chunk_sources = {c["source"] for c in _chunks_data}
                _content_signature = hashlib.md5(
                    f"{len(_chunks_data)}|{sorted(_chunk_sources)}".encode()
                ).hexdigest()
                print(f"✅ Loaded {len(_chunks_data)} chunks from {len(_chunk_sources)} sources (SQLite + FAISS)")
                print(f"   Sources: {sorted(_chunk_sources)}")
                print(f"   Knowledge base signature: {_content_signature[:16]}... (cache invalidated if this changes)")
            else:
                print("⚠️ No data found. Run: python scripts/rebuild.py (after placing PDFs in scripts/source_files/)")
                _content_signature = None
        except Exception as e:
            print(f"⚠️ Could not load from SQLite/FAISS: {e}. Run rebuild to ingest source documents.")
            _chunks_data = []
            _faiss_index = None
            _content_signature = None

        # Connect to Google Gemini 2.0 Flash (no local LLM loaded)
        try:
            from google import genai
            _genai_client = genai.Client(api_key=GEMINI_API_KEY)
            print(f"✅ Gemini API client ready (model: {GEMINI_MODEL})")
        except Exception as e:
            print(f"❌ Error creating Gemini client: {e}")
            return False

        _models_loaded = True
        print("✅ All models loaded successfully!")
        return True

def get_cached_response(question_hash):
    """Get cached response only if it was generated with the current knowledge base (same content signature)."""
    cache_file = Path(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'response_cache.pkl'))
    if cache_file.exists() and _content_signature is not None:
        try:
            with open(cache_file, 'rb') as f:
                cache = pickle.load(f)
                if question_hash in cache:
                    cached = cache[question_hash]
                    if cached.get('content_signature') == _content_signature:
                        _performance_stats['cached_requests'] += 1
                        return cached
        except Exception as e:
            print(f"Cache read error: {e}")
    return None

def cache_response(question_hash, response_data):
    """Cache response with size management"""
    cache_file = Path(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'response_cache.pkl'))
    try:
        cache = {}
        if cache_file.exists():
            with open(cache_file, 'rb') as f:
                cache = pickle.load(f)
        
        # Limit cache size to 1000 entries
        if len(cache) >= 1000:
            # Remove oldest entries
            oldest_keys = list(cache.keys())[:100]
            for key in oldest_keys:
                del cache[key]
        
        cache[question_hash] = response_data
        
        with open(cache_file, 'wb') as f:
            pickle.dump(cache, f)
            
    except Exception as e:
        print(f"Cache write error: {e}")

def get_product_image_refs_for_question(question: str):
    """
    Look up products whose part number or product name matches the question and return their linked images.
    Returns (list of image URLs, context_line or None). Uses products + product_images tables.
    Tries part-number match first; if none, tries product-by-name (e.g. 'Jacobson Vessel knife').
    """
    if not question or not question.strip():
        return [], None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        wanted = _question_part_numbers_set(question)
        matching = []
        if wanted:
            rows = conn.execute(
                "SELECT id, manufacturer_part_number, product_name FROM products"
            ).fetchall()
            matching = [r for r in rows if (r["manufacturer_part_number"] or "").strip() and _normalize_part(r["manufacturer_part_number"]) in wanted]
        if not matching:
            by_name = get_products_matching_name_query(question, max_products=5)
            matching = [dict(r) for r in by_name]
        if not matching:
            conn.close()
            return [], None
        refs = []
        parts = []
        for r in matching:
            pid = r["id"]
            part = (r["manufacturer_part_number"] or "").strip()
            img_rows = conn.execute(
                """SELECT i.source_id, i.page_number, i.image_index
                   FROM product_images pi JOIN images i ON i.id = pi.image_id
                   WHERE pi.product_id=? ORDER BY pi.display_order, pi.id""",
                (pid,),
            ).fetchall()
            for im in img_rows:
                url = f"/api/image/{im['source_id']}/{im['page_number']}/{im['image_index']}"
                if url not in refs:
                    refs.append(url)
            if part:
                parts.append(part)
        conn.close()
        if not refs:
            return [], None
        context_line = f"Database product-image association: The following image(s) are linked to product(s) {', '.join(parts)}. Use this to answer which image is correct for that part number."
        return refs, context_line
    except sqlite3.OperationalError:
        return [], None


def _product_rows_to_cards(rows, conn):
    """Build list of product card dicts (with image_refs) from product rows. conn must be open with row_factory."""
    cards = []
    for r in rows:
        pid = r["id"] if isinstance(r, dict) else r[0]
        img_rows = conn.execute(
            """SELECT i.source_id, i.page_number, i.image_index
               FROM product_images pi JOIN images i ON i.id = pi.image_id
               WHERE pi.product_id=? ORDER BY pi.display_order, pi.id""",
            (pid,),
        ).fetchall()
        image_refs = [f"/api/image/{im['source_id']}/{im['page_number']}/{im['image_index']}" for im in img_rows]
        cards.append({
            "id": r["id"],
            "manufacturer_part_number": (r["manufacturer_part_number"] or "").strip(),
            "product_name": (r["product_name"] or "").strip(),
            "description": (r["description"] or "").strip(),
            "secondary_description": (r["secondary_description"] or "").strip(),
            "category": (r["category"] or "").strip(),
            "page_number": r["page_number"],
            "manufacturer": (r["manufacturer"] or "").strip(),
            "image_refs": image_refs,
        })
    return cards


def get_product_cards_for_image_refs(image_refs: list):
    """
    Given a list of image URLs (/api/image/source_id/page_number/image_index), find products
    that have those images linked via product_images. Return product cards (with their image_refs)
    so the chat UI can show both product information and images for the primary product(s).
    """
    if not image_refs:
        return []
    # Parse refs to (source_id, page_number, image_index)
    triples = []
    for ref in image_refs:
        if not ref or "/api/image/" not in ref:
            continue
        parts = ref.replace("/api/image/", "").strip("/").split("/")
        if len(parts) >= 3:
            try:
                sid, pno, idx = int(parts[0]), int(parts[1]), int(parts[2])
                triples.append((sid, pno, idx))
            except (ValueError, TypeError):
                continue
    if not triples:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # Get image ids for these (source_id, page_number, image_index)
        image_ids = []
        for sid, pno, idx in triples:
            row = conn.execute(
                "SELECT id FROM images WHERE source_id=? AND page_number=? AND image_index=?",
                (sid, pno, idx),
            ).fetchone()
            if row:
                image_ids.append(row["id"])
        if not image_ids:
            conn.close()
            return []
        # Product ids that have any of these images
        placeholders = ",".join("?" * len(image_ids))
        pi_rows = conn.execute(
            f"SELECT DISTINCT product_id FROM product_images WHERE image_id IN ({placeholders}) ORDER BY product_id",
            image_ids,
        ).fetchall()
        product_ids = [r["product_id"] for r in pi_rows]
        if not product_ids:
            conn.close()
            return []
        ph = ",".join("?" * len(product_ids))
        rows = conn.execute(
            f"SELECT id, manufacturer_part_number, product_name, description, secondary_description, category, page_number, manufacturer FROM products WHERE id IN ({ph}) ORDER BY page_number, id",
            product_ids,
        ).fetchall()
        cards = _product_rows_to_cards(rows, conn)
        conn.close()
        return cards
    except sqlite3.OperationalError:
        return []


def get_product_cards_for_question(question: str):
    """
    Return full product card data for products that match the question:
    - If the question mentions a part number, return cards for those products (exact match).
    - If not, try product-by-name search (e.g. 'Jacobson Vessel knife') and return cards for matches.
    Each card: id, manufacturer_part_number, product_name, description, secondary_description,
    category, page_number, manufacturer, image_refs (list of image URLs).
    """
    if not question or not question.strip():
        return []
    wanted = _question_part_numbers_set(question)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, manufacturer_part_number, product_name, description, secondary_description, category, page_number, manufacturer FROM products"
        ).fetchall()
        matching = []
        if wanted:
            matching = [r for r in rows if (r["manufacturer_part_number"] or "").strip() and _normalize_part(r["manufacturer_part_number"]) in wanted]
        if not matching:
            # No part number in question: try product-by-name so UI shows cards for "Jacobson Vessel knife" etc.
            by_name = get_products_matching_name_query(question, max_products=5)
            matching = [dict(r) for r in by_name]
        if not matching:
            conn.close()
            return []
        cards = _product_rows_to_cards(matching, conn)
        conn.close()
        return cards
    except sqlite3.OperationalError:
        return []


# Part-number pattern: common catalog styles (e.g. NL3006, NL3720, ABC-123, 12345)
_PART_NUMBER_RE = re.compile(r"\b([A-Z]{2,5}[-\s]?\d{3,}[A-Z0-9-]*|\d{4,}[A-Z]{0,3})\b", re.IGNORECASE)


def _normalize_part(part: str) -> str:
    """Normalize part number for comparison (lowercase, collapse spaces/dashes)."""
    if not part or not isinstance(part, str):
        return ""
    return re.sub(r"[\s\-]+", "", part.strip().lower())


def extract_part_number_candidates(question):
    """Return list of tokens from question that look like part numbers (for keyword boost)."""
    if not question or not question.strip():
        return []
    return list(dict.fromkeys(_PART_NUMBER_RE.findall(question)))  # preserve order, dedupe


def _question_part_numbers_set(question: str):
    """Return set of normalized part numbers mentioned in the question (for exact matching)."""
    candidates = extract_part_number_candidates(question)
    return {_normalize_part(p) for p in candidates if _normalize_part(p)}


def get_chunks_for_page(source_id: int, page_number: int, max_chunks: int = 10):
    """Return chunks for a given (source_id, page_number), e.g. to prime context when we found a product by name."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT c.id, c.source_id, c.page_number, c.text, s.name AS source
               FROM chunks c JOIN sources s ON s.id = c.source_id
               WHERE c.source_id=? AND c.page_number=?
               ORDER BY c.chunk_index LIMIT ?""",
            (source_id, page_number, max_chunks),
        ).fetchall()
        conn.close()
        return [
            {"text": (r["text"] or "")[:1200], "source": r["source"], "source_id": r["source_id"], "page_number": r["page_number"]}
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "need", "ought",
    "it", "its", "he", "she", "we", "they", "me", "my", "our", "your",
    "his", "her", "him", "them", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "if", "or", "and", "but", "not", "no", "so", "to", "of", "in",
    "on", "at", "by", "for", "with", "from", "as", "into", "about",
    "up", "out", "off", "all", "any", "each", "some", "such",
    "tell", "show", "find", "give", "get", "list", "describe",
    "information", "info", "details", "know", "about", "like",
})


def get_products_matching_name_query(question: str, max_products: int = 5):
    """
    Search products by product_name (case-insensitive). Question is split into
    significant words (stopwords removed); products where product_name contains
    all significant words are returned.  Requires at least 2 significant words
    to avoid overly broad single-word matches.
    """
    if not question or not question.strip():
        return []
    tokens = [w for w in re.split(r"[^\w]+", question.strip()) if len(w) >= 2]
    words = [w for w in tokens if w.lower() not in _STOPWORDS]
    if len(words) < 2:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, source_id, page_number, manufacturer_part_number, product_name, description, secondary_description, category, manufacturer FROM products"
        ).fetchall()
        conn.close()
        words_lower = [w.lower() for w in words]
        matching = []
        for r in rows:
            name = (r["product_name"] or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            if all(w in name_lower for w in words_lower):
                matching.append(dict(r))
                if len(matching) >= max_products:
                    break
        return matching
    except sqlite3.OperationalError:
        return []


def _query_to_search_words(question: str, min_len: int = 2):
    """Extract significant words from a question for chunk search (e.g. 'horsely dura separator' -> ['horsely', 'dura', 'separator'])."""
    if not question or not question.strip():
        return []
    words = [w for w in re.split(r"[^\w]+", question.strip()) if len(w) >= min_len]
    return words


def get_chunks_containing_query_words(question: str, max_chunks: int = 5):
    """
    Find chunks that contain the question's key words (e.g. 'horsely dura separator').
    Does not depend on the product table. Prefer chunks that contain ALL words; if none,
    return chunks that contain the most words. Case-insensitive.
    """
    words = _query_to_search_words(question, min_len=2)
    if not words:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # First try: chunks that contain ALL words (AND)
        conditions = " AND ".join("LOWER(c.text) LIKE ?" for _ in words)
        params = [f"%{w.lower()}%" for w in words]
        params.append(max_chunks * 2)  # fetch extra in case we dedupe
        rows = conn.execute(
            f"""SELECT c.id, c.source_id, c.page_number, c.chunk_index, c.text, s.name AS source
                FROM chunks c JOIN sources s ON s.id = c.source_id
                WHERE {conditions}
                ORDER BY c.source_id, c.page_number, c.chunk_index
                LIMIT ?""",
            params,
        ).fetchall()
        if rows:
            conn.close()
            return [
                {"text": (r["text"] or "")[:1200], "source": r["source"], "source_id": r["source_id"], "page_number": r["page_number"]}
                for r in rows[:max_chunks]
            ]
        # Fallback: chunks that contain ANY word; rank by how many words they contain
        seen_ids = set()
        scored = []
        for w in words:
            pattern = f"%{w.lower()}%"
            for r in conn.execute(
                """SELECT c.id, c.source_id, c.page_number, c.chunk_index, c.text, s.name AS source
                   FROM chunks c JOIN sources s ON s.id = c.source_id
                   WHERE LOWER(c.text) LIKE ?
                   LIMIT 50""",
                (pattern,),
            ).fetchall():
                cid = r["id"]
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                text_lower = (r["text"] or "").lower()
                score = sum(1 for ww in words if ww.lower() in text_lower)
                scored.append((score, r))
        conn.close()
        scored.sort(key=lambda x: (-x[0], x[1]["source_id"], x[1]["page_number"], x[1]["chunk_index"]))
        return [
            {"text": (r["text"] or "")[:1200], "source": r["source"], "source_id": r["source_id"], "page_number": r["page_number"]}
            for _, r in scored[:max_chunks]
        ]
    except sqlite3.OperationalError:
        return []


def get_chunks_containing_text(needle, max_chunks=3):
    """
    Return up to max_chunks chunks whose text contains needle (case-insensitive).
    Also tries needle with spaces removed so 'NL3006' matches 'NL 3006' in the PDF text.
    """
    if not needle or not needle.strip():
        return []
    needle = needle.strip()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        pattern = f"%{needle}%"
        rows = conn.execute(
            """SELECT c.id, c.source_id, c.page_number, c.text, s.name AS source
               FROM chunks c JOIN sources s ON s.id = c.source_id
               WHERE LOWER(c.text) LIKE LOWER(?)
               ORDER BY c.id LIMIT ?""",
            (pattern, max_chunks),
        ).fetchall()
        if not rows and len(needle) >= 4:
            needle_no_spaces = needle.replace(" ", "").lower()
            if needle_no_spaces != needle.lower():
                pattern_alt = f"%{needle_no_spaces}%"
                rows = conn.execute(
                    """SELECT c.id, c.source_id, c.page_number, c.text, s.name AS source
                       FROM chunks c JOIN sources s ON s.id = c.source_id
                       WHERE REPLACE(REPLACE(LOWER(c.text), ' ', ''), char(9), '') LIKE ?
                       ORDER BY c.id LIMIT ?""",
                    (pattern_alt, max_chunks),
                ).fetchall()
        conn.close()
        return [
            {"text": (r["text"] or "")[:1200], "source": r["source"], "source_id": r["source_id"], "page_number": r["page_number"]}
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def _format_product_context_lines(rows, conn=None):
    """Build 'KNOWN PRODUCTS' text from a list of product rows (dicts with product fields). conn optional for sibling lookup."""
    if not rows:
        return None
    lines = []
    for r in rows:
        part = (r.get("manufacturer_part_number") or "").strip()
        name = (r.get("product_name") or "").strip()
        desc = (r.get("description") or "").strip()
        sec = (r.get("secondary_description") or "").strip()
        cat = (r.get("category") or "").strip()
        line = f"Product: {part}" + (f" — {name}" if name else "")
        if desc:
            line += f". {desc}"
        if sec:
            line += f" {sec}"
        if cat:
            line += f" (Category: {cat})"
        lines.append(line)
    return "KNOWN PRODUCTS (from database):\n" + "\n".join(lines)


def get_product_context_for_question(question):
    """
    If the question mentions a known manufacturer_part_number, return a short context string
    (product name, description, etc.) so the model can answer even when no chunk is retrieved.
    If the question does NOT mention a part number, try matching by product_name (e.g. 'Jacobson Vessel knife')
    so retrieval-by-name works. When a product has variants (same product_name + description, same source),
    include them so the model can say e.g. "Also available as NL1481 (8in)."
    """
    if not question or not question.strip():
        return None
    wanted = _question_part_numbers_set(question)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source_id, manufacturer_part_number, product_name, description, secondary_description, category FROM products"
        ).fetchall()
        conn.close()
        matching = []
        if wanted:
            matching = [
                r for r in rows
                if (r["manufacturer_part_number"] or "").strip()
                and _normalize_part(r["manufacturer_part_number"]) in wanted
            ]
        if not matching:
            # No part number in question: try product-by-name search so "Jacobson Vessel knife" finds the product
            by_name = get_products_matching_name_query(question, max_products=5)
            matching = [r for r in by_name]
        if not matching:
            return None
        lines = []
        for r in matching:
            part = (r["manufacturer_part_number"] or "").strip()
            name = (r["product_name"] or "").strip()
            desc = (r["description"] or "").strip()
            sec = (r["secondary_description"] or "").strip()
            cat = (r["category"] or "").strip()
            line = f"Product: {part}" + (f" — {name}" if name else "")
            if desc:
                line += f". {desc}"
            if sec:
                line += f" {sec}"
            if cat:
                line += f" (Category: {cat})"
            lines.append(line)
            # Include sibling variants (same product name + description, same source) so the model can mention "also available as NL1481 (8in)"
            if name or desc:
                siblings = [
                    o for o in rows
                    if o["source_id"] == r["source_id"]
                    and (o["manufacturer_part_number"] or "").strip().lower() != part.lower()
                    and (o["product_name"] or "").strip() == name
                    and (o["description"] or "").strip() == desc
                ]
                if siblings:
                    sibling_parts = [f"{s['manufacturer_part_number']} ({s['secondary_description'] or 'variant'})" for s in siblings[:5]]
                    lines.append(f"  Other variants (same product): " + "; ".join(sibling_parts))
        return "KNOWN PRODUCTS (from database):\n" + "\n".join(lines)
    except sqlite3.OperationalError:
        return None


def get_image_refs_for_chunks(chunk_tuples):
    """Return list of image URLs for (source_id, page_number) pairs that have images. chunk_tuples = [(source_id, page_number), ...]."""
    if not chunk_tuples:
        return []
    seen = set()
    refs = []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for sid, pno in chunk_tuples:
        if (sid, pno) in seen:
            continue
        seen.add((sid, pno))
        row = conn.execute(
            "SELECT source_id, page_number, image_index FROM images WHERE source_id=? AND page_number=? LIMIT 1",
            (sid, pno),
        ).fetchone()
        if row:
            refs.append(f"/api/image/{row['source_id']}/{row['page_number']}/{row['image_index']}")
    conn.close()
    return refs


def get_catalog_samples_for_sources(source_ids):
    """Load catalog samples (and config) for the given source_ids. Returns list of dicts: source_id, sample_type, value_text, notes; and optional config per source. Safe if tables are missing."""
    if not source_ids:
        return [], {}
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(source_ids))
        rows = conn.execute(
            f"SELECT source_id, page_number, sample_type, value_text, notes FROM catalog_samples WHERE source_id IN ({placeholders}) ORDER BY source_id, sample_type, id",
            list(source_ids),
        ).fetchall()
        config_rows = conn.execute(
            f"SELECT source_id, config_json FROM catalog_config WHERE source_id IN ({placeholders})",
            list(source_ids),
        ).fetchall()
        conn.close()
        samples = [{"source_id": r["source_id"], "page_number": r["page_number"], "sample_type": r["sample_type"], "value_text": r["value_text"], "notes": r["notes"] or ""} for r in rows]
        config_by_source = {}
        for r in config_rows:
            if r["config_json"]:
                try:
                    config_by_source[r["source_id"]] = json.loads(r["config_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
        return samples, config_by_source
    except sqlite3.OperationalError:
        return [], {}


def get_sample_terms_for_search():
    """Load samples from all catalogs that have chunks; return a short string of example terms to append to the user query so FAISS retrieval is biased toward similar content. Safe if tables missing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        source_ids = [r[0] for r in conn.execute("SELECT DISTINCT source_id FROM chunks").fetchall()]
        conn.close()
        if not source_ids:
            return ""
        samples, _ = get_catalog_samples_for_sources(source_ids)
        by_type = {}
        for s in samples:
            t = s["sample_type"]
            if t not in by_type:
                by_type[t] = []
            val = (s["value_text"] or "").strip()
            if val and val not in by_type[t]:
                by_type[t].append(val)
        parts = []
        if by_type.get("part_number"):
            parts.append("part numbers like " + ", ".join(repr(e) for e in by_type["part_number"][:5]))
        if by_type.get("product_name"):
            parts.append("product names like " + ", ".join(repr(e) for e in by_type["product_name"][:3]))
        if by_type.get("image_part_number"):
            parts.append("image-associated part numbers: " + ", ".join(repr(e) for e in by_type["image_part_number"][:5]))
        if by_type.get("category"):
            parts.append("categories: " + ", ".join(repr(e) for e in by_type["category"][:5]))
        if by_type.get("description"):
            short = [repr((e[:40] + "…") if len(e) > 40 else e) for e in by_type["description"][:2]]
            parts.append("descriptions like " + ", ".join(short))
        if by_type.get("secondary_description"):
            short = [repr((e[:40] + "…") if len(e) > 40 else e) for e in by_type["secondary_description"][:2]]
            parts.append("secondary descriptions like " + ", ".join(short))
        if not parts:
            return ""
        return " Catalog field examples: " + "; ".join(parts)
    except sqlite3.OperationalError:
        return ""


def format_samples_as_field_guide(samples, config_by_source=None):
    """Format catalog samples into a short instruction block so the model learns how to parse and associate data to fields (part number, product name, description)."""
    if not samples:
        return ""
    by_type = {}
    for s in samples:
        t = s["sample_type"]
        if t not in by_type:
            by_type[t] = []
        val = (s["value_text"] or "").strip()
        if val and val not in by_type[t]:
            by_type[t].append(val)
    parts = []
    labels = {
        "part_number": "Part numbers",
        "product_name": "Product names",
        "description": "Descriptions",
        "secondary_description": "Secondary descriptions",
        "category": "Categories",
        "other": "Other fields",
    }
    for st in ("part_number", "product_name", "description", "secondary_description", "category", "other"):
        if st in by_type and by_type[st]:
            label = labels.get(st, st.replace("_", " "))
            examples = by_type[st][:8]  # cap so prompt doesn't explode
            parts.append(f"{label} in this catalog look like: {', '.join(repr(e) for e in examples)}")
    image_assocs = by_type.get("image_part_number") or []
    if image_assocs:
        image_samples_full = []
        for s in samples:
            if s.get("sample_type") == "image_part_number":
                val = (s.get("value_text") or "").strip()
                pno = s.get("page_number")
                notes = (s.get("notes") or "").strip()
                idx = notes.replace("image_index:", "").strip() if notes.startswith("image_index:") else "?"
                if val and pno is not None:
                    image_samples_full.append(f"page {pno} image {idx} → part number {repr(val)}")
        if image_samples_full:
            parts.append("Image-to-part-number associations: " + "; ".join(image_samples_full[:10]))
    if not parts:
        return ""
    guide = (
        "When parsing the context, use these user-provided examples to identify part numbers, product names, descriptions, secondary descriptions, and categories. "
        "Treat only text that matches the style of these examples as part numbers or product names; do not treat phone numbers, page numbers, or plain digits as part numbers. "
        "Use category examples to recognize section headings; use image-to-part-number associations to link images to the correct product. "
        "Then associate each field correctly when answering. "
    ) + " ".join(parts)
    if config_by_source:
        hints = []
        for sid, cfg in config_by_source.items():
            if isinstance(cfg, dict):
                if cfg.get("part_number_rules"):
                    hints.append("Part number rules: " + str(cfg["part_number_rules"])[:200])
                if cfg.get("language"):
                    hints.append("Language: " + str(cfg["language"]))
        if hints:
            guide += " Catalog instructions: " + "; ".join(hints[:3])
    return guide


def format_analysis_profile_for_llm(profile):
    """Format the analysis catalog profile (from Analyze Catalog Layout) into instructions for the LLM."""
    if not profile or not isinstance(profile, dict):
        return ""
    parts = []
    zd = profile.get("zone_detection") or {}
    if zd.get("method"):
        parts.append(f"Zone delimiter: {zd['method']}.")
        if zd.get("color_rgb"):
            parts.append("Use zone boundaries to associate images only with products in the same zone.")
    patterns = profile.get("catalog_number_patterns") or []
    if patterns:
        descs = [p.get("description") or p.get("regex", "")[:40] for p in patterns[:5]]
        parts.append("Catalog/part number patterns: " + "; ".join(descs) + ".")
    ir = profile.get("image_rules") or {}
    if ir.get("large_photo_association"):
        parts.append(f"Large product photos: associate to {ir['large_photo_association']} (family or variant).")
    if ir.get("small_drawing_association"):
        parts.append("Small detail drawings: associate to nearest catalog number in the same zone.")
    ph = profile.get("product_hierarchy") or {}
    if ph.get("family_name_detection"):
        parts.append("Family name: " + str(ph["family_name_detection"])[:120] + ".")
    if ph.get("variant_detection"):
        parts.append("Variants: " + str(ph["variant_detection"])[:120] + ".")
    if not parts:
        return ""
    return "Catalog profile (use for extraction): " + " ".join(parts)


def build_field_guide_for_source(conn, source_id: int):
    """Build full field guide for product extraction: samples + config hints + analysis profile instructions."""
    samples, config_by_source = get_catalog_samples_for_sources([source_id])
    guide = format_samples_as_field_guide(samples, config_by_source) if samples else ""
    analysis = load_analysis_profile_for_source(conn, source_id)
    if analysis:
        profile_instructions = format_analysis_profile_for_llm(analysis)
        if profile_instructions:
            guide = (guide + " " + profile_instructions).strip() if guide else profile_instructions
    return guide


@app.route('/api/image/<int:source_id>/<int:page_number>/<int:image_index>', methods=['GET'])
def serve_image(source_id, page_number, image_index):
    """Serve an extracted image from the knowledge base."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT file_path FROM images WHERE source_id=? AND page_number=? AND image_index=?",
        (source_id, page_number, image_index),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Image not found"}), 404
    path = os.path.join(DATA_DIR, row["file_path"].replace("/", os.sep))
    if not os.path.isfile(path):
        return jsonify({"error": "Image file not found"}), 404
    ext = os.path.splitext(path)[1].lower()
    mimetypes = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
    mimetype = mimetypes.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mimetype, max_age=86400)


# --- Catalog profile: resolve analysis profile (catalog_profiles) first, then DB catalog_profile, then YAML ---
def get_profile_for_source(conn, source_id: int):
    """Return (profile_dict, profile_path_or_none) for zone detection and image association. Prefers analysis profile from catalog_profiles."""
    analysis = load_analysis_profile_for_source(conn, source_id)
    if analysis and (analysis.get("zone_detection") or analysis.get("image_rules")):
        return analysis, None
    try:
        row = conn.execute("SELECT config_json FROM catalog_config WHERE source_id=?", (source_id,)).fetchone()
        if row and row["config_json"]:
            config = json.loads(row["config_json"])
            if isinstance(config, dict):
                cp = config.get("catalog_profile")
                if isinstance(cp, dict) and cp.get("zone_detection"):
                    return cp, None
    except (TypeError, ValueError, json.JSONDecodeError, sqlite3.OperationalError):
        pass
    return resolve_profile_for_source(conn, source_id)


# --- Catalog setup: list catalogs, get content, config, samples ---

@app.route('/api/catalogs', methods=['GET'])
def api_catalogs():
    """List all catalogs (sources) with id and name."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, name FROM sources ORDER BY name").fetchall()
        conn.close()
        return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/content', methods=['GET'])
def api_catalog_content(source_id):
    """Get catalog content: pages with chunk text and image refs per page."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        name_row = conn.execute("SELECT name FROM sources WHERE id=?", (source_id,)).fetchone()
        if not name_row:
            conn.close()
            return jsonify({"error": "Catalog not found"}), 404
        chunks = conn.execute(
            "SELECT id, page_number, chunk_index, text FROM chunks WHERE source_id=? ORDER BY page_number, chunk_index",
            (source_id,),
        ).fetchall()
        imgs = conn.execute(
            "SELECT page_number, image_index FROM images WHERE source_id=? ORDER BY page_number, image_index",
            (source_id,),
        ).fetchall()
        conn.close()
        pages = {}
        for c in chunks:
            pno = c["page_number"] or 0
            if pno not in pages:
                pages[pno] = {"page_number": pno, "chunks": [], "images": []}
            pages[pno]["chunks"].append({"id": c["id"], "chunk_index": c["chunk_index"], "text": c["text"]})
        for img in imgs:
            pno = img["page_number"]
            if pno not in pages:
                pages[pno] = {"page_number": pno, "chunks": [], "images": []}
            pages[pno]["images"].append({
                "image_index": img["image_index"],
                "url": f"/api/image/{source_id}/{pno}/{img['image_index']}",
            })
        return jsonify({"catalog_id": source_id, "catalog_name": name_row["name"], "pages": list(pages.values())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/config', methods=['GET', 'PUT'])
def api_catalog_config(source_id):
    """Get or update catalog instruction set (config JSON)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            row = conn.execute("SELECT config_json FROM catalog_config WHERE source_id=?", (source_id,)).fetchone()
            conn.close()
            config = json.loads(row["config_json"]) if row and row["config_json"] else {}
            return jsonify(config)
        data = request.get_json() or {}
        conn.execute(
            "INSERT INTO catalog_config (source_id, config_json, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(source_id) DO UPDATE SET config_json=excluded.config_json, updated_at=datetime('now')",
            (source_id, json.dumps(data)),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/profile-status', methods=['GET'])
def api_catalog_profile_status(source_id):
    """Get analysis profile status for UI: status, analyzed_at, analyzed_by_model, catalog_id, manufacturer, last_rebuild_at."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        status = get_analysis_profile_status(conn, source_id)
        if status is None:
            status = {}
        try:
            row = conn.execute("SELECT last_rebuild_at FROM sources WHERE id = ?", (source_id,)).fetchone()
            status["last_rebuild_at"] = row["last_rebuild_at"] if row and row["last_rebuild_at"] else None
        except sqlite3.OperationalError:
            status["last_rebuild_at"] = None  # column added by rebuild.py migration
        conn.close()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/rebuild', methods=['POST'])
def api_catalog_rebuild(source_id):
    """Rebuild a single catalog: re-extract PDF, chunks, images, page_blocks; rebuild FAISS; set last_rebuild_at. Runs scripts/rebuild.py --source-id."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT id, name FROM sources WHERE id = ?", (source_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "Catalog not found"}), 404
        rebuild_script = os.path.join(SCRIPT_DIR, "rebuild.py")
        if not os.path.isfile(rebuild_script):
            return jsonify({"error": "rebuild.py not found"}), 500
        result = subprocess.run(
            [sys.executable, rebuild_script, "--source-id", str(source_id)],
            cwd=ROOT,
            timeout=600,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip() or "Rebuild failed"
            return jsonify({"error": err}), 500
        return jsonify({"ok": True, "message": "Catalog rebuilt. Restart the chat server to load the new index."})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Rebuild timed out (10 min)"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/profile-analysis', methods=['GET', 'PUT'])
def api_catalog_profile_analysis(source_id):
    """GET: full profile JSON (from catalog_profiles or default) for editor. PUT: update profile_json and set status to verified."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            row = conn.execute(
                "SELECT profile_json FROM catalog_profiles WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            conn.close()
            if row and row["profile_json"]:
                try:
                    return jsonify(json.loads(row["profile_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            conn = sqlite3.connect(DB_PATH)
            default = load_default_profile()
            conn.close()
            return jsonify(default)
        data = request.get_json() or {}
        if not isinstance(data, dict):
            conn.close()
            return jsonify({"error": "profile must be a JSON object"}), 400
        existing = conn.execute("SELECT source_id FROM catalog_profiles WHERE source_id = ?", (source_id,)).fetchone()
        if not existing:
            conn.close()
            return jsonify({"error": "No profile found. Run Analyze Catalog Layout first."}), 400
        profile_json = json.dumps(data)
        conn.execute(
            "UPDATE catalog_profiles SET profile_json = ?, status = 'verified' WHERE source_id = ?",
            (profile_json, source_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/analyze', methods=['POST'])
def api_catalog_analyze(source_id):
    """Run catalog layout analysis (Gemini 2.5 Pro). Body: { sample_pages: [1, 5, 10] } or empty for auto-select."""
    try:
        data = request.get_json() or {}
        sample_pages = data.get("sample_pages")
        if sample_pages is not None and not isinstance(sample_pages, list):
            return jsonify({"error": "sample_pages must be an array of page numbers"}), 400
        if sample_pages is not None:
            sample_pages = [int(p) for p in sample_pages if isinstance(p, (int, float)) or (isinstance(p, str) and p.strip().isdigit())]
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        progress_log = []
        def progress_cb(msg):
            progress_log.append(msg)
        profile = run_catalog_analysis(conn, source_id, sample_pages or [], progress_callback=progress_cb)
        # Run validation: spatial extraction dry-run on each sample page for debug report
        row = conn.execute("SELECT sample_pages FROM catalog_profiles WHERE source_id=?", (source_id,)).fetchone()
        sample_pages_used = []
        if row and row["sample_pages"]:
            try:
                sample_pages_used = json.loads(row["sample_pages"])
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        validation_report = run_profile_validation(conn, source_id, profile, sample_pages_used)
        conn.close()
        scores = profile.get("confidence_scores") or {}
        summary = {
            "zone_detection": profile.get("zone_detection", {}).get("method", "unknown"),
            "catalog_number_patterns_count": len(profile.get("catalog_number_patterns") or []),
            "confidence_scores": scores,
            "low_confidence": [k for k, v in scores.items() if isinstance(v, (int, float)) and v < 7],
        }
        return jsonify({
            "ok": True,
            "profile": profile,
            "summary": summary,
            "progress": progress_log,
            "validation_report": validation_report,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/profile', methods=['GET', 'PUT'])
def api_catalog_profile(source_id):
    """Get or update catalog profile (page layout / image association). Stored inside config_json as catalog_profile."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            row = conn.execute("SELECT config_json FROM catalog_config WHERE source_id=?", (source_id,)).fetchone()
            conn.close()
            config = json.loads(row["config_json"]) if row and row["config_json"] else {}
            profile = config.get("catalog_profile")
            return jsonify(profile if isinstance(profile, dict) else {})
        data = request.get_json() or {}
        row = conn.execute("SELECT config_json FROM catalog_config WHERE source_id=?", (source_id,)).fetchone()
        config = json.loads(row["config_json"]) if row and row["config_json"] else {}
        if not isinstance(config, dict):
            config = {}
        config["catalog_profile"] = data
        conn.execute(
            "INSERT INTO catalog_config (source_id, config_json, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(source_id) DO UPDATE SET config_json=excluded.config_json, updated_at=datetime('now')",
            (source_id, json.dumps(config)),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/samples', methods=['GET', 'POST'])
def api_catalog_samples(source_id):
    """Get samples for a catalog, or add a new sample (user-provided example)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            rows = conn.execute(
                "SELECT id, page_number, sample_type, value_text, notes, created_at FROM catalog_samples WHERE source_id=? ORDER BY page_number, id",
                (source_id,),
            ).fetchall()
            conn.close()
            return jsonify([dict(r) for r in rows])
        data = request.get_json() or {}
        sample_type = (data.get("sample_type") or "").strip()
        value_text = (data.get("value_text") or "").strip()
        if not sample_type or not value_text:
            conn.close()
            return jsonify({"error": "sample_type and value_text required"}), 400
        if sample_type not in ("part_number", "product_name", "description", "secondary_description", "category", "other", "image_part_number"):
            conn.close()
            return jsonify({"error": "sample_type must be one of: part_number, product_name, description, secondary_description, category, other, image_part_number"}), 400
        conn.execute(
            "INSERT INTO catalog_samples (source_id, page_number, sample_type, value_text, notes) VALUES (?, ?, ?, ?, ?)",
            (source_id, data.get("page_number"), sample_type, value_text, (data.get("notes") or "").strip()),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Register more specific paths first so they match before the generic one
@app.route('/api/catalogs/<int:source_id>/build-product-listing/clear', methods=['POST'])
def api_build_product_listing_clear(source_id):
    """Clear all products (and product_images) for this catalog. Use before building by page when replacing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id=?)", (source_id,))
        conn.execute("DELETE FROM products WHERE source_id=?", (source_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "Products cleared"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/build-product-listing/page/<int:page_number>', methods=['POST'])
def api_build_product_listing_page(source_id, page_number):
    """Build product listing for a single page only. Writes to DB immediately. Use for progress-by-page to avoid timeouts."""
    print(f"[API] build-product-listing/page: source_id={source_id} page={page_number}")
    if not load_models_once():
        return jsonify({"created": 0, "page_number": page_number, "errors": ["Models not loaded"]}), 503
    try:
        t0 = time.time()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            field_guide = build_field_guide_for_source(conn, source_id)
        finally:
            conn.close()
        data = request.get_json() or {}
        replace_page = data.get("replace", True)
        result = build_product_listing_for_page(source_id, page_number, field_guide, replace_page=replace_page)
        elapsed = time.time() - t0
        print(f"[API] build-product-listing/page: source_id={source_id} page={page_number} completed in {elapsed:.1f}s created={result.get('created', 0)}")
        return jsonify(result)
    except Exception as e:
        print(f"[API] build-product-listing/page: source_id={source_id} page={page_number} error: {e}")
        return jsonify({"created": 0, "page_number": page_number, "errors": [str(e)]}), 500


@app.route('/api/catalogs/<int:source_id>/build-product-listing', methods=['POST'])
def api_build_product_listing(source_id):
    """Generate a product listing for this catalog using chunks + samples + config (LLM extraction per page). Writes to DB after each page. Replace existing products by default."""
    try:
        data = request.get_json() or {}
        replace = data.get("replace", True)
        result = build_product_listing_for_catalog(source_id, replace=replace)
        return jsonify(result)
    except Exception as e:
        return jsonify({"created": 0, "pages_processed": 0, "errors": [str(e)]}), 500


@app.route('/api/catalogs/<int:source_id>/assign-image', methods=['POST'])
def api_catalog_assign_image(source_id):
    """Assign a part number to an image: create/update product, link image to product, and add an image_part_number sample so the model learns image–part-number attribution."""
    try:
        data = request.get_json() or {}
        page_number = data.get("page_number")
        image_index = data.get("image_index")
        part_number = (data.get("part_number") or "").strip()
        if page_number is None or image_index is None or not part_number:
            return jsonify({"error": "page_number, image_index, and part_number required"}), 400
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        img_row = conn.execute(
            "SELECT id FROM images WHERE source_id=? AND page_number=? AND image_index=?",
            (source_id, page_number, image_index),
        ).fetchone()
        if not img_row:
            conn.close()
            return jsonify({"error": "Image not found"}), 404
        image_id = img_row["id"]
        product_row = conn.execute(
            "SELECT id FROM products WHERE source_id=? AND manufacturer_part_number=?",
            (source_id, part_number),
        ).fetchone()
        if product_row:
            product_id = product_row["id"]
            conn.execute(
                "UPDATE products SET product_name=?, description=?, secondary_description=?, category=?, updated_at=datetime('now') WHERE id=?",
                ((data.get("product_name") or "").strip() or None, (data.get("description") or "").strip() or None, (data.get("secondary_description") or "").strip() or None, (data.get("category") or "").strip() or None, product_id),
            )
        else:
            conn.execute(
                """INSERT INTO products (source_id, page_number, manufacturer_part_number, product_name, description, secondary_description, category, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (source_id, page_number, part_number, (data.get("product_name") or "").strip() or None, (data.get("description") or "").strip() or None, (data.get("secondary_description") or "").strip() or None, (data.get("category") or "").strip() or None),
            )
            product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        try:
            conn.execute("INSERT INTO product_images (product_id, image_id, display_order) VALUES (?, ?, 0)", (product_id, image_id))
        except sqlite3.IntegrityError:
            pass
        conn.execute(
            "INSERT INTO catalog_samples (source_id, page_number, sample_type, value_text, notes) VALUES (?, ?, 'image_part_number', ?, ?)",
            (source_id, page_number, part_number, f"image_index:{image_index}"),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "product_id": product_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Products and product–image assignment (structured exportable data) ---

def _product_row_to_dict(row, conn=None):
    """Turn a product row (sqlite3.Row) into a dict. If conn given, attach all linked images (no limit)."""
    d = dict(row)
    if conn is None:
        d.setdefault("images", [])
        return d
    img_rows = conn.execute(
        "SELECT pi.image_id, pi.display_order, i.source_id, i.page_number, i.image_index FROM product_images pi JOIN images i ON i.id = pi.image_id WHERE pi.product_id=? ORDER BY pi.display_order, pi.id",
        (d["id"],),
    ).fetchall()
    d["images"] = [
        {"image_id": r["image_id"], "display_order": r["display_order"], "source_id": r["source_id"], "page_number": r["page_number"], "image_index": r["image_index"], "url": f"/api/image/{r['source_id']}/{r['page_number']}/{r['image_index']}"}
        for r in img_rows
    ]
    return d


@app.route('/api/catalogs/<int:source_id>/products', methods=['GET', 'POST'])
def api_catalog_products(source_id):
    """List products for a catalog, or create a new product."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'GET':
            rows = conn.execute(
                "SELECT id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, created_at, updated_at FROM products WHERE source_id=? ORDER BY page_number, id",
                (source_id,),
            ).fetchall()
            out = [_product_row_to_dict(r, conn) for r in rows]
            conn.close()
            return jsonify(out)
        data = request.get_json() or {}
        mfr_part = (data.get("manufacturer_part_number") or "").strip()
        if not mfr_part:
            conn.close()
            return jsonify({"error": "manufacturer_part_number required"}), 400
        conn.execute(
            """INSERT INTO products (source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                source_id,
                data.get("page_number"),
                (data.get("manufacturer") or "").strip() or None,
                mfr_part,
                (data.get("product_name") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                (data.get("secondary_description") or "").strip() or None,
                (data.get("category") or "").strip() or None,
                (data.get("language") or "en").strip(),
                (data.get("verification_status") or "unverified").strip(),
                (data.get("raw_snippet") or "").strip() or None,
            ),
        )
        conn.commit()
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, created_at, updated_at FROM products WHERE id=?", (pid,)).fetchone()
        out = _product_row_to_dict(row, conn)
        conn.close()
        return jsonify(out), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/products/<int:product_id>', methods=['GET', 'PUT', 'DELETE'])
def api_product(product_id):
    """Get, update, or delete a single product."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if request.method == 'DELETE':
            conn.execute("DELETE FROM products WHERE id=?", (product_id,))
            conn.commit()
            conn.close()
            return jsonify({"ok": True})
        row = conn.execute(
            "SELECT id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, created_at, updated_at FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Product not found"}), 404
        if request.method == 'GET':
            out = _product_row_to_dict(row, conn)
            conn.close()
            return jsonify(out)
        data = request.get_json() or {}
        conn.execute(
            """UPDATE products SET page_number=?, manufacturer=?, manufacturer_part_number=?, product_name=?, description=?, secondary_description=?, category=?, language=?, verification_status=?, raw_snippet=?, updated_at=datetime('now')
               WHERE id=?""",
            (
                data.get("page_number") if "page_number" in data else row["page_number"],
                (data.get("manufacturer") or "").strip() if "manufacturer" in data else row["manufacturer"],
                (data.get("manufacturer_part_number") or "").strip() if "manufacturer_part_number" in data else row["manufacturer_part_number"],
                (data.get("product_name") or "").strip() if "product_name" in data else row["product_name"],
                (data.get("description") or "").strip() if "description" in data else row["description"],
                (data.get("secondary_description") or "").strip() if "secondary_description" in data else row["secondary_description"],
                (data.get("category") or "").strip() if "category" in data else row["category"],
                (data.get("language") or "en").strip() if "language" in data else row["language"],
                (data.get("verification_status") or "unverified").strip() if "verification_status" in data else row["verification_status"],
                (data.get("raw_snippet") or "").strip() if "raw_snippet" in data else row["raw_snippet"],
                product_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, raw_snippet, created_at, updated_at FROM products WHERE id=?", (product_id,)).fetchone()
        out = _product_row_to_dict(row, conn)
        conn.close()
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/products/<int:product_id>/images', methods=['GET', 'POST'])
def api_product_images(product_id):
    """List images linked to a product, or assign an image to the product."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        prod = conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
        if not prod:
            conn.close()
            return jsonify({"error": "Product not found"}), 404
        if request.method == 'GET':
            rows = conn.execute(
                "SELECT pi.id, pi.image_id, pi.display_order, i.source_id, i.page_number, i.image_index FROM product_images pi JOIN images i ON i.id = pi.image_id WHERE pi.product_id=? ORDER BY pi.display_order, pi.id",
                (product_id,),
            ).fetchall()
            conn.close()
            return jsonify([{"image_id": r["image_id"], "display_order": r["display_order"], "source_id": r["source_id"], "page_number": r["page_number"], "image_index": r["image_index"], "url": f"/api/image/{r['source_id']}/{r['page_number']}/{r['image_index']}"} for r in rows])
        data = request.get_json() or {}
        image_id = data.get("image_id")
        if not image_id and "source_id" in data and "page_number" in data and "image_index" in data:
            img_row = conn.execute(
                "SELECT id FROM images WHERE source_id=? AND page_number=? AND image_index=?",
                (data["source_id"], data["page_number"], data["image_index"]),
            ).fetchone()
            if not img_row:
                conn.close()
                return jsonify({"error": "Image not found"}), 404
            image_id = img_row["id"]
        if not image_id:
            conn.close()
            return jsonify({"error": "image_id or (source_id, page_number, image_index) required"}), 400
        display_order = data.get("display_order", 0)
        try:
            conn.execute("INSERT INTO product_images (product_id, image_id, display_order) VALUES (?, ?, ?)", (product_id, image_id, display_order))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
        return jsonify({"ok": True}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/products/<int:product_id>/images/<int:image_id>', methods=['DELETE'])
def api_product_image_delete(product_id, image_id):
    """Unlink an image from a product."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM product_images WHERE product_id=? AND image_id=?", (product_id, image_id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/catalogs/<int:source_id>/products/export', methods=['GET'])
def api_catalog_products_export(source_id):
    """Export products for a catalog as JSON or CSV. ?format=json|csv"""
    try:
        fmt = (request.args.get("format") or "json").lower()
        if fmt not in ("json", "csv"):
            return jsonify({"error": "format must be json or csv"}), 400
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        name_row = conn.execute("SELECT name FROM sources WHERE id=?", (source_id,)).fetchone()
        if not name_row:
            conn.close()
            return jsonify({"error": "Catalog not found"}), 404
        rows = conn.execute(
            "SELECT id, source_id, page_number, manufacturer, manufacturer_part_number, product_name, description, secondary_description, category, language, verification_status, created_at, updated_at FROM products WHERE source_id=? ORDER BY page_number, id",
            (source_id,),
        ).fetchall()
        products_export = []
        for r in rows:
            p = dict(r)
            img_rows = conn.execute(
                "SELECT i.source_id, i.page_number, i.image_index FROM product_images pi JOIN images i ON i.id = pi.image_id WHERE pi.product_id=? ORDER BY pi.display_order",
                (p["id"],),
            ).fetchall()
            p["image_refs"] = [f"/api/image/{row['source_id']}/{row['page_number']}/{row['image_index']}" for row in img_rows]
            products_export.append(p)
        conn.close()
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            fieldnames = ["manufacturer_part_number", "product_name", "description", "secondary_description", "category", "page_number", "manufacturer", "language", "verification_status", "image_refs"]
            w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for p in products_export:
                row = {k: p.get(k) for k in fieldnames}
                row["image_refs"] = "; ".join(p.get("image_refs") or [])
                w.writerow(row)
            from flask import Response
            return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=catalog_{source_id}_products.csv"})
        return jsonify({"catalog_id": source_id, "catalog_name": name_row["name"], "products": products_export})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/clear-cache', methods=['POST'])
def api_clear_cache():
    """Clear the response cache so the next chat request does fresh retrieval and LLM generation."""
    cache_file = Path(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'response_cache.pkl'))
    try:
        if cache_file.exists():
            cache_file.unlink()
            return jsonify({"ok": True, "message": "Response cache cleared."})
        return jsonify({"ok": True, "message": "No cache file to clear."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check with GPU monitoring"""
    gpu_info = get_gpu_memory_info()
    system_info = {
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': psutil.virtual_memory().percent,
        'memory_available_gb': round(psutil.virtual_memory().available / 1024**3, 2)
    }
    
    return jsonify({
        'status': 'healthy',
        'models_loaded': _models_loaded,
        'cache_size': len(_response_cache),
        'device': str(_device) if _device else 'unknown',
        'gpu_info': gpu_info,
        'system_info': system_info,
        'performance_stats': _performance_stats,
        'uptime_seconds': (datetime.now() - _performance_stats['start_time']).total_seconds()
    })

@app.route('/chat', methods=['POST'])
def chat():
    """Optimized chat endpoint with preloaded models"""
    start_time = time.time()
    _performance_stats['total_requests'] += 1
    
    if not load_models_once():
        return jsonify({'error': 'Models not loaded'}), 500
    
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        
        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        # Create hash for caching
        question_hash = hashlib.md5(question.encode()).hexdigest()
        
        # Check cache first (only use if cached answer was from current knowledge base)
        cached_response = get_cached_response(question_hash)
        if cached_response:
            response_time = int((time.time() - start_time) * 1000)
            return jsonify({
                'answer': cached_response['answer'],
                'sources': cached_response['sources'],
                'image_refs': cached_response.get('image_refs', []),
                'product_cards': cached_response.get('product_cards', []),
                'responseTime': response_time,
                'cached': True,
                'gpu_utilization': get_gpu_memory_info()
            })
        
        # No content: prompt user to run rebuild
        if not _chunks_data or _faiss_index is None:
            response_time = int((time.time() - start_time) * 1000)
            return jsonify({
                'answer': 'No content loaded. Place PDFs in scripts/source_files/ and run: python scripts/rebuild.py Then restart the chat server to use the new data.',
                'sources': [],
                'image_refs': [],
                'product_cards': [],
                'responseTime': response_time,
                'cached': False,
                'gpu_utilization': get_gpu_memory_info()
            })
        
        print(f"Processing question: \"{question[:50]}{'...' if len(question) > 50 else ''}\"")
        
        # Use catalog samples to guide search: append example terms so retrieval favors chunks with similar part numbers/names
        search_hint = get_sample_terms_for_search()
        search_query = (question + search_hint) if search_hint else question
        
        # Generate embeddings (query + sample hint so FAISS finds more relevant catalog content)
        question_embedding = _model_embed.encode([search_query], convert_to_numpy=True)
        
        # Search for similar chunks. Fewer context chunks = tighter, more focused answers (less noise).
        k = 10
        max_context_chunks = 5
        distances, indices = _faiss_index.search(question_embedding, k)
        
        # Build context and source citations in retrieval order (most relevant first). Only list sources for chunks actually used in context.
        context_chunks = []
        sources_ordered = []  # list in retrieval order so UI shows most relevant first
        source_page_pairs = []  # (source_id, page_number) for image lookup
        
        for idx in indices[0]:
            if idx < len(_chunks_data):
                chunk = _chunks_data[idx]
                if isinstance(chunk, dict):
                    # Use full chunk (up to 1200 chars) so part numbers and product details are not cut off
                    chunk_text = (chunk["text"] or "")[:1200]
                    source_citation = chunk["source"]
                    if chunk.get('page_number'):
                        source_citation += f" (Page {chunk['page_number']})"
                    elif chunk.get('type') == 'product':
                        source_citation += f" (Product ID: {chunk.get('row_index', 'N/A')})"
                    context_chunks.append(chunk_text)
                    sources_ordered.append(source_citation)
                    if chunk.get("source_id") is not None and chunk.get("page_number") is not None:
                        source_page_pairs.append((chunk["source_id"], chunk["page_number"]))
        
        # Product-by-name: when the user asks by product name (e.g. "Jacobson Vessel knife"), search products
        # and prepend chunks from those products' pages so the LLM sees the right context.
        products_by_name = get_products_matching_name_query(question, max_products=5)
        if products_by_name:
            print(f"  [Retrieval] Product-by-name: found {len(products_by_name)} product(s), prepending chunks from their pages.")
            seen_text = {t for t in context_chunks}
            for p in products_by_name:
                sid = p.get("source_id")
                pno = p.get("page_number")
                if sid is None or pno is None:
                    continue
                page_chunks = get_chunks_for_page(sid, pno, max_chunks=5)
                for kw_chunk in page_chunks:
                    txt = kw_chunk.get("text", "")
                    if txt and txt not in seen_text:
                        seen_text.add(txt)
                        cit = kw_chunk.get("source", "")
                        if kw_chunk.get("page_number") is not None:
                            cit += f" (Page {kw_chunk['page_number']})"
                        context_chunks.insert(0, txt)
                        sources_ordered.insert(0, cit)
                        if kw_chunk.get("source_id") is not None and kw_chunk.get("page_number") is not None:
                            source_page_pairs.insert(0, (kw_chunk["source_id"], kw_chunk["page_number"]))

        # Hybrid retrieval: if the question contains part-number-like tokens, add chunks that contain them (keyword match)
        part_candidates = extract_part_number_candidates(question)
        keyword_source_ids = []
        seen_text = {t for t in context_chunks}
        for part in part_candidates:
            kw_chunks = get_chunks_containing_text(part, max_chunks=2)
            if kw_chunks:
                print(f"  [Retrieval] Part number '{part}': found {len(kw_chunks)} chunk(s) via keyword search.")
            else:
                print(f"  [Retrieval] Part number '{part}': NO chunks in database contain this. Run rebuild? Or run: python scripts/check_part_in_db.py {part}")
            for kw_chunk in kw_chunks:
                txt = kw_chunk.get("text", "")
                if txt and txt not in seen_text:
                    seen_text.add(txt)
                    cit = kw_chunk.get("source", "")
                    if kw_chunk.get("page_number"):
                        cit += f" (Page {kw_chunk['page_number']})"
                    context_chunks.insert(0, txt)
                    sources_ordered.insert(0, cit)
                    if kw_chunk.get("source_id") is not None:
                        keyword_source_ids.append(kw_chunk["source_id"])
                        if kw_chunk.get("page_number") is not None:
                            source_page_pairs.insert(0, (kw_chunk["source_id"], kw_chunk["page_number"]))

        # Query-words chunk search: find chunks that contain the question's key words (e.g. "horsely dura separator").
        # Does not depend on the product table; works even when the product isn't in the table. Prepend last so they rank first.
        query_word_chunks = get_chunks_containing_query_words(question, max_chunks=5)
        if query_word_chunks:
            print(f"  [Retrieval] Query-words: found {len(query_word_chunks)} chunk(s) containing the question terms.")
            seen_text = {t for t in context_chunks}
            for kw_chunk in reversed(query_word_chunks):  # prepend in stable order
                txt = kw_chunk.get("text", "")
                if txt and txt not in seen_text:
                    seen_text.add(txt)
                    cit = kw_chunk.get("source", "")
                    if kw_chunk.get("page_number") is not None:
                        cit += f" (Page {kw_chunk['page_number']})"
                    context_chunks.insert(0, txt)
                    sources_ordered.insert(0, cit)
                    if kw_chunk.get("source_id") is not None and kw_chunk.get("page_number") is not None:
                        source_page_pairs.insert(0, (kw_chunk["source_id"], kw_chunk["page_number"]))

        # Only use first max_context_chunks for the answer; only those appear in sources (so UI matches what the model saw)
        context_chunks_used = context_chunks[:max_context_chunks]
        sources = sources_ordered[:max_context_chunks]
        
        image_refs = get_image_refs_for_chunks(source_page_pairs[:max_context_chunks]) if source_page_pairs else []

        # Product–image association: if the question mentions a part number, look up linked images in products/product_images
        product_image_refs, product_image_context = get_product_image_refs_for_question(question)
        if product_image_refs:
            image_refs = list(product_image_refs) + [r for r in image_refs if r not in product_image_refs]

        # Product table context: when the question mentions a known part number, inject product row so the model can answer even if no chunk has it
        product_context = get_product_context_for_question(question)

        # Load catalog samples for retrieved sources (FAISS chunks + keyword chunks)
        source_ids = []
        for i in indices[0][:max_context_chunks]:
            if i < len(_chunks_data):
                c = _chunks_data[i]
                if isinstance(c, dict) and c.get("source_id") is not None:
                    source_ids.append(c["source_id"])
        source_ids = list(dict.fromkeys(source_ids + keyword_source_ids))
        samples, config_by_source = get_catalog_samples_for_sources(source_ids)
        field_guide = format_samples_as_field_guide(samples, config_by_source) if samples else ""

        context = "RELEVANT EXCERPTS FROM KNOWLEDGE BASE:\n\n" + "\n\n".join(context_chunks_used) if context_chunks_used else ""
        if product_context:
            context = product_context + "\n\n" + context
        if product_image_context:
            context = product_image_context + "\n\n" + context

        if part_candidates and len(context.strip()) < 200:
            print(f"  [Retrieval] WARNING: Part-number question but context is very short ({len(context)} chars). Chunks may not contain the part.")
        elif part_candidates:
            print(f"  [Retrieval] Context length: {len(context)} chars, chunks used: {len(context_chunks_used)}")

        # Generate response using preloaded model (with optional field-association guide from samples)
        answer = generate_response_optimized(question, context, field_guide=field_guide or None)
        if product_image_refs and ("image" in question.lower() or "picture" in question.lower() or "photo" in question.lower()):
            answer = "The correct image(s) for that product are linked below. " + answer
        _performance_stats['gpu_requests'] += 1
        
        # Calculate response time
        response_time = int((time.time() - start_time) * 1000)
        
        # Update performance stats
        if _performance_stats['total_requests'] > 1:
            current_avg = _performance_stats['avg_response_time']
            _performance_stats['avg_response_time'] = (current_avg + response_time) / 2
        else:
            _performance_stats['avg_response_time'] = response_time
        
        # Product cards for chat UI: only from direct question match (part number or product name).
        # Do NOT fall back to image_refs — that shows unrelated products from FAISS pages.
        product_cards = get_product_cards_for_question(question)

        # Prepare response (include content signature so cache is only used for same knowledge base)
        response_data = {
            'answer': answer,
            'sources': list(sources),
            'image_refs': image_refs,
            'product_cards': product_cards,
            'responseTime': response_time,
            'cached': False,
            'content_signature': _content_signature,
            'gpu_utilization': get_gpu_memory_info()
        }
        
        # Cache the response
        cache_response(question_hash, response_data)
        
        print(f"Response generated in {response_time}ms (cached: false)")
        # Don't send content_signature to frontend (used only for cache validation)
        out = {k: v for k, v in response_data.items() if k != 'content_signature'}
        # Optional: include last Gemini error in response for debugging (set RETURN_CHAT_ERROR=1 in .env)
        if RETURN_CHAT_ERROR and answer == "I'm sorry, but I'm unable to process your question at the moment." and _last_chat_error:
            out["debug_error"] = _last_chat_error
        return jsonify(out)
        
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Instrument Oracle...")
    print("=" * 60)
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY is not set. The app uses Google Gemini 2.0 Flash for answers.")
        print("   Set your API key in the project .env file:")
        print("   1. Copy .env.example to .env (in the project root)")
        print("   2. Edit .env and set GEMINI_API_KEY=your_key")
        print("   Get a key at: https://aistudio.google.com/apikey")
        print("=" * 60)
        sys.exit(1)
    print("🔗 LLM: Google Gemini 2.0 Flash (API)")
    print("   • Embeddings + FAISS run locally (GPU optional)")
    print("   • Chat and product extraction use Gemini")
    print("=" * 60)

    if load_models_once():
        print("✅ All models loaded successfully!")
        print("🌐 Starting Flask server on port 5001...")
        print("📊 Monitor performance at: http://localhost:5001/health")
        print("⚡ Response times: typically 1–5 s (Gemini), <100 ms (cached)")
        app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
    else:
        print("❌ Failed to load models")
        sys.exit(1) 
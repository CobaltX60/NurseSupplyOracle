#!/usr/bin/env python3
"""
Optimized Hugging Face GPU-accelerated chat server for Nurse Supply Oracle
Features: Model preloading, in-process inference, and aggressive optimization
"""

import json
import os
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import pickle
import hashlib
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import time
import torch
import psutil
from datetime import datetime
import sys
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import re

app = Flask(__name__)
CORS(app)

# Global variables
_model_embed = None
_chunks_data = None
_chunk_sources = None
_faiss_index = None
_response_cache = {}
_models_loaded = False
_loading_lock = threading.Lock()
_device = None
_llm_model = None
_llm_tokenizer = None
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
    """Clean the response to extract only the actual answer with proper sentence-based truncation"""
    # Remove any prompt artifacts
    response = re.sub(r'<s>.*?\[/INST\]', '', response, flags=re.DOTALL)
    response = re.sub(r'Context:.*?Question:.*?Answer:', '', response, flags=re.DOTALL)
    response = re.sub(r'\[INST\].*?\[/INST\]', '', response, flags=re.DOTALL)
    
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

def generate_response_optimized(question: str, context: str, max_tokens: int = 200) -> str:
    """Generate response using preloaded model - optimized for speed"""
    try:
        # Format prompt for Mistral instruction model
        full_prompt = f"""<s>[INST] Based on the clinical background and available products below, provide a practical answer that combines nursing knowledge with specific product recommendations when relevant. Focus on being helpful and actionable.

Context: {context}

Question: {question}

Answer: [/INST]"""
        
        # Tokenize and generate
        inputs = _llm_tokenizer(full_prompt, return_tensors="pt").to(_device)
        
        with torch.no_grad():  # Disable gradient computation for inference
            out = _llm_model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,  # Deterministic for speed
                temperature=0.1,
                top_p=0.9,
                repetition_penalty=1.1,
                pad_token_id=_llm_tokenizer.eos_token_id,
                eos_token_id=_llm_tokenizer.eos_token_id,
                early_stopping=True,
                use_cache=True  # Enable KV cache for speed
            )
        
        raw_response = _llm_tokenizer.decode(out[0], skip_special_tokens=True)
        cleaned_response = clean_response(raw_response, question)
        
        # Fallback for very short responses
        if len(cleaned_response) < 10:
            return "Based on the available information, I cannot provide a complete answer at this time."
        
        return cleaned_response
        
    except Exception as e:
        print(f"Error generating response: {e}")
        return "I'm sorry, but I'm unable to process your question at the moment."

def load_models_once():
    """Load all models with aggressive optimization"""
    global _model_embed, _chunks_data, _chunk_sources, _faiss_index, _models_loaded, _device
    global _llm_model, _llm_tokenizer
    
    with _loading_lock:
        if _models_loaded:
            return True
        
        print("🚀 Loading models with aggressive optimization...")
        
        # Set up device
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
        
        # Load chunks and FAISS index
        print("📥 Loading chunks and FAISS index...")
        try:
            # Try to load combined chunks with page numbers first, then fallback to others
            chunks_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chunks_combined_with_pages.json')
            faiss_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'faiss_index_with_pages.idx')
            
            if not os.path.exists(chunks_path):
                # Fallback to original combined chunks
                chunks_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chunks_combined.json')
                faiss_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'faiss_index_all_pymupdf.idx')
                print("⚠️ Combined chunks with pages not found, using original combined chunks")
                
                if not os.path.exists(chunks_path):
                    # Final fallback to original chunks
                    chunks_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chunks_all_pymupdf.json')
                    print("⚠️ Combined chunks not found, using original chunks")
            
            # Try multiple encodings to handle special characters
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
            _chunks_data = None
            
            for encoding in encodings:
                try:
                    with open(chunks_path, 'r', encoding=encoding) as f:
                        _chunks_data = json.load(f)
                    print(f"✅ Successfully loaded chunks with {encoding} encoding")
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    print(f"⚠️ Error with {encoding} encoding: {e}")
                    continue
            
            if _chunks_data is None:
                raise Exception("Failed to load chunks with any encoding")
            _faiss_index = faiss.read_index(faiss_path)
            
            # Extract sources
            _chunk_sources = set()
            product_count = 0
            textbook_count = 0
            
            for chunk in _chunks_data:
                if isinstance(chunk, dict):
                    if 'source' in chunk:
                        _chunk_sources.add(chunk['source'])
                        if chunk.get('type') == 'product':
                            product_count += 1
                        else:
                            textbook_count += 1
                    else:
                        _chunk_sources.add("Primary Nursing Textbook")
                        textbook_count += 1
                else:
                    _chunk_sources.add("Primary Nursing Textbook")
                    textbook_count += 1
            
            print(f"✅ Loaded {len(_chunks_data)} total chunks from {len(_chunk_sources)} sources")
            print(f"📚 Textbook chunks: {textbook_count}")
            print(f"🛍️ Product chunks: {product_count}")
        except Exception as e:
            print(f"❌ Error loading chunks: {e}")
            return False
        
        # Load LLM model with aggressive optimization
        print("📥 Loading Mistral-7B model with aggressive optimization...")
        try:
            MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
            
            # Ultra-aggressive 4-bit quantization for maximum speed
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                llm_int8_threshold=6.0,
                llm_int8_has_fp16_weight=False
            )
            
            # Load tokenizer
            hf_token = os.environ.get('HF_TOKEN', 'your_hf_token_here')
            _llm_tokenizer = AutoTokenizer.from_pretrained(MODEL, token=hf_token, use_fast=False)
            
            # Load model with aggressive optimization
            _llm_model = AutoModelForCausalLM.from_pretrained(
                MODEL,
                quantization_config=bnb_config,
                device_map="auto",
                torch_dtype=torch.float16,
                token=hf_token,
                low_cpu_mem_usage=True
            )
            
            # Set model to evaluation mode
            _llm_model.eval()
            
            # Show GPU memory after LLM model
            if torch.cuda.is_available():
                gpu_info = get_gpu_memory_info()
                if gpu_info:
                    print(f"📊 GPU Memory after LLM: {gpu_info['allocated_gb']}GB allocated ({gpu_info['utilization_percent']}% utilization)")
            
            print("✅ Mistral-7B model loaded successfully!")
            
        except Exception as e:
            print(f"❌ Error loading LLM model: {e}")
            return False
        
        _models_loaded = True
        print("✅ All models loaded successfully!")
        return True

def get_cached_response(question_hash):
    """Get cached response with enhanced error handling"""
    cache_file = Path(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'response_cache.pkl'))
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                cache = pickle.load(f)
                if question_hash in cache:
                    _performance_stats['cached_requests'] += 1
                    return cache[question_hash]
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
        
        # Check cache first
        cached_response = get_cached_response(question_hash)
        if cached_response:
            response_time = int((time.time() - start_time) * 1000)
            return jsonify({
                'answer': cached_response['answer'],
                'sources': cached_response['sources'],
                'responseTime': response_time,
                'cached': True,
                'gpu_utilization': get_gpu_memory_info()
            })
        
        print(f"Processing question: \"{question[:50]}{'...' if len(question) > 50 else ''}\"")
        
        # Generate embeddings
        question_embedding = _model_embed.encode([question], convert_to_numpy=True)
        
        # Search for similar chunks - optimized for speed
        k = 6  # Balanced for product and textbook information
        distances, indices = _faiss_index.search(question_embedding, k)
        
        # Get relevant chunks, separating textbook and product information
        textbook_chunks = []
        product_chunks = []
        sources = set()
        
        for idx in indices[0]:
            if idx < len(_chunks_data):
                chunk = _chunks_data[idx]
                if isinstance(chunk, dict):
                    chunk_text = chunk["text"][:400]  # Reduced for speed
                    
                    # Create source citation with page number if available
                    source_citation = chunk["source"]
                    if chunk.get('page_number'):
                        source_citation += f" (Page {chunk['page_number']})"
                    elif chunk.get('type') == 'product':
                        source_citation += f" (Product ID: {chunk.get('row_index', 'N/A')})"
                    
                    sources.add(source_citation)
                    
                    # Separate product chunks from textbook chunks
                    if chunk.get('type') == 'product':
                        product_chunks.append(chunk_text)
                    else:
                        textbook_chunks.append(chunk_text)
                else:
                    chunk_text = chunk[:400]
                    textbook_chunks.append(chunk_text)
                    sources.add("Primary Nursing Textbook")
        
        # Create context with better product integration
        context_parts = []
        
        # Always include some textbook context for clinical knowledge
        if textbook_chunks:
            context_parts.append("CLINICAL BACKGROUND:\n" + "\n".join(textbook_chunks[:2]))
        
        # Prioritize product information when available
        if product_chunks:
            context_parts.append("SPECIFIC PRODUCTS AVAILABLE:\n" + "\n".join(product_chunks[:3]))
        elif "product" in question.lower() or "supply" in question.lower() or "item" in question.lower():
            # If asking about products but none found, mention this
            context_parts.append("PRODUCT INFORMATION: No specific products found in search results.")
        
        context = "\n\n".join(context_parts)
        
        # Generate response using preloaded model
        answer = generate_response_optimized(question, context)
        _performance_stats['gpu_requests'] += 1
        
        # Calculate response time
        response_time = int((time.time() - start_time) * 1000)
        
        # Update performance stats
        if _performance_stats['total_requests'] > 1:
            current_avg = _performance_stats['avg_response_time']
            _performance_stats['avg_response_time'] = (current_avg + response_time) / 2
        else:
            _performance_stats['avg_response_time'] = response_time
        
        # Prepare response
        response_data = {
            'answer': answer,
            'sources': list(sources),
            'responseTime': response_time,
            'cached': False,
            'gpu_utilization': get_gpu_memory_info()
        }
        
        # Cache the response
        cache_response(question_hash, response_data)
        
        print(f"Response generated in {response_time}ms (cached: false)")
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Nurse Supply Oracle (Optimized Version)...")
    print("=" * 60)
    print("🔥 Key Optimizations:")
    print("   • Model preloading at startup")
    print("   • In-process inference (no subprocess)")
    print("   • Aggressive 4-bit quantization")
    print("   • Reduced context length")
    print("   • Optimized token limits")
    print("   • GPU memory optimization")
    print("=" * 60)
    
    # Load models at startup
    if load_models_once():
        print("✅ All models loaded successfully!")
        print("🌐 Starting Flask server on port 5001...")
        print("📊 Monitor performance at: http://localhost:5001/health")
        print("⚡ Expected response times: 1-3 seconds (first), <100ms (cached)")
        
        app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
    else:
        print("❌ Failed to load models")
        sys.exit(1) 
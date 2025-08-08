#!/usr/bin/env python3
"""
Hugging Face GPU-accelerated chat server for Nurse Supply Oracle
Features GPU acceleration with 4-bit quantization for fast inference
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
import subprocess
import sys

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
_performance_stats = {
    'total_requests': 0,
    'cached_requests': 0,
    'gpu_requests': 0,
    'avg_response_time': 0,
    'start_time': datetime.now()
}

# Paths for Hugging Face script (use system Python to avoid dependency issues)
PY = "python"  # Use system Python instead of venv Python
SCRIPT = os.path.join(os.path.dirname(__file__), "chat_hf.py")

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

def load_models_once():
    """Load models with GPU optimization"""
    global _model_embed, _chunks_data, _chunk_sources, _faiss_index, _models_loaded, _device
    
    with _loading_lock:
        if _models_loaded:
            return True
        
        print("🚀 Loading models with Hugging Face GPU optimization...")
        
        # Set up device
        if torch.cuda.is_available():
            _device = torch.device('cuda:0')
            print(f"✅ Using GPU: {torch.cuda.get_device_name(0)}")
            
            # Show initial GPU memory
            gpu_info = get_gpu_memory_info()
            if gpu_info:
                print(f"📊 GPU Memory: {gpu_info['total_gb']}GB total")
        else:
            _device = torch.device('cpu')
            print("⚠️ CUDA not available, using CPU")
        
        # Load embedding model
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
            # Get the correct path to chunks_all_pymupdf.json (in parent directory)
            chunks_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chunks_all_pymupdf.json')
            faiss_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'faiss_index_all_pymupdf.idx')
            
            _chunks_data = json.load(open(chunks_path))
            _faiss_index = faiss.read_index(faiss_path)
            
            # Extract sources
            _chunk_sources = set()
            for chunk in _chunks_data:
                if isinstance(chunk, dict) and 'source' in chunk:
                    _chunk_sources.add(chunk['source'])
                else:
                    _chunk_sources.add("Primary Nursing Textbook")
            
            print(f"✅ Loaded {len(_chunks_data)} chunks from {len(_chunk_sources)} sources")
        except Exception as e:
            print(f"❌ Error loading chunks: {e}")
            return False
        
        print("📥 Hugging Face model will be loaded on first request...")
        
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

def call_huggingface_model(question, context):
    """Call the working chat_hf.py script directly"""
    try:
        # Prepare the full prompt with context - optimized for concise responses
        full_prompt = f"""<s>[INST] Based on the nursing textbook information below, provide a brief, direct answer in 1-2 sentences. Focus only on the specific question asked.

Context: {context}

Question: {question}

Answer: [/INST]"""
        
        # Prepare payload
        payload = json.dumps({"question": full_prompt})
        
        # Call the working chat_hf.py script with proper environment
        env = os.environ.copy()
        env['HF_TOKEN'] = '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'
        
        # ——— DEBUG LOGGING START ———
        print(f"🔍 DEBUG: Launching chat_hf.py with payload: {payload[:200]}...")
        print(f"🔍 DEBUG: Using python exe: {PY}")
        print(f"🔍 DEBUG: Script path: {SCRIPT}")
        print(f"🔍 DEBUG: Subprocess env PYTHONPATH: {env.get('PYTHONPATH', 'Not set')}")
        print(f"🔍 DEBUG: Subprocess env HF_TOKEN: {env.get('HF_TOKEN', 'Not set')}")
        
        proc = subprocess.run(
            [PY, SCRIPT],
            input=payload,
            text=True,
            capture_output=True,
            env=env
        )
        
        print(f"🔍 DEBUG: Subprocess exit code: {proc.returncode}")
        print(f"🔍 DEBUG: Subprocess stdout: {proc.stdout[:500]}...")
        print(f"🔍 DEBUG: Subprocess stderr: {proc.stderr[:500]}...")
        
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
        # ——— DEBUG LOGGING END ———
        
        # Parse response
        response_data = json.loads(proc.stdout)
        return response_data.get("answer", "No response generated")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ HF script error: {e.stderr}")
        return "I'm sorry, but I'm unable to process your question at the moment due to a technical issue."
    except Exception as e:
        print(f"❌ Error calling HF model: {e}")
        return "I'm sorry, but I'm unable to process your question at the moment due to a technical issue."

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
    """Enhanced chat endpoint with Hugging Face GPU optimization"""
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
        
        # Search for similar chunks - optimized for precision
        k = 3  # Retrieve top 3 most relevant chunks for better context coverage
        distances, indices = _faiss_index.search(question_embedding, k)
        
        # Get relevant chunks
        relevant_chunks = []
        sources = set()
        
        for idx in indices[0]:
            if idx < len(_chunks_data):
                chunk = _chunks_data[idx]
                if isinstance(chunk, dict):
                    chunk_text = chunk["text"][:800]  # Reduced limit for more focused context
                    relevant_chunks.append(chunk_text)
                    sources.add(chunk["source"])
                else:
                    chunk_text = chunk[:800]
                    relevant_chunks.append(chunk_text)
                    sources.add("Primary Nursing Textbook")
        
        # Create context
        context = "\n\n".join(relevant_chunks)
        
        # Call Hugging Face model
        answer = call_huggingface_model(question, context)
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
    print("🚀 Starting Nurse Supply Oracle (Hugging Face GPU Optimized)...")
    print("=" * 60)
    
    # Load models
    if load_models_once():
        print("✅ Models loaded successfully!")
        print("🌐 Starting Flask server on port 5001...")
        print("📊 Monitor GPU usage at: http://localhost:5001/health")
        
        app.run(host='0.0.0.0', port=5001, debug=False)
    else:
        print("❌ Failed to load models")
        sys.exit(1) 
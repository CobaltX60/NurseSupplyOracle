# Instrument Oracle

An AI-powered assistant that **data mines PDF and other source files** for **surgical instrumentation** (product names, descriptions, part numbers, characteristics, images), builds a searchable library, and answers questions using a **local Qwen2.5-7B** model. Long-term storage uses **SQLite**; responses can be **structured** (answer + sources + instrument matches). See [documents/PROJECT_OVERVIEW.md](documents/PROJECT_OVERVIEW.md) and [documents/IMPLEMENTATION_PLAN.md](documents/IMPLEMENTATION_PLAN.md) for the full plan.

## 🎯 Features

- **AI-Powered Q&A**: Get instant answers about instruments and products using Qwen2.5-7B (8-bit)
- **Comprehensive Knowledge Base**: Chunks from your documents and product data
- **GPU Acceleration**: Optimized for NVIDIA GPUs with CUDA support
- **Smart Caching**: Fast responses for repeated questions
- **Source Attribution**: See which source provided each answer
- **Modern Web Interface**: Clean, responsive Next.js frontend

## 📁 Documentation

Detailed guides and reference docs live in the **`documents/`** folder. Use them to enhance the solution and as context for LLMs working on this project:

- **[documents/README.md](documents/README.md)** — Index of all documentation
- **Project vision & plan** — [documents/PROJECT_OVERVIEW.md](documents/PROJECT_OVERVIEW.md), [documents/CURRENT_BUILD.md](documents/CURRENT_BUILD.md), [documents/IMPLEMENTATION_PLAN.md](documents/IMPLEMENTATION_PLAN.md)
- **PDF paths & PyMuPDF** — [documents/PDF_PATH_UPDATES.md](documents/PDF_PATH_UPDATES.md)
- **Performance & GPU** — [documents/PERFORMANCE_OPTIMIZATIONS.md](documents/PERFORMANCE_OPTIMIZATIONS.md), [documents/README-GPU.md](documents/README-GPU.md)
- **Product integration** — [documents/PRODUCT_INTEGRATION.md](documents/PRODUCT_INTEGRATION.md)

## 🏗️ Architecture

### Frontend
- **Next.js 15.4.5** with React 19
- **Tailwind CSS** for styling
- **TypeScript** for type safety
- **Real-time processing** with loading states

### Backend
- **Flask** server with GPU optimization
- **Qwen2.5-7B-Instruct** (8-bit quantized) for AI responses
- **FAISS** vector search for semantic similarity
- **PyMuPDF** for robust PDF text extraction
- **Sentence Transformers** for embeddings

### Data Pipeline
- **Text Processing**: Semantic chunking with 1,200 token chunks
- **Vector Search**: FAISS index for fast similarity matching
- **Response Generation**: Context-aware AI responses
- **Caching**: Intelligent response caching system

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**
- **Node.js 18+**
- **NVIDIA GPU** with CUDA support (8GB+ VRAM recommended)
- **Git**

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/InstrumentOracle.git
   cd InstrumentOracle
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements-gpu.txt
   ```

3. **Install Node.js dependencies**
   ```bash
   npm install
   ```

4. **Download AI Model**
   ```bash
   python scripts/download_model.py
   ```

5. **Add source PDFs** into `scripts/source_files/`, then **rebuild** (only when you want to refresh content):
   ```bash
   python scripts/rebuild.py
   ```
   The app does not auto-rebuild on startup; it uses existing data in `data/instrument_oracle.db` and `data/faiss_index.idx`.

### Running the Application

1. **Start the Flask backend**
   ```bash
   cd scripts
   python chat_server.py
   ```

2. **Start the Next.js frontend** (in a new terminal)
   ```bash
   npm run dev
   ```

3. **Access the application**
   - Frontend: http://localhost:3001
   - Backend API: http://localhost:5001
   - Health Check: http://localhost:5001/health

## 📚 Knowledge Base

The system uses your documents and product data:

- Add PDFs and documents to process with the preparation scripts
- Add PDFs to `scripts/source_files/` and run `python scripts/rebuild.py` to refresh the library
- FAISS index enables fast semantic search over your knowledge chunks

## 🔧 Configuration

### GPU Requirements
- **Minimum**: 6GB VRAM (with 8-bit quantization for Qwen2.5-7B)
- **Recommended**: 8GB+ VRAM for optimal performance
- **CPU Fallback**: Available but significantly slower

### Application-level config (recommended)

The app reads a **`.env`** file from the project root so you can keep API keys and options in the build instead of setting system environment variables.

1. Copy the example file:  
   `cp .env.example .env` (or on Windows: `copy .env.example .env`)
2. Edit **`.env`** and set your keys:
   - **GEMINI_API_KEY** — for Google Gemini 2.0 Flash (recommended; no local GPU needed for the LLM). Get a key at [Google AI Studio](https://aistudio.google.com/apikey).
   - **GEMINI_MODEL** — optional; default is `gemini-2.0-flash`.
3. `.env` is gitignored and will not be committed.

If you prefer, you can still set these in the **environment** (e.g. `export GEMINI_API_KEY=...`); the app uses either `.env` or the shell.

### Environment variables (alternative)

```bash
# Option A: Gemini (set in .env or here)
export GEMINI_API_KEY="your_gemini_api_key"
export GEMINI_MODEL="gemini-2.0-flash"

# Option B: Local LLM — Hugging Face token if required
export HF_TOKEN="your_actual_token_here"

# Optional: CUDA device
export CUDA_VISIBLE_DEVICES=0
```

## 📊 Performance

- **First Response**: ~40 seconds (model loading)
- **Cached Responses**: <100ms
- **GPU Memory Usage**: ~0.09GB allocated
- **Model Size**: ~4GB (4-bit quantized)

## 🛠️ Development

### Project Structure
```
InstrumentOracle/
├── src/                    # Next.js frontend
│   ├── app/               # App router components
│   └── globals.css        # Global styles
├── scripts/               # Python backend
│   ├── chat_server.py     # Flask server
│   ├── source_files/      # Put PDFs here; rebuild.py reads from here
│   ├── rebuild.py         # Rebuild content (run when prompted)
│   └── ...
├── documents/             # Markdown docs (LLM context & enhancement guides)
├── data/                  # SQLite DB + FAISS index (created by rebuild.py)
├── public/                # Static assets
├── requirements-gpu.txt   # Python dependencies
└── package.json          # Node.js dependencies
```

### Key Scripts
- `scripts/chat_server.py`: Main Flask server
- `scripts/rebuild.py`: Ingest PDFs from `scripts/source_files/` into SQLite + FAISS
- `scripts/check_cuda.py`: GPU compatibility check
- `scripts/process_excel_data.py`: Process product/Excel data

## 🔍 API Endpoints

### POST `/api/chat`
Send questions and receive AI-powered answers.

**Request:**
```json
{
  "question": "What instruments do you have for X?"
}
```

**Response:**
```json
{
  "answer": "...",
  "sources": ["Source Name"],
  "responseTime": 38816,
  "cached": false,
  "gpu_utilization": {
    "allocated_gb": 0.09,
    "reserved_gb": 0.1,
    "total_gb": 8.0,
    "utilization_percent": 1.2
  }
}
```

### GET `/health`
System health check with GPU monitoring.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Qwen (Alibaba)** for the language model (Qwen2.5-7B-Instruct)
- **Hugging Face** for the transformers library
- **FAISS** for efficient vector search

## 🆘 Support

For issues and questions:
1. Check the [Issues](https://github.com/yourusername/InstrumentOracle/issues) page
2. Review the GPU compatibility guide ([documents/README-GPU.md](documents/README-GPU.md))
3. Ensure all dependencies are properly installed

---

**Instrument Oracle** – AI-powered instrument and product knowledge

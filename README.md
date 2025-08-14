# Nurse Supply Oracle

A comprehensive AI-powered nursing education assistant that provides instant answers to nursing questions using advanced language models and nursing textbook knowledge.

## 🏥 Features

- **AI-Powered Q&A**: Get instant answers to nursing questions using Mistral 7B
- **Comprehensive Knowledge Base**: 1,048 chunks from 3 nursing textbooks
- **GPU Acceleration**: Optimized for NVIDIA GPUs with CUDA support
- **Smart Caching**: Fast responses for repeated questions
- **Source Attribution**: See which textbook provided each answer
- **Modern Web Interface**: Clean, responsive Next.js frontend

## 🏗️ Architecture

### Frontend
- **Next.js 15.4.5** with React 19
- **Tailwind CSS** for styling
- **TypeScript** for type safety
- **Real-time processing** with loading states

### Backend
- **Flask** server with GPU optimization
- **Mistral 7B Instruct** (4-bit quantized) for AI responses
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
   git clone https://github.com/yourusername/NurseSupplyOracle.git
   cd NurseSupplyOracle
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

5. **Process Nursing Textbooks**
   ```bash
   python scripts/prepare_all_pymupdf.py
   ```

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

The system includes comprehensive nursing knowledge from:

- **Primary Nursing Textbook**: 143 chunks
- **Secondary Nursing Textbook**: 199 chunks
- **Tertiary Nursing Textbook**: 706 chunks

**Total**: 1,048 knowledge chunks with semantic search capabilities.

## 🔧 Configuration

### GPU Requirements
- **Minimum**: 4GB VRAM (with 4-bit quantization)
- **Recommended**: 8GB+ VRAM for optimal performance
- **CPU Fallback**: Available but significantly slower

### Environment Variables
```bash
# Hugging Face token (for model access)
export HF_TOKEN="your_hf_token_here"

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
NurseSupplyOracle/
├── src/                    # Next.js frontend
│   ├── app/               # App router components
│   └── globals.css        # Global styles
├── scripts/               # Python backend
│   ├── chat_server_hf.py  # Flask server
│   ├── chat_hf.py         # AI model interface
│   └── prepare_all_pymupdf.py # Data processing
├── public/                # Static assets
├── requirements-gpu.txt   # Python dependencies
└── package.json          # Node.js dependencies
```

### Key Scripts
- `scripts/chat_server_hf.py`: Main Flask server
- `scripts/chat_hf.py`: Mistral 7B model interface
- `scripts/prepare_all_pymupdf.py`: Text processing pipeline
- `scripts/check_cuda.py`: GPU compatibility check

## 🔍 API Endpoints

### POST `/api/chat`
Send nursing questions and receive AI-powered answers.

**Request:**
```json
{
  "question": "What should I use on a burn?"
}
```

**Response:**
```json
{
  "answer": "You should use water, saline solution, or a wound cleanser, followed by an antibacterial wash, a topical antibiotic ointment like silver sulfadiazine or mupirocin, and a nonadherent dressing.",
  "sources": ["Tertiary Nursing Textbook"],
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

- **Mistral AI** for the powerful language model
- **Hugging Face** for the transformers library
- **OpenStax** for nursing textbook content
- **FAISS** for efficient vector search

## 🆘 Support

For issues and questions:
1. Check the [Issues](https://github.com/yourusername/NurseSupplyOracle/issues) page
2. Review the GPU compatibility guide
3. Ensure all dependencies are properly installed

---

**Built with ❤️ for nursing education**

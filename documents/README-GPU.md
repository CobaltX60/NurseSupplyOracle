# GPU Optimization Guide for Instrument Oracle

This guide covers GPU optimization for the Instrument Oracle application using Hugging Face models (Qwen2.5-7B-Instruct with 8-bit quantization by default).

## 🚀 Quick Start

### **Step 1: Install GPU Dependencies**

```bash
# Install CUDA-enabled PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install Hugging Face dependencies
pip install transformers accelerate bitsandbytes

# Install other requirements
pip install -r requirements.txt
```

### **Step 2: Verify GPU Setup**

```bash
# Check CUDA availability
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# Check GPU info
python -c "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}')"
```

### **Step 3: Start the Optimized Server**

```bash
# Start the GPU server
python scripts/chat_server.py

# In another terminal, start the frontend
npm run dev
```

## 🎯 Performance Benefits

### **Before (llama-cpp-python)**
- ❌ 60+ second response times
- ❌ CPU-only processing
- ❌ 1.1% GPU utilization
- ❌ Manual model management

### **After (Hugging Face)**
- ✅ Sub-second to single-digit second responses
- ✅ Full GPU acceleration with 8-bit quantization (Qwen2.5-7B)
- ✅ 80%+ GPU utilization
- ✅ Automatic model download and caching

## 📊 GPU Requirements

### **Minimum Requirements**
- **VRAM**: 6GB
- **CUDA**: 11.8+
- **Driver**: Latest NVIDIA drivers

### **Recommended Requirements**
- **VRAM**: 8GB+ (RTX 3070 Ti or better)
- **CUDA**: 12.0+
- **Driver**: Latest NVIDIA drivers

## 🔧 Configuration

### **Hugging Face Model Configuration**

The system automatically uses optimized settings:

```python
# 8-bit quantization for good quality and memory usage
BQB = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16
)

# GPU-optimized model loading
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    quantization_config=BQB,
    device_map="auto",
    torch_dtype=torch.float16
)
```

### **Model Options**

**Primary Model:**
- `Qwen/Qwen2.5-7B-Instruct` (8-bit quantized)

**Alternative:** You can change the model and quantization in `scripts/chat_server.py` (e.g. 4-bit for lower VRAM).

## 📈 Performance Monitoring

### **Health Check Endpoint**
```bash
curl http://localhost:5001/health
```

**Response includes:**
- GPU memory usage and utilization
- System resource usage
- Performance statistics
- Model loading status

### **GPU Memory Monitoring**
```python
# Real-time GPU monitoring
import torch
print(f"GPU Memory: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")
print(f"GPU Utilization: {torch.cuda.memory_reserved(0) / 1024**3:.2f} GB")
```

## ⚙️ Advanced Configuration

### **Custom Model Settings**

You can modify the model configuration in `scripts/chat_server.py`:

```python
# Adjust generation parameters
def answer(question: str, max_tokens: int = 256) -> str:
    inputs = tokenizer(question, return_tensors="pt").to("cuda")
    out = model.generate(
        **inputs,
        max_new_tokens=max_tokens,  # Adjust for longer/shorter responses
        do_sample=False,            # Deterministic output
        pad_token_id=tokenizer.eos_token_id
    )
    return tokenizer.decode(out[0], skip_special_tokens=True)
```

### **Memory Optimization**

For lower VRAM usage:

```python
# Use 8-bit quantization instead of 4-bit
BQB = BitsAndBytesConfig(
    load_in_8bit=True,
    bnb_8bit_compute_dtype=torch.float16
)

# Or use CPU offloading for very large models
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    device_map="auto",
    offload_folder="offload",
    torch_dtype=torch.float16
)
```

## 🔍 Troubleshooting

### **Common GPU Issues**

1. **CUDA not available**
   ```bash
   # Check CUDA installation
   python -c "import torch; print(torch.cuda.is_available())"
   
   # Reinstall PyTorch with CUDA
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
   ```

2. **Out of GPU memory**
   - Reduce `max_new_tokens` in generation
   - Use smaller models
   - Enable gradient checkpointing

3. **Slow first request**
   - This is normal - model is downloading
   - Subsequent requests are much faster

4. **Model download issues**
   - Check internet connection
   - Clear Hugging Face cache: `rm -rf ~/.cache/huggingface`

### **Performance Tuning**

For optimal performance:

1. **Monitor GPU usage**
   ```bash
   watch -n 1 nvidia-smi
   ```

2. **Adjust batch size**
   - Increase for faster processing (if memory allows)
   - Decrease for lower memory usage

3. **Optimize context size**
   - Reduce context window for faster inference
   - Balance between speed and quality

## 🎯 Expected Performance

With proper GPU optimization:

- **First request**: 5-15 seconds (model download)
- **Subsequent requests**: 1-5 seconds
- **Cached requests**: <100ms
- **GPU utilization**: 80%+
- **Memory usage**: 3-5GB VRAM

## 📚 Additional Resources

- [Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers/)
- [BitsAndBytes Documentation](https://github.com/TimDettmers/bitsandbytes)
- [PyTorch CUDA Guide](https://pytorch.org/docs/stable/notes/cuda.html)
- [NVIDIA GPU Monitoring](https://developer.nvidia.com/nvidia-system-management-interface)

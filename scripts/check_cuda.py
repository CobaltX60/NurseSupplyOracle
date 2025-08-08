import torch

print("=== CUDA/GPU Information ===")
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA device count: {torch.cuda.device_count()}")
    print(f"Current device: {torch.cuda.current_device()}")
    print(f"Device name: {torch.cuda.get_device_name(0)}")
    print(f"CUDA version: {torch.version.cuda}")
    
    # Test GPU memory
    device = torch.device('cuda:0')
    print(f"GPU memory allocated: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")
    print(f"GPU memory cached: {torch.cuda.memory_reserved(0) / 1024**3:.2f} GB")
else:
    print("CUDA is not available. You may need to install PyTorch with CUDA support.")
    print("Try: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118") 
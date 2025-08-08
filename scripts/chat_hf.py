# scripts/chat_hf.py
import sys
import json
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch
import re

# ensure we can print unicode on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except:
    pass

# 1) Switch to Mistral-7B-Instruct-v0.3 (the correct model name)
MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# 2) More aggressive 4-bit quant config for 8GB GPU
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,  # Double quantization to save more memory
    llm_int8_threshold=6.0,
    llm_int8_has_fp16_weight=False
)

# 3) Load model + tokenizer ON GPU with authentication (use slow tokenizer to avoid sentencepiece issues)
tokenizer = AutoTokenizer.from_pretrained(MODEL, token="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", use_fast=False)
model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    quantization_config=bnb_config,
    device_map="auto",
    torch_dtype=torch.float16,
    token="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"
)

def clean_response(response: str, original_question: str) -> str:
    """Clean the response to extract only the actual answer"""
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
    
    # Limit response length
    if len(response) > 200:
        sentences = response.split('.')
        response = '. '.join(sentences[:2]) + '.'
    
    return response

def answer(question: str, max_tokens: int = 50) -> str:  # Optimized for concise responses
    # Format prompt for Mistral instruction model
    prompt = f"""<s>[INST] {question} [/INST]"""
    
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    out = model.generate(
        **inputs,
        max_new_tokens=max_tokens,
        do_sample=False,
        temperature=0.1,  # Low temperature for focused responses
        top_p=0.9,        # Nucleus sampling
        repetition_penalty=1.1,  # Prevent repetition
        pad_token_id=tokenizer.eos_token_id,
        eos_token_id=tokenizer.eos_token_id,
        early_stopping=True
    )
    raw_response = tokenizer.decode(out[0], skip_special_tokens=True)
    
    # Clean the response
    cleaned_response = clean_response(raw_response, question)
    
    # If the response is too short or seems incomplete, return a fallback
    if len(cleaned_response) < 10:
        return "Based on the available information, I cannot provide a complete answer at this time."
    
    return cleaned_response

if __name__ == "__main__":
    # expect {"question":"…"} on stdin or as arg0
    data = json.loads(sys.stdin.read()) if not sys.argv[1:] else json.loads(sys.argv[1])
    q = data.get("question", "")
    resp = answer(q)
    print(json.dumps({"answer": resp})) 
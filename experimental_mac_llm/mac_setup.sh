#!/bin/bash
# MacOS M2 AI Node Setup Script for MathStudio Experimental Pipeline
# Target IP: 192.168.178.26
# Run this script on the Mac terminal.

echo "Starting Mac M2 MathStudio AI Node Setup..."

# 1. Update Homebrew (Optional but recommended)
# brew update

# 2. Setup Python Virtual Environment
echo "Setting up Python virtual environment..."
mkdir -p ~/mathstudio_ai_node
cd ~/mathstudio_ai_node
python3 -m venv venv
source venv/bin/activate

# 3. Install MLX and MLX-VLM Packages
# MLX is Apple's array framework tailored for Apple Silicon (Metal).
echo "Installing mlx, mlx-vlm, and mlx-lm..."
pip install --upgrade pip
pip install mlx mlx-lm mlx-vlm
pip install fastapi uvicorn

# 4. Create the Model Server Script
echo "Creating the API server script..."
cat << 'EOF' > server.py
import argparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
import uvicorn
import mlx_vlm
import mlx_lm
import mlx.core as mx

app = FastAPI(title="MathStudio MLX Server")

# Global state for loaded models
current_model_type = None  # 'vision' or 'reasoning'
model = None
processor = None

# Model IDs specialized for MLX (quantized for M2)
# These models are hosted on the Hugging Face mlx-community
VISION_MODEL_ID = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
REASONING_MODEL_ID = "mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit"

class LoadRequest(BaseModel):
    model_type: str  # "vision" or "reasoning"

@app.post("/load")
async def load_model(req: LoadRequest):
    global current_model_type, model, processor
    
    if current_model_type == req.model_type:
        return {"status": f"{req.model_type} already loaded"}
        
    # Free existing memory
    if model is not None:
        del model
        del processor
        mx.metal.clear_cache()
    
    if req.model_type == "vision":
        print(f"Loading Vision Model: {VISION_MODEL_ID}")
        model, processor = mlx_vlm.load(VISION_MODEL_ID)
        current_model_type = "vision"
    elif req.model_type == "reasoning":
        print(f"Loading Reasoning Model: {REASONING_MODEL_ID}")
        # Using mlx_lm for text-only reasoning models
        model, processor = mlx_lm.load(REASONING_MODEL_ID)
        current_model_type = "reasoning"
    else:
        raise HTTPException(status_code=400, detail="Invalid model_type")
        
    return {"status": f"Loaded {req.model_type}"}

@app.post("/unload")
async def unload_model():
    global current_model_type, model, processor
    del model
    del processor
    model = None
    processor = None
    current_model_type = None
    mx.metal.clear_cache()
    return {"status": "Models unloaded, memory cleared"}

@app.get("/status")
def status():
    return {"loaded_model": current_model_type}

# Vision Endpoint (receives Base64 image or multipart file)
@app.post("/generate/vision")
async def generate_vision(
    image: UploadFile = File(...), 
    prompt: str = Form(...),
    temperature: float = Form(0.0)
):
    if current_model_type != "vision":
        raise HTTPException(status_code=400, detail="Vision model not loaded. Call /load first.")
        
    # Read image bytes
    image_bytes = await image.read()
    
    # Process with MLX-VLM
    # (Implementation details for passing bytes to mlx_vlm go here - 
    # typically involves saving to temp file or using PIL.Image.open from BytesIO)
    from PIL import Image
    import io
    pil_image = Image.open(io.BytesIO(image_bytes))
    
    # Format prompt for Qwen-VL
    messages = [
        {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}
    ]
    prompt_text = processor.apply_chat_template(messages, add_generation_prompt=True)
    
    # Generate
    output = mlx_vlm.generate(
        model, 
        processor, 
        prompt_text, 
        [pil_image], 
        verbose=False,
        temp=temperature
    )
    return {"text": output}

class ReasoningRequest(BaseModel):
    prompt: str
    temperature: float = 0.6
    max_tokens: int = 2048

# Reasoning Endpoint (Text only)
@app.post("/generate/reasoning")
async def generate_reasoning(req: ReasoningRequest):
    if current_model_type != "reasoning":
         raise HTTPException(status_code=400, detail="Reasoning model not loaded. Call /load first.")
         
    prompt = processor.apply_chat_template(
        [{"role": "user", "content": req.prompt}],
        add_generation_prompt=True
    )
    
    output = mlx_lm.generate(
        model, 
        processor, 
        prompt, 
        temp=req.temperature, 
        max_tokens=req.max_tokens,
        verbose=False
    )
    return {"text": output}

if __name__ == "__main__":
    # Bind to 0.0.0.0 to allow access from 192.168.178.2
    uvicorn.run(app, host="0.0.0.0", port=8000)
EOF

# 5. Download the Models (Optional pre-fetch)
# We can use the huggingface-cli via mlx tools to pre-download the models
# so the first load isn't extremely slow.
echo "Downloading specialized MLX MLX-community models..."
echo "1. Downloading Qwen2.5-VL-7B-Instruct-4bit (Vision)..."
python3 -c "import mlx_vlm; mlx_vlm.load('mlx-community/Qwen2.5-VL-7B-Instruct-4bit')"

echo "2. Downloading DeepSeek-R1-Distill-Qwen-14B-4bit (Reasoning)..."
python3 -c "import mlx_lm; mlx_lm.load('mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit')"

echo "Setup complete! To run the server:"
echo "cd ~/mathstudio_ai_node"
echo "source venv/bin/activate"
echo "python server.py"
echo "The API will be available at http://192.168.178.26:8000"

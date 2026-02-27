import paramiko

host = "192.168.178.26"
user = "jure"
password = "jussupow"

patch_script = """
import sys
with open('/Users/jure/mathstudio_ai_node/server.py', 'r') as f:
    content = f.read()

import re

# We will completely replace the vision endpoint
old_vision_endpoint = re.search(r'# Vision Endpoint.*?class ReasoningRequest', content, re.DOTALL)

if old_vision_endpoint:
    new_vision = '''# Vision Endpoint (receives Base64 image)

class VisionRequest(BaseModel):
    image_base64: str
    prompt: str
    temperature: float = 0.0

@app.post("/generate/vision")
async def generate_vision(req: VisionRequest):
    if current_model_type != "vision":
        raise HTTPException(status_code=400, detail="Vision model not loaded. Call /load first.")
        
    import base64
    import io
    from PIL import Image
    
    try:
        b64_data = req.image_base64
        if b64_data.startswith('data:image'):
            b64_data = b64_data.split(',')[1]
            
        b64_data = b64_data.strip()
        # Add padding if missing
        missing_padding = len(b64_data) % 4
        if missing_padding:
            b64_data += '=' * (4 - missing_padding)
        
        image_bytes = base64.b64decode(b64_data)
        
        # Write to disk to ensure mlx_vlm processes it correctly as a path
        tmp_img_path = "/tmp/current_vision.png"
        with open(tmp_img_path, "wb") as f:
            f.write(image_bytes)
            
        max_pixels = 3136 * 28 * 28
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image format: {e}")
    
    messages = [
        {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": req.prompt}]}
    ]
    
    # Qwen2.5-VL fast processor forces return_tensors='pt' and clashes with mlx_lm's 'np' hardcoding.
    processor.image_processor.use_fast = False
    
    # 1. Provide the format string without generating the assistant prefix natively since we process manually
    prompt_text = processor.apply_chat_template(messages, add_generation_prompt=True)
    
    # 2. Call the processor directly but FORCE return_tensors="pt" to appease Qwen Fast Processor
    from PIL import Image
    image = Image.open(tmp_img_path)
    inputs = processor(text=[prompt_text], images=[image], padding=True, return_tensors="pt")
    
    # 3. Convert PyTorch tensors directly to MLX Arrays
    import mlx.core as mx
    from mlx_vlm.utils import generate_step
    
    model_inputs = {}
    for key, value in inputs.items():
        if key not in ["images"]: # ignore generic lists if they exist
            # Convert torch tensor -> numpy array -> mlx array
            model_inputs[key] = mx.array(value.numpy())
            
    input_ids = model_inputs.pop("input_ids")
    pixel_values = model_inputs.pop("pixel_values")
    mask = model_inputs.pop("attention_mask", None)
    
    # Qwen needs image_grid_thw directly injected
    kwargs = {k: v for k, v in model_inputs.items()}
            
    # 4. Stream generate using the underlying mlx_lm generator
    detokenizer = processor.detokenizer
    detokenizer.reset()
    
    for n, (token, _) in enumerate(generate_step(input_ids, model, pixel_values, mask, temp=req.temperature, **kwargs)):
        if token == processor.tokenizer.eos_token_id:
            break
        detokenizer.add_token(token)
        
    detokenizer.finalize()
    return {"text": detokenizer.last_segment}

class ReasoningRequest'''

    content = content.replace(old_vision_endpoint.group(0), new_vision)
    with open('/Users/jure/mathstudio_ai_node/server.py', 'w') as f:
        f.write(content)
    print("PATCH APPLIED SUCCESSFULLY")
else:
    print("TARGET NOT FOUND")
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting to {host}...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    sftp = client.open_sftp()
    with sftp.file('/tmp/mac_patch_b64.py', 'w') as f:
        f.write(patch_script)
    sftp.close()
    
    print("Executing patch script...")
    stdin, stdout, stderr = client.exec_command("python3 /tmp/mac_patch_b64.py")
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)
    
finally:
    client.close()

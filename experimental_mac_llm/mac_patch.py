import os
import sys

act_path = '/Users/jure/mathstudio_ai_node/venv/bin/activate_this.py'
if os.path.exists(act_path):
    with open(act_path) as f:
        exec(f.read(), dict(__file__=act_path))
else:
    # Manual path hacking if activate_this.py is missing (common in python3 -m venv)
    sys.path.insert(0, '/Users/jure/mathstudio_ai_node/venv/lib/python3.9/site-packages')

import mlx_vlm
import inspect

print("--- MLX VLM GENERATE SIGNATURE ---")
try:
    print(inspect.signature(mlx_vlm.generate))
except Exception as e:
    print("Could not get signature:", e)

with open('/Users/jure/mathstudio_ai_node/server.py', 'r') as f:
    content = f.read()

old_gen = """    output = mlx_vlm.generate(
        model, 
        processor, 
        prompt_text, 
        [pil_image], 
        verbose=False,
        temp=temperature
    )"""

new_gen = """    output = mlx_vlm.generate(
        model=model, 
        processor=processor, 
        prompt=prompt_text, 
        images=[pil_image], 
        verbose=False,
        temperature=temperature
    )"""

if old_gen in content:
    content = content.replace(old_gen, new_gen)
    with open('/Users/jure/mathstudio_ai_node/server.py', 'w') as f:
        f.write(content)
    print("PATCH APPLIED SUCCESSFULLY")
else:
    print("PATCH TARGET NOT FOUND. Current code:")
    
    idx = content.find("mlx_vlm.generate")
    if idx != -1:
        print(content[max(0, idx-50) : min(len(content), idx+200)])

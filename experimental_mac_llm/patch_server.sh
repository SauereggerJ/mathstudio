#!/bin/bash
cat << 'EOF' > /home/jure/nasi_data/math/New_Research_Library/mathstudio/experimental_mac_llm/patch_server.py
with open("/Users/jure/mathstudio_ai_node/server.py", "r") as f:
    content = f.read()

# Fix the Vision Endpoint Generation logic
# mlx_vlm.generate syntax for Qwen2.5-VL expects:
# generate(model, processor, prompt, image_processor=None, **kwargs)
old_gen = """    output = mlx_vlm.generate(
        model, 
        processor, 
        prompt_text, 
        [pil_image], 
        verbose=False,
        temp=temperature
    )"""

new_gen = """    # Correct parameters for Qwen2.5-VL with MLX
    output = mlx_vlm.generate(
        model, 
        processor, 
        prompt=prompt_text,
        image_processor=processor, # Sometimes needed depending on mlx-vlm version
        verbose=False,
        temp=temperature
    )"""

if old_gen in content:
    content = content.replace(old_gen, new_gen)
    with open("/Users/jure/mathstudio_ai_node/server.py", "w") as f:
        f.write(content)
    print("PATCH APPLIED SUCCESSFULLY")
else:
    print("PATCH TARGET NOT FOUND")
EOF

ssh jpass@192.168.178.26 "" # Dummy

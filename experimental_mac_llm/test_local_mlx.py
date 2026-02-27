import paramiko
import os

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting to {host}...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    print("Uploading test image to Mac...")
    sftp = client.open_sftp()
    
    test_script = """
import sys
import mlx_vlm
import time

model_path = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
print("Loading model...")
model, processor = mlx_vlm.load(model_path)

prompt = "Please transcribe the entire contents of this textbook page."

messages = [
    {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}
]
prompt_text = processor.apply_chat_template(messages, add_generation_prompt=True)

print("Generating...")
output = mlx_vlm.generate(
    model=model,
    processor=processor,
    prompt=prompt_text,
    image_processor=processor,
    images=["/tmp/mathstudio_temp_p30.png"],
    verbose=False,
    temperature=0.0
)
print("--- OUTPUT ---")
print(output)
"""
    
    sftp.put('/tmp/mathstudio_temp_p30.png', '/tmp/mathstudio_temp_p30.png')
    with sftp.file('/tmp/test_local_mlx.py', 'w') as f:
        f.write(test_script)
    sftp.close()
    
    print("Executing local test on Mac...")
    stdin, stdout, stderr = client.exec_command("source /Users/jure/mathstudio_ai_node/venv/bin/activate && python3 /tmp/test_local_mlx.py")
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)

finally:
    client.close()

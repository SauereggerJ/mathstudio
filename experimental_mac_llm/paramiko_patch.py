import paramiko
import sys

host = "192.168.178.26"
user = "jure"
password = "jussupow"

patch_script = """
import sys
sys.path.insert(0, '/Users/jure/mathstudio_ai_node/venv/lib/python3.9/site-packages')
import mlx_vlm
import inspect

print("--- SIGNATURE ---")
print(inspect.signature(mlx_vlm.generate))

try:
    with open('/Users/jure/mathstudio_ai_node/server.py', 'r') as f:
        content = f.read()
        
    old_gen = '''    output = mlx_vlm.generate(
        model, 
        processor, 
        prompt_text, 
        [pil_image], 
        verbose=False,
        temp=temperature
    )'''

    new_gen = '''    output = mlx_vlm.generate(
        model=model, 
        processor=processor, 
        prompt=prompt_text, 
        image_processor=processor,
        images=[pil_image], 
        verbose=False,
        temperature=temperature
    )'''

    if old_gen in content:
        content = content.replace(old_gen, new_gen)
        with open('/Users/jure/mathstudio_ai_node/server.py', 'w') as f:
            f.write(content)
        print("PATCH APPLIED SUCCESSFULLY")
    else:
        print("PATCH NOT FOUND")
except Exception as e:
    print("Error:", e)
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting to {host}...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    print("Uploading patch script via SFTP...")
    sftp = client.open_sftp()
    with sftp.file('/tmp/mac_patch.py', 'w') as f:
        f.write(patch_script)
    sftp.close()
    
    print("Executing patch script...")
    stdin, stdout, stderr = client.exec_command("python3 /tmp/mac_patch.py")
    
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)
    
finally:
    client.close()

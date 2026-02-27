import paramiko
import re

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to 192.168.178.26...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    
    with sftp.file('/Users/jure/mathstudio_ai_node/server.py', 'r') as f:
        content = f.read().decode('utf-8')
        
    old_load = 'model, processor = mlx_vlm.load(VISION_MODEL_ID)'
    new_load = 'model, processor = mlx_vlm.load(VISION_MODEL_ID, processor_config={"use_fast": False})'
    
    if old_load in content:
        content = content.replace(old_load, new_load)
        with sftp.file('/Users/jure/mathstudio_ai_node/server.py', 'w') as f:
            f.write(content)
        print("PATCH APPLIED SUCCESSFULLY")
    elif new_load in content:
        print("PATCH ALREADY APPLIED")
    else:
        print("STRING NOT FOUND")
finally:
    client.close()

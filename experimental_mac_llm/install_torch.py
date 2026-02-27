import paramiko
import time

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to Mac M2...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    print("Installing Torch within the venv...")
    stdin, stdout, stderr = client.exec_command("source /Users/jure/mathstudio_ai_node/venv/bin/activate && pip install torch torchvision torchaudio")
    
    # Wait for the installation to finish
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)
    
    print(f"Installation finished with exit code {exit_status}.")
        
finally:
    client.close()

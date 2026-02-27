import paramiko
import sys

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting to {host}...")
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    print("Running server.py directly...")
    stdin, stdout, stderr = client.exec_command("source /Users/jure/mathstudio_ai_node/venv/bin/activate && python3 /Users/jure/mathstudio_ai_node/server.py")
    
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)
    
finally:
    client.close()

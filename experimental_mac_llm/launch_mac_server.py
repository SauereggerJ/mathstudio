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
    
    print("Launching server.py with nohup...")
    # Execute and immediately disconnect to leave nohup running
    client.exec_command("pkill -f 'python server.py'; cd /Users/jure/mathstudio_ai_node && source venv/bin/activate && nohup python server.py > server.log 2>&1 & ")
    print("Launched in background.")
finally:
    client.close()

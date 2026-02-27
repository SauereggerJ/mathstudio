import paramiko
import time

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    
    # 1. Kill everything on port 8000 and any python server.py
    print("Killing existing servers...")
    client.exec_command("lsof -ti :8000 | xargs kill -9")
    client.exec_command("pkill -9 -f 'python server.py'")
    time.sleep(2)
    
    # 2. Launch with nohup and caffeinate to prevent sleep
    print("Launching new server with caffeinate...")
    client.exec_command("cd /Users/jure/mathstudio_ai_node && source venv/bin/activate && nohup caffeinate -is python server.py > server.log 2>&1 & ")
    print("Launched.")
finally:
    client.close()

import paramiko
import time

host = "192.168.178.2"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting to Intel Server {host}...")
    client.connect(host, username=user, password=password, timeout=10, look_for_keys=False, allow_agent=False)
    
    # Check if app.py is running
    stdin, stdout, stderr = client.exec_command("pgrep -f 'python.*app.py'")
    pids = stdout.read().decode().strip().split('\n')
    
    if pids and pids[0]:
        print(f"Found running app.py processes: {pids}. Restarting...")
        client.exec_command("pkill -f 'python.*app.py'")
        time.sleep(2)
        
    print("Starting app.py in background via tmux or nohup...")
    client.exec_command("cd /home/jure/nasi_data/math/New_Research_Library/mathstudio && nohup python3 app.py > server.log 2>&1 &")
    
    print("SUCCESS: Intel server restarted.")
    
except Exception as e:
    print(f"Failed to SSH into {host}: {e}")
finally:
    client.close()

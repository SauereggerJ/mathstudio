import paramiko
import sys

host = "192.168.178.26"
user = "jure"
password = "jussupow"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    # Read the log
    stdin, stdout, stderr = client.exec_command("tail -n 50 /Users/jure/mathstudio_ai_node/server.log")
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    if out: print("--- MAC SERVER LOG ---\n", out)
    if err: print("--- MAC SERVER ERR ---\n", err)
finally:
    client.close()

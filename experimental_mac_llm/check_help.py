import paramiko

host = "192.168.178.26"
user = "jure"
password = "jussupow"

test_script = """
import sys
sys.path.insert(0, '/Users/jure/mathstudio_ai_node/venv/lib/python3.9/site-packages')
import mlx_vlm
print(help(mlx_vlm.generate))
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(host, username=user, password=password, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    with sftp.file('/tmp/check_qwen_help.py', 'w') as f:
        f.write(test_script)
    sftp.close()
    
    stdin, stdout, stderr = client.exec_command("source /Users/jure/mathstudio_ai_node/venv/bin/activate && python3 /tmp/check_qwen_help.py")
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    if out: print("STDOUT:\n", out)
    if err: print("STDERR:\n", err)
finally:
    client.close()

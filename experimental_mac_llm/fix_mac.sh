#!/usr/bin/expect -f
set timeout 10
spawn ssh jure@192.168.178.26 "source ~/mathstudio_ai_node/venv/bin/activate && python3 -c \"
import mlx_vlm
import inspect
print('--- MLX VLM GENERATE SIGNATURE ---')
print(inspect.signature(mlx_vlm.generate))
with open('/Users/jure/mathstudio_ai_node/server.py', 'r') as f:
    content = f.read()
if 'output = mlx_vlm.generate(' in content:
    print('Found generate block')
\""
expect "Password:"
send "jussupow\r"
expect eof

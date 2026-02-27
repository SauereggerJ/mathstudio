#!/bin/bash
cd ~/mathstudio_ai_node
source venv/bin/activate
python3 -c "import mlx_vlm; help(mlx_vlm.generate)"
python3 -c "
with open('server.py', 'r') as f:
    text = f.read()
    print('--- SERVER CODE SNIPPET ---')
    print(text[text.find('generate(')-50 : text.find('generate(')+200])
"

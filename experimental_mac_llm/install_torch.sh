#!/bin/bash
cd ~/mathstudio_ai_node
source venv/bin/activate
echo "Installing torch and torchvision for missing AutoVideoProcessor dependencies..."
pip install torch torchvision
echo "Downloading Qwen2.5-VL-7B-Instruct-4bit again..."
python3 -c "import mlx_vlm; mlx_vlm.load('mlx-community/Qwen2.5-VL-7B-Instruct-4bit')"
echo "Downloading DeepSeek-R1-Distill-Qwen-14B-4bit again..."
python3 -c "import mlx_lm; mlx_lm.load('mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit')"
echo "Installation script completed."

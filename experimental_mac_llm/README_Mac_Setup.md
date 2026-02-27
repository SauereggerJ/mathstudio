# Mac M2 AI Node Setup Guide

**Target Machine:** Apple Silicon M2 Mac (16GB RAM)
**Target IP:** `192.168.178.26`
**User:** `jure`

## Prerequisites

Ensure you have Python 3.10+ installed on the Mac. If you don't use Homebrew, you might need to install Xcode Command Line Tools first (`xcode-select --install`).

## Installation Steps

1. **SSH into the Mac** from your LMDE dev machine (`192.168.178.30`):
   ```bash
   ssh jure@192.168.178.26
   ```

2. **Copy the setup script** to the Mac. You can do this by copying the contents of `mac_setup.sh` (located in `mathstudio/experimental_mac_llm/` on the server/LMDE) or by transferring the file directly using `scp`:
   ```bash
   # From LMDE (192.168.178.30)
   scp /mnt/nasi_data/math/New_Research_Library/mathstudio/experimental_mac_llm/mac_setup.sh jure@192.168.178.26:~
   ```

3. **Run the script** on the Mac:
   ```bash
   chmod +x mac_setup.sh
   ./mac_setup.sh
   ```

## What the Script Does

1. Creates a virtual environment in `~/mathstudio_ai_node`.
2. Installs Apple's native machine learning framework `mlx`, along with `mlx-lm` (for text models) and `mlx-vlm` (for vision models), optimizing inference for Apple Silicon's unified memory architecture.
3. Installs `fastapi` and `uvicorn` to run the inference server.
4. Generates a Python server script (`server.py`) that handles dynamic swapping between models to adhere to the 16GB memory limit.
5. Downloads the 4-bit quantized MLX-community versions of the models:
   - **Vision**: `mlx-community/Qwen2.5-VL-7B-Instruct-4bit` (~4.5 GB)
   - **Reasoning**: `mlx-community/DeepSeek-R1-Distill-Qwen-14B-4bit` (~8.5 GB)

## Running the Server

Once setup is complete, you can start the dedicated MathStudio MLX inference server:

```bash
cd ~/mathstudio_ai_node
source venv/bin/activate
python server.py
```

The server binds to `0.0.0.0:8000`, making it accessible to your Intel machine (`192.168.178.2`) on the local network. 

## API Endpoints Overview

- `POST /load` — Send `{"model_type": "vision"}` or `{"reasoning"}` to swap the models loaded in memory.
- `POST /unload` — Clears memory entirely.
- `GET /status` — Check which model is currently resident in RAM.
- `POST /generate/vision` — Send multipart form data (`image` file, `prompt` text) to convert PDF pages to LaTeX.
- `POST /generate/reasoning` — Send JSON (`prompt`) to synthesize KB concepts.

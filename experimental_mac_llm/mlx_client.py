import os
import io
import time
import requests
import base64
from typing import Dict, Any, Optional
from PIL import Image

class MLXClient:
    """
    Experimental client for communicating with the Mac M2 MLX Server.
    Target IP: 192.168.178.26
    """
    def __init__(self, host: str = "192.168.178.26", port: int = 8000):
        self.base_url = f"http://{host}:{port}"
        
    def _check_server_status(self) -> bool:
        """Ping the server to check connectivity."""
        try:
            resp = requests.get(f"{self.base_url}/status", timeout=15)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def load_model(self, model_type: str) -> bool:
        """
        Dynamically swap models on the Mac to handle the 16GB limit.
        model_type: "vision" | "reasoning"
        """
        try:
            print(f"Requesting MLX node to load '{model_type}' model...")
            resp = requests.post(f"{self.base_url}/load", json={"model_type": model_type}, timeout=60)
            resp.raise_for_status()
            print(f"Success: {resp.json().get('status')}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Failed to load {model_type} model: {e}")
            return False

    def generate_vision(self, image_path: str, prompt: str, temperature: float = 0.0, max_tokens: int = 2048) -> Optional[str]:
        """
        Send a PDF page (image) to the Qwen2.5-VL model to extract LaTeX.
        """
        try:
            status_resp = requests.get(f"{self.base_url}/status", timeout=120)
            if status_resp.json().get("loaded_model") != "vision":
                self.load_model("vision")
                
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            b64_str = base64.b64encode(image_bytes).decode('utf-8')
            
            payload = {
                "image_base64": b64_str, 
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
                
            print(f"Sending base64 vision request to {self.base_url} (temp={temperature})...")
            # Changed to json=payload for the new VisionRequest schema
            resp = requests.post(f"{self.base_url}/generate/vision", json=payload, timeout=300)
            
            if resp.status_code != 200:
                 print(f"Vision generation failed with status {resp.status_code}: {resp.text}")
                 resp.raise_for_status()
                 
            return resp.json().get('text')
                
        except requests.exceptions.RequestException as e:
            print(f"Vision generation failed: {e}")
            return None

    def generate_reasoning(self, prompt: str, temperature: float = 0.6) -> Optional[str]:
        """
        Send a stitched LaTeX block to DeepSeek-R1-Distill to extract Knowledge Base entries.
        """
        try:
            # We first ensure reasoning is loaded
            status_resp = requests.get(f"{self.base_url}/status", timeout=5)
            if status_resp.json().get("loaded_model") != "reasoning":
                self.load_model("reasoning")
                
            payload = {
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": 2048
            }
            
            print(f"Sending reasoning request to {self.base_url} (temp={temperature})...")
            resp = requests.post(f"{self.base_url}/generate/reasoning", json=payload, timeout=180)
            resp.raise_for_status()
            return resp.json().get('text')
            
        except requests.exceptions.RequestException as e:
            print(f"Reasoning generation failed: {e}")
            return None

if __name__ == "__main__":
    # Simple connection test
    client = MLXClient()
    if client._check_server_status():
        print(f"Connection to MLX AI Node ({client.base_url}) successful!")
        status = requests.get(f"{client.base_url}/status").json()
        print(f"Current state: {status}")
    else:
        print(f"Failed to connect to MLX AI Node at {client.base_url}. Make sure the Mac server is running on 192.168.178.26.")

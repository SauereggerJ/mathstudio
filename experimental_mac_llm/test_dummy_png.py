import io
import os
import base64
from PIL import Image as PilImage

temp_img_path = "/tmp/mathstudio_temp_p5.png"

# Same logic as worker
if os.path.exists(temp_img_path): os.remove(temp_img_path)
dummy_img = PilImage.new('RGB', (100, 100), color = 'white')
dummy_img.save(temp_img_path, format="PNG")

with open(temp_img_path, 'rb') as f:
    b64_str = base64.b64encode(f.read()).decode('utf-8')
    
print("B64 snippet:", b64_str[:50])

# Try to decode it back into PIL in memory exactly as Mac does
try:
    image_bytes = base64.b64decode(b64_str)
    pil_image = PilImage.open(io.BytesIO(image_bytes)).convert('RGB')
    print("Successfully decoded back into PIL. Size:", pil_image.size)
except Exception as e:
    print("FAILED TO DECODE LOCALLY:", e)

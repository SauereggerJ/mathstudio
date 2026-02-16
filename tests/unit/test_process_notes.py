import pytest
import io
import json
from PIL import Image
from unittest.mock import patch, MagicMock
import process_notes

def test_optimize_image():
    """Verifies that large images are scaled down."""
    # Create a large dummy image (3000x1000)
    img = Image.new('RGB', (3000, 1000), color='red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_bytes = img_byte_arr.getvalue()
    
    optimized = process_notes.optimize_image(img_bytes, max_size=2048)
    
    # Check the size of the resulting image
    result_img = Image.open(io.BytesIO(optimized))
    assert max(result_img.size) <= 2048
    assert result_img.format == 'JPEG'

def test_get_gemini_content_mocked():
    """Verifies image transcription orchestration with mocked API."""
    # Use explicit double backslashes for the JSON string to avoid 	 interpretation
    mock_dict = {
        "markdown_source": "Notes",
        "latex_source": "\section{Notes}",
        "title": "Test"
    }
    mock_json_text = json.dumps(mock_dict)
    
    mock_response_json = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": mock_json_text
                }]
            }
        }]
    }
    
    dummy_image = Image.new('RGB', (100, 100))
    img_byte_arr = io.BytesIO()
    dummy_image.save(img_byte_arr, format='JPEG')
    image_bytes = img_byte_arr.getvalue()
    
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response_json
        
        result = process_notes.get_gemini_content(image_bytes, "image/jpeg")
        assert result is not None
        assert result["title"] == "Test"
        assert result["markdown_source"] == "Notes"

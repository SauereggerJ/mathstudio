import pytest
import io
import json
from PIL import Image
from unittest.mock import patch, MagicMock
from services.note import note_service

def test_optimize_image():
    """Verifies that large images are scaled down."""
    img = Image.new('RGB', (3000, 1000), color='red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_bytes = img_byte_arr.getvalue()
    
    optimized = note_service.optimize_image(img_bytes, max_size=2048)
    result_img = Image.open(io.BytesIO(optimized))
    assert max(result_img.size) <= 2048
    assert result_img.format == 'JPEG'

def test_transcribe_note_mocked(mock_gemini):
    """Verifies image transcription orchestration with mocked API."""
    mock_dict = {
        "markdown_source": "Notes",
        "latex_source": "\\section{Notes}",
        "title": "Test"
    }
    mock_gemini.models.generate_content.return_value.text = json.dumps(mock_dict)
    
    dummy_image = Image.new('RGB', (100, 100))
    img_byte_arr = io.BytesIO()
    dummy_image.save(img_byte_arr, format='JPEG')
    image_bytes = img_byte_arr.getvalue()
    
    result = note_service.transcribe_note(image_bytes)
    assert result is not None
    assert result["title"] == "Test"
    assert result["markdown_source"] == "Notes"

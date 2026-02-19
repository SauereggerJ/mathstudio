import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import converter

def test_extract_text_pypdf_mocked(tmp_path):
    """Verifies PDF text extraction with mocked pypdf."""
    dummy_pdf = tmp_path / "test.pdf"
    dummy_pdf.write_text("fake pdf content")
    
    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Extracted mathematical text"
    mock_reader.pages = [mock_page]
    
    with patch("pypdf.PdfReader", return_value=mock_reader):
        text, error = converter.extract_text_pypdf(str(dummy_pdf), 1)
        assert error is None
        assert text == "Extracted mathematical text"

def test_extract_text_pypdf_out_of_range(tmp_path):
    dummy_pdf = tmp_path / "test.pdf"
    dummy_pdf.write_text("fake pdf content")
    
    mock_reader = MagicMock()
    mock_reader.pages = [MagicMock()]
    
    with patch("pypdf.PdfReader", return_value=mock_reader):
        text, error = converter.extract_text_pypdf(str(dummy_pdf), 5)
        assert text is None
        assert "out of range" in error

def test_convert_page_success():
    """Verifies the full conversion flow with a mocked Gemini API response."""
    longer_text = "This is a sufficiently long string of mathematical text for testing."
    mock_dict = {
        "markdown": "# Math Note",
        "latex": "\\section{Math}"
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
    
    with (patch("converter.extract_text_pypdf", return_value=(longer_text, None)),
          patch("os.path.exists", return_value=True),
          patch("requests.post") as mock_post):
        
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response_json
        
        data, error = converter.convert_page("dummy.pdf", 1)
        
        assert error is None
        assert data["markdown"] == "# Math Note"
        assert data["latex"] == "\\section{Math}"

def test_convert_page_api_error():
    longer_text = "This is a sufficiently long string of mathematical text for testing."
    with (patch("converter.extract_text_pypdf", return_value=(longer_text, None)),
          patch("os.path.exists", return_value=True),
          patch("requests.post") as mock_post):
        
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Internal Server Error"
        
        data, error = converter.convert_page("dummy.pdf", 1)
        assert data is None
        assert "Gemini API Error 500" in error

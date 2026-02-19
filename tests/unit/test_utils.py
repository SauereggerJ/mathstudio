import pytest
import os
import json
from unittest.mock import patch, mock_open
from core.config import get_api_key

def test_load_api_key_success():
    mock_creds = json.dumps({"GEMINI_API_KEY": "test_key"})
    # Patch PROJECT_ROOT / "credentials.json" open call
    with patch("builtins.open", mock_open(read_data=mock_creds)):
        assert get_api_key() == "test_key"

def test_load_api_key_env_fallback():
    with patch("builtins.open", side_effect=FileNotFoundError):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "env_key"}):
            assert get_api_key() == "env_key"

import pytest
import os
import json
from unittest.mock import patch, mock_open
from utils import load_api_key

def test_load_api_key_success():
    mock_creds = json.dumps({"GEMINI_API_KEY": "test_key"})
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_creds)):
            assert load_api_key() == "test_key"

def test_load_api_key_missing_key():
    mock_creds = json.dumps({"OTHER_KEY": "val"})
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_creds)):
            assert load_api_key() is None

def test_load_api_key_file_not_found():
    with patch("os.path.exists", return_value=False):
        assert load_api_key() is None

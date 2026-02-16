import pytest
import sqlite3
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set dummy API key
os.environ["GEMINI_API_KEY"] = "dummy_key"

@pytest.fixture
def test_db():
    """Creates a temporary file database with the full schema for testing."""
    db_fd, db_path = tempfile.mkstemp()
    
    import indexer
    with patch("indexer.DB_FILE", db_path):
        indexer.setup_database()
        
    yield db_path
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture
def mock_gemini():
    """Mocks the Gemini client."""
    mock_client = MagicMock()
    
    mock_emb = MagicMock()
    mock_emb.embeddings = [MagicMock(values=[0.1] * 768)]
    mock_client.models.embed_content.return_value = mock_emb
    
    mock_gen = MagicMock()
    mock_gen.text = "Expanded Query"
    mock_client.models.generate_content.return_value = mock_gen
    
    with (patch("search.client", mock_client),
          patch("book_ingestor.client", mock_client)):
        yield mock_client

@pytest.fixture
def client(test_db):
    """Flask test client."""
    # Patch config values in ALL modules that might use them
    with (patch("config.DB_FILE", Path(test_db)),
          patch("config.LIBRARY_ROOT", Path("/tmp")),
          patch("api_v1.DB_FILE", test_db),
          patch("search.DB_FILE", test_db)):
        
        from app import app as flask_app
        flask_app.config.update({"TESTING": True})
        
        with flask_app.test_client() as client:
            yield client

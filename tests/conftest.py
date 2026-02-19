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
    
    from core.database import DatabaseManager
    db_mgr = DatabaseManager(db_path)
    db_mgr.initialize_schema()
        
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
    
    # Patch the services that use the client
    with (patch("services.search.search_service.ai.client", mock_client),
          patch("services.ingestor.ingestor_service.ai.client", mock_client),
          patch("services.note.note_service.ai.client", mock_client),
          patch("core.ai.genai.Client", return_value=mock_client)):
        yield mock_client

@pytest.fixture
def client(test_db):
    """Flask test client."""
    # Patch config values in ALL modules that might use them
    with (patch("core.config.DB_FILE", Path(test_db)),
          patch("core.config.LIBRARY_ROOT", Path("/tmp"))):
        
        from app import app as flask_app
        flask_app.config.update({"TESTING": True})
        
        with flask_app.test_client() as client:
            yield client

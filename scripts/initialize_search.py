import sys
import os

# Add project root to path for core imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.search_engine import create_mathstudio_indices
    print("Starting Elasticsearch Index Initialization...")
    create_mathstudio_indices()
    print("Initialization complete.")
except ImportError as e:
    print(f"Error: Could not import core modules. Ensure requirements are installed. {e}")
except Exception as e:
    print(f"An error occurred during initialization: {e}")

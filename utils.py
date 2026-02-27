
import json
import os
import sys

def load_api_key(credentials_file="credentials.json"):
    """
    Loads GEMINI_API_KEY from credentials.json.
    Attempts to find the file in the current directory or the script's directory.
    """
    try:
        # Check current working directory
        if os.path.exists(credentials_file):
            path = credentials_file
        else:
            # Check script directory (useful if running from subdirectory)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(script_dir, credentials_file)
            
            # If still not found, try parent directory (common in Flask apps inside web/)
            if not os.path.exists(path):
                path = os.path.join(os.path.dirname(script_dir), credentials_file)

        with open(path, "r") as f:
            creds = json.load(f)
        
        key = creds.get("GEMINI_API_KEY")
        if not key:
             print(f"ERROR: GEMINI_API_KEY not found in {path}")
             return None
             
        return key

    except FileNotFoundError:
        print(f"ERROR: {credentials_file} not found in {os.getcwd()} or parent directories!")
        return None
    except Exception as e:
        print(f"ERROR loading API Key: {e}")
        return None

import json
import re
import time
import sys
import logging
from pathlib import Path
from google import genai
from google.genai import types
from .config import get_api_key, GEMINI_MODEL

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self, model_name=GEMINI_MODEL):
        self.api_key = get_api_key()
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in credentials.json or environment.")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name

    def upload_file(self, file_path: Path, display_name: str = None):
        """Uploads a file to Google File API and returns the file object."""
        try:
            # Correct SDK syntax for uploading files
            file = self.client.files.upload(
                file=str(file_path),
                config=types.UploadFileConfig(display_name=display_name or file_path.name)
            )
            logger.info(f"File uploaded to Gemini: {file.uri}")
            return file
        except Exception as e:
            logger.error(f"Failed to upload file to Gemini: {e}")
            return None

    def delete_file(self, file_name: str):
        """Removes a file from Google File API."""
        try:
            self.client.files.delete(name=file_name)
            logger.info(f"File deleted from Gemini: {file_name}")
        except Exception as e:
            logger.error(f"Failed to delete file from Gemini: {e}")

    def generate_json(self, contents, retry_count=3):
        """Generates a structured JSON response. 'contents' can be a string or SDK types."""
        backoff = 5
        # Normalize to Content object if string
        if isinstance(contents, str):
            contents = types.Content(role="user", parts=[types.Part.from_text(text=contents)])
            
        for attempt in range(retry_count):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                text = response.text
                
                # Clean up markdown code blocks if Gemini accidentally includes them
                if text.startswith("```json"):
                    text = re.sub(r'^```json\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                elif text.startswith("```"):
                    text = re.sub(r'^```\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON Decode failed, attempting repair: {e}")
                    
                    # 1. Try to fix unescaped backslashes (most common in LaTeX)
                    # We look for \ that isn't part of a standard JSON escape sequence
                    import re
                    repaired = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', text)
                    try:
                        return json.loads(repaired)
                    except:
                        # 2. Try replacing ALL single backslashes with double, then fixing double-doubles
                        repaired2 = text.replace('\\', '\\\\').replace('\\\\\\\\', '\\\\')
                        # But ensure quotes remain correctly escaped
                        repaired2 = repaired2.replace('\\\\"', '\\"')
                        try:
                            return json.loads(repaired2)
                        except Exception as e2:
                            logger.error(f"JSON repair failed completely: {e2}")
                            logger.debug(f"Raw text: {text}")
                            return None
            except Exception as e:
                if '429' in str(e) and attempt < retry_count - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"[AI Error] Attempt {attempt+1} failed: {e}")
                if attempt == retry_count - 1:
                    return None
        return None

    def generate_text(self, prompt):
        """Generates plain text response."""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"[AI Error] {e}", file=sys.stderr)
            return None

# Global instance
ai = AIService()

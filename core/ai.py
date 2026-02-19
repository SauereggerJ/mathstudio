import json
import re
import time
import sys
from google import genai
from google.genai import types
from .config import get_api_key, GEMINI_MODEL

class AIService:
    def __init__(self, model_name=GEMINI_MODEL):
        self.api_key = get_api_key()
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in credentials.json or environment.")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name

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
                return json.loads(response.text)
            except Exception as e:
                import traceback
                traceback.print_exc()
                if '429' in str(e) and attempt < retry_count - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                print(f"[AI Error] Attempt {attempt+1} failed: {e}", file=sys.stderr)
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

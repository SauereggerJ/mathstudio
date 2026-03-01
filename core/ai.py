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

    def generate_json(self, contents, retry_count=5, schema=None):
        """Generates a structured JSON response. 'contents' can be a string or SDK types.
        If schema is provided, it is passed to the API as response_schema for structured output."""
        backoff = 10
        # Normalize to Content object if string
        if isinstance(contents, str):
            contents = types.Content(role="user", parts=[types.Part.from_text(text=contents)])
            
        for attempt in range(retry_count):
            try:
                gen_config = types.GenerateContentConfig(response_mime_type="application/json")
                if schema:
                    gen_config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema
                    )
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=gen_config
                )
                
                # Check for non-STOP finish reasons (SAFETY, RECITATION, MAX_TOKENS, etc.)
                try:
                    finish_reason = response.candidates[0].finish_reason if response.candidates else None
                    if finish_reason and str(finish_reason) not in ('FinishReason.STOP', 'STOP', '1', 'None'):
                        logger.error(f"[AI] Generation blocked — finish_reason: {finish_reason}. Safety/policy refusal.")
                        return None
                except Exception:
                    pass

                text = response.text
                
                # DEBUG LOGGING: Write raw response to the NAS for guaranteed visibility
                try:
                    with open("/home/jure/nasi_data/math/New_Research_Library/mathstudio/ai_debug_raw.log", "w") as f:
                        f.write(text)
                except:
                    pass

                # Clean up markdown code blocks if Gemini accidentally includes them
                if text.startswith("```json"):
                    text = re.sub(r'^```json\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                elif text.startswith("```"):
                    text = re.sub(r'^```\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                
                # SANITIZATION: Strip only the most problematic control chars (0-8, 11-12, 14-31)
                # Keep \n (10), \r (13), \t (9) as strict=False below will handle them in strings.
                # This fixes errors like the Vertical Tab (\x0b / 11) found on Page 232.
                text = "".join(char for char in text if ord(char) >= 32 or char in "\n\r\t")

                try:
                    # strict=False allows literal control characters (like real tabs/newlines) inside strings
                    return json.loads(text, strict=False)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON Decode failed, attempting repair: {e}")
                    
                    # 1. Aggressive backslash repair for LaTeX
                    # In LaTeX, almost every \ should be realized as a literal backslash.
                    # We double any \ that isn't already part of a valid JSON escape (\", \\, \/)
                    # or a unicode escape (\uXXXX).
                    import re
                    # We don't exclude b,f,n,r,t here because in LaTeX \textbf, \newline etc. 
                    # they are usually meant as literal backslashes, and if the AI wanted 
                    # a real newline it would use a literal LF or a double-escaped \\n.
                    repaired = re.sub(r'\\(?!["\\/]|u[0-9a-fA-F]{4})', r'\\\\', text)
                    
                    try:
                        return json.loads(repaired, strict=False)
                    except Exception as e2:
                        # 2. Last resort: Total backslash doubling
                        repaired2 = text.replace('\\', '\\\\').replace('\\\\\\\\', '\\\\').replace('\\\\"', '\\"')
                        try:
                            return json.loads(repaired2, strict=False)
                        except Exception as e3:
                            logger.error(f"JSON repair failed completely: {e3}")
                            # Write the problematic response to the debug log for inspection
                            try:
                                with open("/home/jure/nasi_data/math/New_Research_Library/mathstudio/ai_debug_raw.log", "a") as f:
                                    f.write(f"\n\n=== JSON REPAIR FAILURE ===\n{text[:2000]}\n")
                            except Exception:
                                pass
                            return None
            except Exception as e:
                err_str = str(e)
                if ('429' in err_str or '503' in err_str) and attempt < retry_count - 1:
                    logger.warning(f"[AI] Rate/capacity limit hit (attempt {attempt+1}), backing off {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"[AI Error] Attempt {attempt+1} failed: {e}")
                if attempt == retry_count - 1:
                    return None
        return None

    def generate_text(self, prompt, retry_count=3):
        """Generates plain text response with basic retry logic."""
        backoff = 10
        for attempt in range(retry_count):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text
            except Exception as e:
                err_str = str(e)
                if ('429' in err_str or '503' in err_str) and attempt < retry_count - 1:
                    logger.warning(f"[AI Text] Rate/capacity limit hit (attempt {attempt+1}), backing off {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                print(f"[AI Error] {e}", file=sys.stderr)
                if attempt == retry_count - 1:
                    return None
        return None

# Global instance
ai = AIService()

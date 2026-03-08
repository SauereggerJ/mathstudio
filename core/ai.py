import json
import re
import time
import sys
import logging
from pathlib import Path
from google import genai
from google.genai import types

from .config import GEMINI_API_KEY, DEEPSEEK_API_KEY, GEMINI_MODEL, AI_ROUTING_POLICY

logger = logging.getLogger(__name__)

class AIProvider:
    def upload_file(self, file_path: Path, display_name: str = None):
        raise NotImplementedError
    def delete_file(self, file_name: str):
        raise NotImplementedError
    def generate_json(self, contents, retry_count=5, schema=None):
        raise NotImplementedError
    def generate_text(self, prompt, retry_count=3):
        raise NotImplementedError
    def generate_xml_blocks(self, prompt_or_contents, tag: str, retry_count=3):
        raise NotImplementedError

class GeminiProvider(AIProvider):
    def __init__(self, model_name=GEMINI_MODEL):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not found in credentials.json or environment.")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model_name = model_name

    def upload_file(self, file_path: Path, display_name: str = None):
        try:
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
        try:
            self.client.files.delete(name=file_name)
            logger.info(f"File deleted from Gemini: {file_name}")
        except Exception as e:
            logger.error(f"Failed to delete file from Gemini: {e}")

    def generate_json(self, contents, retry_count=5, schema=None):
        backoff = 10
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
                
                try:
                    finish_reason = response.candidates[0].finish_reason if response.candidates else None
                    if finish_reason and str(finish_reason) not in ('FinishReason.STOP', 'STOP', '1', 'None'):
                        logger.error(f"[Gemini] Generation blocked — finish_reason: {finish_reason}.")
                        return None
                except Exception:
                    pass

                text = response.text
                
                try:
                    with open("/home/jure/nasi_data/math/New_Research_Library/mathstudio/ai_debug_raw.log", "w") as f:
                        f.write(text)
                except:
                    pass

                if text.startswith("```json"):
                    text = re.sub(r'^```json\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                elif text.startswith("```"):
                    text = re.sub(r'^```\s*', '', text)
                    text = re.sub(r'\s*```$', '', text)
                
                # Strip problematic control chars (0-8, 11-12, 14-31)
                text = "".join(char for char in text if ord(char) >= 32 or char in "\n\r\t")

                try:
                    return json.loads(text, strict=False)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON Decode failed, attempting repair: {e}")
                    repaired = re.sub(r'\\(?!["\\/]|u[0-9a-fA-F]{4})', r'\\\\', text)
                    try:
                        return json.loads(repaired, strict=False)
                    except Exception:
                        repaired2 = text.replace('\\', '\\\\').replace('\\\\\\\\', '\\\\').replace('\\\\"', '\\"')
                        try:
                            return json.loads(repaired2, strict=False)
                        except Exception as e3:
                            logger.error(f"JSON repair failed completely.")
                            return None
            except Exception as e:
                err_str = str(e)
                if ('429' in err_str or '503' in err_str) and attempt < retry_count - 1:
                    logger.warning(f"[Gemini] Rate limit hit, backing off {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"[Gemini] Error (Attempt {attempt+1}): {e}")
                if attempt == retry_count - 1:
                    return None
        return None

    def generate_text(self, prompt, retry_count=3):
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
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                if attempt == retry_count - 1:
                    return None
        return None

    def generate_xml_blocks(self, prompt_or_contents, tag: str, retry_count=3):
        # Instruct Gemini to output delimited tags
        if isinstance(prompt_or_contents, str):
            prompt_or_contents += f"\n\nIMPORTANT: Output your result wrapped EXACTLY within <{tag}> and </{tag}> delimiters."
        elif isinstance(prompt_or_contents, list):
            # Append string to the last text part
            last_content = prompt_or_contents[-1]
            if hasattr(last_content, 'parts') and len(last_content.parts) > 0:
                last_content.parts.append(types.Part.from_text(text=f"\n\nIMPORTANT: Output your result wrapped EXACTLY within <{tag}> and </{tag}> delimiters."))

        raw_text = self.generate_text(prompt_or_contents, retry_count=retry_count)
        if not raw_text: return []

        # Find all blocks matching <tag>...</tag>
        pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)
        matches = pattern.findall(raw_text)
        return [m.strip() for m in matches]


class DeepSeekProvider(AIProvider):
    def __init__(self, model_name="deepseek-chat"):
        import openai
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY not found.")
        self.client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=60.0)
        self.model_name = model_name

    def _to_string_prompt(self, contents):
        # DeepSeek doesn't support Gemini's multimodal types.Content. 
        # Attempt to extract purely the text.
        if isinstance(contents, str):
            return contents
        
        extracted_text = []
        if isinstance(contents, list):
            for c in contents:
                if hasattr(c, 'parts'):
                    for p in c.parts:
                        if hasattr(p, 'text') and p.text:
                            extracted_text.append(p.text)
        return "\n".join(extracted_text)

    def upload_file(self, file_path: Path, display_name: str = None):
        logger.warning("DeepSeek Provider does not support File Uploads natively.")
        return None

    def delete_file(self, file_name: str):
        pass

    def generate_json(self, contents, retry_count=5, schema=None):
        prompt = self._to_string_prompt(contents)
        prompt += "\nOutput strict JSON."
        
        backoff = 10
        for attempt in range(retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                text = response.choices[0].message.content
                
                try:
                    with open("/home/jure/nasi_data/math/New_Research_Library/mathstudio/ai_debug_raw.log", "w") as f:
                        f.write(text)
                except:
                    pass
                
                return json.loads(text, strict=False)
            except Exception as e:
                if attempt < retry_count - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"[DeepSeek] Error generating JSON: {e}")
                return None
        return None

    def generate_text(self, prompt, retry_count=3):
        prompt_str = self._to_string_prompt(prompt)
        backoff = 10
        for attempt in range(retry_count):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt_str}]
                )
                return response.choices[0].message.content
            except Exception as e:
                if attempt < retry_count - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"[DeepSeek] Error generating text: {e}")
                return None
        return None

    def generate_xml_blocks(self, prompt_or_contents, tag: str, retry_count=3):
        prompt_str = self._to_string_prompt(prompt_or_contents)
        prompt_str += f"\n\nIMPORTANT: Output your result wrapped EXACTLY within <{tag}> and </{tag}> delimiters. Do not use Markdown formatting for the wrapper, just the raw XML tags."
        
        raw_text = self.generate_text(prompt_str, retry_count=retry_count)
        if not raw_text: return []

        pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)
        matches = pattern.findall(raw_text)
        return [m.strip() for m in matches]


class AIService:
    def __init__(self, routing_policy=AI_ROUTING_POLICY):
        self.routing_policy = routing_policy
        self.gemini = GeminiProvider()
        self.deepseek = None
        if self.routing_policy == "dual_stack" and DEEPSEEK_API_KEY:
            try:
                self.deepseek = DeepSeekProvider()
            except Exception as e:
                logger.error(f"Failed to load DeepSeek: {e}")

    @property
    def client(self):
        # Fallback to Gemini's client for scripts that access ai.client... directly
        return self.gemini.client

    def _is_multimodal(self, contents):
        if isinstance(contents, str): return False
        if isinstance(contents, list):
            for content in contents:
                # Handle types.Content objects
                if hasattr(content, 'parts'):
                    for part in content.parts:
                        # Check for file_data (URI-based)
                        file_data = getattr(part, 'file_data', None)
                        if file_data and getattr(file_data, 'file_uri', None):
                            return True
                        # Check for inline_data (bytes-based)
                        if getattr(part, 'inline_data', None):
                            return True
                # Handle raw parts list if passed directly
                elif hasattr(content, 'file_data') or hasattr(content, 'inline_data'):
                    if getattr(content, 'file_data', None) and getattr(content.file_data, 'file_uri', None):
                        return True
                    if getattr(content, 'inline_data', None):
                        return True
        return False

    def upload_file(self, *args, **kwargs):
        return self.gemini.upload_file(*args, **kwargs)

    def delete_file(self, *args, **kwargs):
        return self.gemini.delete_file(*args, **kwargs)

    def generate_json(self, contents, retry_count=5, schema=None):
        if self.routing_policy == "dual_stack" and self.deepseek and not self._is_multimodal(contents):
            logger.info("Routing JSON request to DeepSeek")
            return self.deepseek.generate_json(contents, retry_count, schema)
        logger.info("Routing JSON request to Gemini")
        return self.gemini.generate_json(contents, retry_count, schema)

    def generate_text(self, prompt, retry_count=3):
        if self.routing_policy == "dual_stack" and self.deepseek and not self._is_multimodal(prompt):
            logger.info("Routing Text request to DeepSeek")
            return self.deepseek.generate_text(prompt, retry_count)
        logger.info("Routing Text request to Gemini")
        return self.gemini.generate_text(prompt, retry_count)

    def generate_xml_blocks(self, prompt_or_contents, tag: str, retry_count=3):
        if self.routing_policy == "dual_stack" and self.deepseek and not self._is_multimodal(prompt_or_contents):
            logger.info("Routing XML requests to DeepSeek")
            return self.deepseek.generate_xml_blocks(prompt_or_contents, tag, retry_count)
        logger.info("Routing XML requests to Gemini")
        return self.gemini.generate_xml_blocks(prompt_or_contents, tag, retry_count)

# Global singleton instance
ai = AIService()

import os
import json
from models.base_model import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
from core.sanitizer import extract_json_from_text, clean_code_by_language

load_dotenv()


class GeminiModel(BaseModel):
    """
    Concrete implementation of BaseModel for Google's Gemini Cloud API.
    Used primarily as a highly capable fallback model.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash", api_key: str = None,
                 timeout: float = 60.0, max_output_tokens: int = 8192):
        self.model_name = model_name
        self.max_output_tokens = max_output_tokens
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")

        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY not found. Set it in .env or pass it directly.")

        self.client = genai.Client(
            api_key=resolved_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # milliseconds
        )

    def generate_fix(self, prompt: str, language: str = "python") -> str:
        """
        Sends the prompt to the Gemini API, enforcing and validating JSON structure.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=self.max_output_tokens,  # 2048 truncated multi-candidate JSON
                )
            )
            raw_response = response.text
        except Exception as e:
            raise Exception(f"Gemini API request failed: {e}")

        # Return raw JSON string; agent.py parses candidate_1/2/3
        # No extra sanitize pass — avoids Python-specific cleanup breaking C++/Java
        from core.sanitizer import _strip_bos_artifacts
        return _strip_bos_artifacts(raw_response) if raw_response else raw_response

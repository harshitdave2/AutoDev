import os
import json
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError
from models.base_model import BaseModel
from core.sanitizer import extract_json_from_text, clean_code_by_language

# Load environment variables
load_dotenv()

class QuotaError(Exception):
    """Structured exception for 429 Rate Limits and Quota Exhaustion."""
    pass

class GroqModel(BaseModel):
    """
    Concrete implementation of BaseModel for Groq's high-speed inference cloud.
    """
    def __init__(self, model_name: str = "llama-3.3-70b-versatile", api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found. Set it in .env or pass it directly.")
            
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1"
        )

    def generate_fix(self, prompt: str, language: str = "python") -> str:
        """
        Sends the prompt to Groq, handling model deprecation and quota limits safely.
        """
        try:
            return self._call_api(self.model_name, prompt, language)
        except Exception as e:
            error_str = str(e).lower()
            
            # 1. Handle Decommissioned Models Seamlessly
            if "model_decommissioned" in error_str or "not found" in error_str:
                self.model_name = "llama-3.3-70b-versatile"
                try:
                    return self._call_api(self.model_name, prompt, language)
                except Exception as retry_e:
                    self._handle_error(retry_e)
            else:
                self._handle_error(e)

    def _handle_error(self, e: Exception):
        """Standardizes API errors to prevent orchestrator crashes."""
        error_str = str(e).lower()
        
        # 2. Handle Quota/Rate Limits
        if isinstance(e, RateLimitError) or "429" in error_str or "quota" in error_str:
            raise QuotaError("Groq unavailable (quota exceeded).")
            
        # 3. Raise Structured Exception (first line only to keep logs clean)
        clean_msg = str(e).split('\n')[0][:100]
        raise Exception(f"Groq API request failed: {type(e).__name__} - {clean_msg}")

    def _call_api(self, target_model: str, prompt: str, language: str) -> str:
        """Internal method to execute the actual HTTP request."""
        response = self.client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        raw_response = response.choices[0].message.content

        # Return the raw JSON string; agent.py will parse candidate_1/2/3
        # No extra sanitize pass — avoids Python-specific cleanup breaking C++/Java
        from core.sanitizer import _strip_bos_artifacts
        return _strip_bos_artifacts(raw_response) if raw_response else raw_response
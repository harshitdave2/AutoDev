import os
import json
from models.base_model import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
from core.sanitizer import extract_json_from_text, clean_python_code

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in environment or .env file.")


class GeminiModel(BaseModel):
    """
    Concrete implementation of BaseModel for Google's Gemini Cloud API.
    Used primarily as a highly capable fallback model.
    """

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not set. Please set it to use the Gemini fallback.")

        # ← CHANGED: Client-based init instead of genai.configure()
        self.client = genai.Client(api_key=api_key)

    def generate_fix(self, prompt: str) -> str:
        """
        Sends the prompt to the Gemini API, enforcing and validating JSON structure.
        """
        try:
            # ← CHANGED: new client call with GenerateContentConfig
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=2048,
                )
            )
            raw_response = response.text
        except Exception as e:
            raise Exception(f"Gemini API request failed: {e}")

        # Safely parse the JSON to ensure the model obeyed instructions
        clean_json = extract_json_from_text(raw_response)

        try:
            parsed_data = json.loads(clean_json)
        except json.JSONDecodeError:
            raise Exception(f"Gemini did not return valid JSON. Raw output: {raw_response}")

        if "fixed_code" not in parsed_data:
            raise Exception("Gemini returned JSON, but 'fixed_code' key is missing.")

        clean_code = clean_python_code(parsed_data["fixed_code"])

        return clean_code
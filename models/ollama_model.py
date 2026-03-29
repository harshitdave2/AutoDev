import requests
import json
from models.base_model import BaseModel
from core.sanitizer import extract_json_from_text, clean_python_code


class OllamaModel(BaseModel):
    """
    Concrete implementation of BaseModel for local Ollama instances.
    """

    def __init__(self, model_name: str = "qwen2.5-coder:7b-instruct-q4_K_M",
                 url: str = "http://localhost:11434/api/generate"):
        self.model_name = model_name
        self.url = url

    def generate_fix(self, prompt: str) -> str:
        """
        Sends the prompt to the local Ollama API and enforces JSON formatting.
        """

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }

        import time
        for attempt in range(3):
            try:
                response = requests.post(self.url, json=payload, timeout=120)
                response.raise_for_status()
                break  # Success
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    raise Exception(f"Failed to connect to Ollama after 3 retries. Is the server running? Error: {e}")
                time.sleep(2)  # Short delay before retrying

        # Raw LLM output
        raw_response = response.json().get("response", "")

        # NEW: sanitize raw text before parsing
        clean_json = extract_json_from_text(raw_response)

        try:
            parsed_data = json.loads(clean_json)
        except json.JSONDecodeError:
            raise Exception(f"Model did not return valid JSON. Raw output: {raw_response}")

        if "fixed_code" not in parsed_data:
            raise Exception("Model returned JSON but 'fixed_code' key is missing.")

        # NEW: sanitize python code
        clean_code = clean_python_code(parsed_data["fixed_code"])

        return clean_code
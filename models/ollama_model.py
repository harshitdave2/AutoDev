"""
models/ollama_model.py
-----------------------
Concrete BaseModel implementation for local Ollama instances.

Speed-first changes (v2):
  - Timeout is configurable via autodev_config.json (key: local_timeout).
    Defaults to 45 seconds instead of the old 120s.
  - Inner retry loop removed — the outer retry_manager loop handles retries.
    One attempt per call; retry_manager will call again if needed.
  - [ModelTimeout] log on timeout for visibility.
"""
import json
import os
import requests

from models.base_model import BaseModel
from core.sanitizer import _strip_bos_artifacts


def _load_local_timeout() -> int:
    """Read local_timeout from autodev_config.json if available."""
    config_candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'autodev_config.json'),
        'autodev_config.json',
    ]
    for path in config_candidates:
        path = os.path.abspath(path)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                return int(cfg.get('local_timeout', 45))
            except Exception:
                pass
    return 45  # Safe default


class OllamaModel(BaseModel):
    """
    Concrete implementation of BaseModel for local Ollama instances.
    """

    def __init__(
        self,
        model_name: str = "qwen2.5-coder:7b-instruct-q4_K_M",
        url: str = "http://localhost:11434/api/generate",
        timeout: int = None,
    ):
        self.model_name = model_name
        self.url = url
        # Use provided timeout, then config file value, then hard default
        self.timeout = timeout if timeout is not None else _load_local_timeout()

    def generate_fix(self, prompt: str, language: str = "python") -> str:
        """
        Sends the prompt to the local Ollama API and enforces JSON formatting.
        Single attempt — caller (retry_manager) handles retry policy.
        """
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }

        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            print(
                f"[ModelTimeout] Ollama timed out after {self.timeout}s "
                f"(model={self.model_name}). Failing over."
            )
            raise Exception(
                f"Ollama timeout after {self.timeout}s — model {self.model_name} too slow"
            )
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to Ollama: {e}")

        raw_response = response.json().get("response", "")

        # Strip BOS artifacts; agent.py handles further parsing
        return _strip_bos_artifacts(raw_response) if raw_response else raw_response
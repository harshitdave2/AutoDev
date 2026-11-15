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


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_local_timeout() -> int:
    """Fallback for direct OllamaModel() use: read local_timeout from the
    project's config. Deliberately does NOT consult the current working
    directory, so behaviour never depends on where the CLI was started."""
    path = os.path.join(PROJECT_ROOT, "autodev_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = int(json.load(f).get("local_timeout", 45))
        return value if value >= 1 else 45
    except (OSError, ValueError, TypeError, AttributeError):
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
        num_ctx: int = None,
    ):
        self.model_name = model_name
        self.url = url
        self.num_ctx = num_ctx
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
        if self.num_ctx:
            # Ollama silently truncates prompts beyond its context window; let
            # the config raise it to match the configured context budget.
            payload["options"] = {"num_ctx": int(self.num_ctx)}

        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout:
            print(
                f"[ModelTimeout] Ollama timed out after {self.timeout}s "
                f"(model={self.model_name}). Failing over."
            )
            raise Exception(
                f"Ollama timeout after {self.timeout}s - model {self.model_name} too slow"
            )
        except requests.exceptions.ConnectionError as e:
            raise Exception(
                f"Cannot reach Ollama at {self.url}. Is it running (`ollama serve`)? ({e})"
            )
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ollama request failed: {e}")

        if response.status_code == 404:
            raise Exception(
                f"Ollama model '{self.model_name}' not found. "
                f"Run `ollama pull {self.model_name}`."
            )
        if not response.ok:
            body = (response.text or "").strip().replace("\n", " ")[:200]
            raise Exception(f"Ollama returned HTTP {response.status_code}: {body}")

        try:
            raw_response = response.json().get("response", "")
        except ValueError:
            raise Exception("Ollama returned a non-JSON HTTP response.")

        # Strip BOS artifacts; agent.py handles further parsing
        return _strip_bos_artifacts(raw_response) if raw_response else raw_response

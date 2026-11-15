"""Load configured repair models using paths relative to this module's project."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from models.model_orchestrator import ModelOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "autodev_config.json"


def load_model(config_path=None):
    config_file = Path(config_path).expanduser().resolve() if config_path else DEFAULT_CONFIG
    if not config_file.is_file():
        raise FileNotFoundError(
            f"AutoDev configuration not found: {config_file}. "
            "Create autodev_config.json from the provided example."
        )
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    try:
        with config_file.open(encoding="utf-8") as stream:
            cfg = json.load(stream)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_file}: {exc}") from exc

    if not isinstance(cfg, dict):
        raise ValueError("AutoDev configuration must contain a JSON object.")

    models = []
    model_errors = []

    if cfg.get("ollama_model"):
        try:
            from models.ollama_model import OllamaModel
            models.append(OllamaModel(cfg["ollama_model"]))
        except Exception as exc:
            model_errors.append(f"Ollama: {exc}")

    api_keys = cfg.get("api_keys") or {}
    if not isinstance(api_keys, dict):
        raise ValueError("The 'api_keys' configuration value must be an object.")

    groq_key = api_keys.get("groq") or os.getenv("GROQ_API_KEY")
    gemini_key = api_keys.get("gemini") or os.getenv("GEMINI_API_KEY")

    if cfg.get("groq_model") and groq_key:
        try:
            from models.groq_model import GroqModel
            models.append(GroqModel(cfg["groq_model"], groq_key))
        except Exception as exc:
            model_errors.append(f"Groq: {exc}")

    if cfg.get("gemini_model") and gemini_key:
        try:
            from models.gemini_model import GeminiModel
            models.append(GeminiModel(cfg["gemini_model"], gemini_key))
        except Exception as exc:
            model_errors.append(f"Gemini: {exc}")

    if not models:
        detail = "; ".join(model_errors) if model_errors else "No model provider is configured."
        raise RuntimeError(
            f"AutoDev could not initialize any model. {detail} "
            "Configure Ollama or provide a valid cloud API key."
        )

    return ModelOrchestrator(
        models,
        timeout=int(cfg.get("cloud_timeout", 60)),
        per_model_retries=int(cfg.get("model_retries", 1)),
    )

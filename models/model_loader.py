import json
from models.ollama_model import OllamaModel
from models.groq_model import GroqModel
from models.gemini_model import GeminiModel

from models.model_orchestrator import ModelOrchestrator

def load_model():
    with open("autodev_config.json") as f:
        cfg = json.load(f)

    models = []
    
    if cfg.get("ollama_model"):
        try:
            models.append(OllamaModel(cfg["ollama_model"]))
        except Exception:
            pass

    api_keys = cfg.get("api_keys", {})

    if cfg.get("groq_model") and api_keys.get("groq"):
        try:
            models.append(GroqModel(cfg["groq_model"], api_keys["groq"]))
        except Exception:
            pass

    if cfg.get("gemini_model") and api_keys.get("gemini"):
        try:
            models.append(GeminiModel(cfg["gemini_model"], api_keys["gemini"]))
        except Exception:
            pass

    return ModelOrchestrator(models)

from models.base_model import BaseModel

class ModelRouter(BaseModel):
    """
    Acts as a middleman that attempts a generation with a primary local model,
    and seamlessly routes to a fallback cloud model if the primary critically fails.
    """
    def __init__(self, primary: BaseModel, fallback: BaseModel):
        self.primary = primary
        self.fallback = fallback

    def generate_fix(self, prompt: str) -> str:
        """
        Attempts the fix with the primary model. Escalates to fallback on failure.
        """
        try:
            # Try to get the fix from the primary (e.g., local Ollama)
            return self.primary.generate_fix(prompt)
        except Exception as e:
            # If the primary model fails entirely (e.g., Ollama is down or crashed), use fallback
            print(f"\n[!] Primary model failed: {e}. Routing to fallback model...")
            return self.fallback.generate_fix(prompt)
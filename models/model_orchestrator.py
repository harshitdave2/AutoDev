import ast
from models.base_model import BaseModel
from concurrent.futures import ThreadPoolExecutor, as_completed

class ModelOrchestrator(BaseModel):
    """
    Acts as an intelligent load-balancer. It attempts a generation with a priority 
    list of models, seamlessly failing over to the next if a model crashes, 
    hits a quota, or hallucinates bad syntax.
    """
    def __init__(self, models: list[BaseModel] = None):
        self.models = models if models is not None else []
        self.last_successful_model = "Multiple Models"

    def generate_fix(self, prompt: str) -> str:
        raise NotImplementedError("Use generate_parallel instead")
        
    def generate_parallel(self, prompt: str) -> list[str]:
        if not self.models:
            raise Exception("No cloud models available to orchestrate.")

        results = []
        
        def run_model(model):
            model_name = getattr(model, 'model_name', model.__class__.__name__)
            try:
                print(f"    [dim]➔ Routing request to: {model_name}...[/dim]")
                result = model.generate_fix(prompt)
                
                # Check if we at least got some valid output via the sanitizer
                from core.sanitizer import sanitize_llm_output
                if not sanitize_llm_output(result):
                    raise ValueError("Model hallucinated empty or invalid format")
                
                print(f"    [dim]✔ {model_name} successfully generated valid code structure.[/dim]")
                return result
                
            except Exception as e:
                error_str = str(e).lower()
                error_class = e.__class__.__name__
                
                # Format the provider name (e.g., GeminiModel -> Gemini)
                provider = model.__class__.__name__.replace("Model", "")
                
                # Handle Quota / Rate Limits cleanly without raw error blobs
                if "429" in error_str or "quota" in error_str or error_class == "QuotaError":
                    print(f"    [bold yellow]⚠ {provider} unavailable (quota exceeded).[/bold yellow]")
                else:
                    # Strip huge tracebacks into a single clean line
                    simplified_msg = str(e).split('\n')[0][:120]
                    print(f"    [dim]✖ {model_name} failed: {simplified_msg}[/dim]")
                return None

        with ThreadPoolExecutor(max_workers=len(self.models)) as executor:
            futures = [executor.submit(run_model, m) for m in self.models]
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    results.append(res)
                    
        return results
class BaseModel:
    """
    Abstract base class for all AI models in the AutoDev framework.
    Ensures a consistent interface whether using local LLMs or Cloud APIs.
    """

    def generate_fix(self, prompt: str) -> str:
        """
        Generates a code fix based on the provided prompt.

        Args:
            prompt (str): The strictly formatted prompt containing context and instructions.

        Returns:
            str: A JSON string containing the 'fixed_code' key.

        Raises:
            NotImplementedError: If the child class does not implement this method.
        """
        raise NotImplementedError("Subclasses must implement generate_fix()")
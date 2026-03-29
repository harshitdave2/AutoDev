import json
import os
from datetime import datetime

class BugMemory:
    """
    Stores and retrieves past bug fixes to allow the AI to learn from previous solutions.
    Uses a JSON file for persistent storage across sessions.
    """
    
    def __init__(self, filepath="autodev_memory.json"):
        """
        Initializes the BugMemory system.
        
        Args:
            filepath (str): The path to the JSON database file.
        """
        self.filepath = filepath
        self.memory = []
        self.load_memory()

    def load_memory(self):
        """
        Loads the JSON database from disk. 
        Creates an empty JSON file if it does not exist.
        """
        if not os.path.exists(self.filepath):
            self.memory = []
            self.save_memory()
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.memory = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # Handle corrupted or unreadable JSON safely
            print(f"Warning: Could not read memory file ({e}). Initializing empty memory.")
            self.memory = []

    def save_memory(self):
        """
        Writes memory to disk safely.
        Uses a temporary file and an atomic rename to prevent file corruption 
        if the process is interrupted during the write operation.
        """
        temp_filepath = f"{self.filepath}.tmp"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=4)
            
            # Atomic replacement ensures file-locking safety and prevents data loss
            os.replace(temp_filepath, self.filepath)
        except IOError as e:
            print(f"Error saving bug memory: {e}")
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except OSError:
                    pass

    def store_fix(self, error_type: str, file_hash: str, function_signature: str, bug_code: str, fixed_code: str):

        # Prevent duplicate entries
        for entry in self.memory:
            if (
                entry["error_type"] == error_type and
                entry["function_signature"] == function_signature and
                entry["bug_code"] == bug_code
            ):
                return

        entry = {
            "error_type": error_type,
            "file_hash": file_hash,
            "function_signature": function_signature,
            "bug_code": bug_code,
            "fixed_code": fixed_code,
            "timestamp": datetime.now().isoformat()
        }

        self.memory.append(entry)
        self.save_memory()

    def retrieve_fix(self, error_type: str, function_signature: str) -> str | None:
        """
        Retrieves a past fix if it closely matches the current issue.
        
        Similarity Rule:
        Returns the fixed code when both the error_type and function_signature match.
        
        Returns:
            str: The fixed Python code if a match is found, otherwise None.
        """
        # Iterate backwards to prioritize the most recently stored fixes
        for entry in reversed(self.memory):
            if entry.get("error_type") == error_type and entry.get("function_signature") == function_signature:
                return entry.get("fixed_code")
                
        return None
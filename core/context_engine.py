import ast
import os
import re

class ContextEngine:
    """
    Extracts deep, multi-level context from source code to improve AI reasoning.
    Designed for Phase 3 integration to expand beyond single-function fixes.
    """

    @staticmethod
    def get_crashing_function(file_path: str, crash_line: int) -> str:
        """Finds and extracts the exact function or class containing the crash line."""
        if not os.path.exists(file_path):
            return ""
            
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ""
            
        lines = source.splitlines()
        best_node = None
        min_size = float('inf')
        
        # Walk the AST to find the tightest wrapping function/class around the line
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                    if node.lineno <= crash_line <= node.end_lineno:
                        size = node.end_lineno - node.lineno
                        if size < min_size:
                            min_size = size
                            best_node = node
                            
        if best_node:
            # -1 because AST lines are 1-indexed but Python lists are 0-indexed
            return "\n".join(lines[best_node.lineno - 1 : best_node.end_lineno])
        
        # Fallback to returning a raw code snippet if no function wraps the line
        start = max(0, crash_line - 5)
        end = min(len(lines), crash_line + 5)
        return "\n".join(lines[start:end])

    @staticmethod
    def get_caller_functions(file_path: str, traceback_str: str) -> list[str]:
        """Extracts the functions that called the crashing function based on the traceback stack."""
        callers = []
        # Look for all stack frames in the traceback
        pattern = r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+)'
        matches = re.findall(pattern, traceback_str)
        
        # The last match is the crash site. Callers are the preceding matches.
        if len(matches) > 1:
            for match in matches[:-1]:
                match_file, match_line, match_func = match
                
                # Ignore global module calls, only fetch actual functions in the same file
                if match_func != '<module>' and os.path.abspath(match_file) == os.path.abspath(file_path):
                    caller_src = ContextEngine.get_crashing_function(match_file, int(match_line))
                    if caller_src and caller_src not in callers:
                        callers.append(caller_src)
                        
        return callers

    @classmethod
    def build_expanded_context(cls, file_path: str, crash_line: int, traceback_str: str) -> dict:
        """
        Builds a comprehensive dictionary containing the crashing function,
        its callers, and a formatted expanded string for the AI prompt.
        """
        crashing_func = cls.get_crashing_function(file_path, crash_line)
        callers = cls.get_caller_functions(file_path, traceback_str)
        
        # Assemble the final context string for the prompt
        context_block = f"--- CRASHING FUNCTION ---\n{crashing_func}\n"
        if callers:
            context_block += "\n--- CALLER FUNCTION(S) ---\n"
            for i, caller in enumerate(callers, 1):
                context_block += f"// Caller {i}\n{caller}\n"
                
        return {
            "crashing_function": crashing_func,
            "caller_functions": callers,
            "has_callers": len(callers) > 0,
            "expanded_context_block": context_block
        }
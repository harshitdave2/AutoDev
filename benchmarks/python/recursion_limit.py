"""
benchmarks/python/recursion_limit.py
Bug: RecursionError — missing base case in recursive flatten
"""

def flatten(lst):
    # BUG: No base case — will recurse forever on non-list elements
    result = []
    for item in lst:
        result.extend(flatten(item))  # Crashes on non-list items
    return result

if __name__ == "__main__":
    nested = [1, [2, 3], [4, [5, 6]], 7]
    flat = flatten(nested)
    print("Flattened:", flat)

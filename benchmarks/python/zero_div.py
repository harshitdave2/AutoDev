"""
benchmarks/python/zero_div.py
Bug: ZeroDivisionError — divides without zero check
"""

def compute_ratio(numerator, denominator):
    # BUG: no zero-check on denominator
    return numerator / denominator

def safe_ratio_list(pairs):
    results = []
    for a, b in pairs:
        results.append(compute_ratio(a, b))
    return results

if __name__ == "__main__":
    test_pairs = [(10, 2), (15, 3), (7, 0), (20, 4)]
    ratios = safe_ratio_list(test_pairs)
    print("Ratios:", ratios)
    print("Average ratio:", sum(ratios) / len(ratios))

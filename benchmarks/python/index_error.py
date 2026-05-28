"""
benchmarks/python/index_error.py
Bug: IndexError — accesses index len(lst) which is out of bounds
"""

def get_last_three(lst):
    n = len(lst)
    # BUG: should be n-1, n-2, n-3 not n, n-1, n-2
    return [lst[n], lst[n - 1], lst[n - 2]]

def summarize(data):
    last = get_last_three(data)
    return {"last_three": last, "total": len(data)}

if __name__ == "__main__":
    data = [10, 20, 30, 40, 50, 60]
    result = summarize(data)
    print("Summary:", result)

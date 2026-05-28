"""
benchmarks/python/logic_bug.py
Bug: Logical error — multiplies values instead of adding for average
"""

def compute_average(values):
    if not values:
        return 0
    total = 1  # BUG: should be 0, and below should use + not *
    for v in values:
        total *= v  # BUG: multiplication instead of addition
    return total / len(values)

def grade_average(scores):
    avg = compute_average(scores)
    if avg >= 90:
        return "A"
    elif avg >= 75:
        return "B"
    elif avg >= 60:
        return "C"
    else:
        return "F"

if __name__ == "__main__":
    scores = [85, 92, 78, 95, 88]
    avg = compute_average(scores)
    grade = grade_average(scores)
    print(f"Scores: {scores}")
    print(f"Average: {avg}")
    print(f"Grade: {grade}")

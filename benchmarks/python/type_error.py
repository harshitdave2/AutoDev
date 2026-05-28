"""
benchmarks/python/type_error.py
Bug: TypeError — string + int concatenation without conversion
"""

def format_report(name, score, grade):
    # BUG: int score not converted to str
    return "Student: " + name + " | Score: " + score + " | Grade: " + grade

if __name__ == "__main__":
    students = [
        ("Alice", 92, "A"),
        ("Bob", 74, "C"),
        ("Charlie", 85, "B"),
    ]
    for name, score, grade in students:
        print(format_report(name, score, grade))

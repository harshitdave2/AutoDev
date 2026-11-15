def format_report(name, score, grade):
    return "Student: " + name + " | Score: " + str(score) + " | Grade: " + grade


if __name__ == "__main__":
    students = [
        ("Alice", 92, "A"),
        ("Bob", 74, "C"),
        ("Charlie", 85, "B"),
    ]
    for name, score, grade in students:
        print(format_report(name, score, grade))

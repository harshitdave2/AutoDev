def compute_average(values):
    if not values:
        return 0
    return sum(values) / len(values)


def grade_average(scores):
    avg = compute_average(scores)
    if avg >= 90:
        return "A"
    elif avg >= 75:
        return "B"
    elif avg >= 60:
        return "C"
    return "F"


if __name__ == "__main__":
    scores = [85, 92, 78, 95, 88]
    avg = compute_average(scores)
    grade = grade_average(scores)
    print(f"Scores: {scores}")
    print(f"Average: {avg}")
    print(f"Grade: {grade}")

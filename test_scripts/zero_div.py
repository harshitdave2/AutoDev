def calculate_ratio(total, count):
    return total / count


if __name__ == "__main__":
    # Intentional failure fixture for AutoDev's ZeroDivisionError repair path.
    print(calculate_ratio(10, 0))

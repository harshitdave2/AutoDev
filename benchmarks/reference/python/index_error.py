def get_last_three(values):
    n = len(values)
    return [values[n - 1], values[n - 2], values[n - 3]]


def summarize(data):
    last = get_last_three(data)
    return {"last_three": last, "total": len(data)}


if __name__ == "__main__":
    data = [10, 20, 30, 40, 50, 60]
    result = summarize(data)
    print("Summary:", result)

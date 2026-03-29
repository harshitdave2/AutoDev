def add(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return str(a) + str(b)
    else:
        return a + b

print(add(5, "10"))
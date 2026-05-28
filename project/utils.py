from math_ops import add

def do_math(x, y):
    # This should be division but causes ZeroDivisionError
    return add(x, y) / 0

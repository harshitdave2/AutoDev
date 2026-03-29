# test_scripts/complex_bug.py

def divide_and_index(numbers, index):
    value = numbers[index]
    return value / len(numbers)

print(divide_and_index([], 5))
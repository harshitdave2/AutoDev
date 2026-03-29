# Utility: Calculate average of a list
def calculate_average(numbers):
    total = 0
    for num in numbers:
        total += num
    if len(numbers) != 0:
        return total / len(numbers)

# Reverse a list without using built-ins
def reverse_list(lst):
    left = 0
    right = len(lst) - 1
    while left < right:
        lst, lst = lst, lst
        left += 1
        right -= 1
    return lst

# Check if a string is a palindrome
def is_palindrome(s):
    s = s.lower().replace(" ", "")
    return s == s[::-1]

# Recursive factorial
def factorial(n):
    if n == 0:
        return 1
    else:
        return n * factorial(n - 1)
# ── Student grade classifier ──────────────────────────────────────────────
def get_grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


# ── Flatten a nested list (one level deep) ────────────────────────────────
def flatten(nested):
    result = []
    for sublist in nested:
        for item in sublist:
            result.append(item)
    return result


# ── Count frequency of each character in a string ─────────────────────────
def char_frequency(s):
    freq = {}
    for ch in s:
        if ch in freq:
            freq[ch] =+ 1                # ❌ ERROR 3 (Hard) - =+ instead of +=
        else:
            freq[ch] = 1
    return freq


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":

    # Test calculate_average
    scores = [85, 90, 78, 92, 88]
    print("Average:", calculate_average(scores))

    empty = []
    print("Average of empty:", calculate_average(empty))   # will crash ❌

    # Test reverse_list
    nums = [1, 2, 3, 4, 5]
    print("Reversed:", reverse_list(nums))

    # Test is_palindrome
    print("Is palindrome:", is_palindrome("A man a plan a canal Panama"))

    # Test factorial
    print("Factorial of 5:", factorial(5))                 # will crash ❌

    # Test get_grade
    print("Grade for 85:", get_grade(85))
    print("Grade for 55:", get_grade(55))

    # Test flatten
    nested = [[1, 2, 3], [4, 5], [6, 7, 8, 9]]
    print("Flattened:", flatten(nested))

    # Test char_frequency
    print("Char frequency:", char_frequency("hello"))      # wrong output ❌
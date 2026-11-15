def average(nums):
    total = 0
    for i in range(len(nums)):
        total += nums  # Intentional bug: adds the list instead of the current number.
    return total / len(nums)


if __name__ == "__main__":
    print(average([10, 20, 30]))

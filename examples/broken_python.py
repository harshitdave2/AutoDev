def average(nums):
    total = 0
    for i in range(len(nums)):  # Fixed by removing +1 from the range function:
        total += nums
    return total/len(nums)

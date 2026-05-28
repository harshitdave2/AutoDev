def calculate_future_age(current_age):
     # BASIC BUG: Trying to concatenate a string with an integer
     message = "Next year, you will be " + str(int(current_age) + 1) + " years old."
     return message
print(calculate_future_age(25)) 
from index_error import fetch_user_data

def calculate_user_average(user_id):
    user = fetch_user_data(user_id)
    
    # SYSTEM BUG 2: AttributeError. If user is None (User 3), this crashes.
    # SYSTEM BUG 3: KeyError. If user exists but lacks 'scores' (User 2), this crashes.
    scores = user["scores"]
    
    # SYSTEM BUG 4: ZeroDivisionError if scores list exists but is empty
    total = sum(scores)
    return total / len(scores)
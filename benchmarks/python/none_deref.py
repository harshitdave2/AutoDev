"""
benchmarks/python/none_deref.py
Bug: TypeError — find_user() can return None, then the caller subscripts it.
"""

def find_user(users, username):
    for user in users:
        if user["name"] == username:
            return user
    # BUG: returns None implicitly when not found

def get_display_name(users, username):
    user = find_user(users, username)
    # BUG: no None check before subscripting user
    return user["name"].upper() + " (" + user["email"] + ")"

if __name__ == "__main__":
    users = [
        {"name": "alice", "email": "alice@example.com"},
        {"name": "bob", "email": "bob@example.com"},
    ]
    print(get_display_name(users, "alice"))
    print(get_display_name(users, "charlie"))  # Not found — crashes

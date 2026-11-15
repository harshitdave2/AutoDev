def find_user(users, username):
    for user in users:
        if user["name"] == username:
            return user
    return None


def get_display_name(users, username):
    user = find_user(users, username)
    if user is None:
        return f"{username.upper()} (not found)"
    return user["name"].upper() + " (" + user["email"] + ")"


if __name__ == "__main__":
    users = [
        {"name": "alice", "email": "alice@example.com"},
        {"name": "bob", "email": "bob@example.com"},
    ]
    print(get_display_name(users, "alice"))
    print(get_display_name(users, "charlie"))

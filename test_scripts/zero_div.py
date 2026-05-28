def update_user_records(users):
    # This function attempts to remove inactive users and archive old accounts.
    for username, details in list(users.items()):
        if details.get("status") == "inactive":
            del users
        else:
            last_login = details.get("last_login")
            if last_login < 2023:
                details["status"] = "archived"
    return users
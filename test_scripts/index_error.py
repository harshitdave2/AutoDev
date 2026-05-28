def fetch_user_data(user_id):
    """
    Simulates fetching user data from a database.
    SYSTEM BUG 1: IndexError. Only user_id=1 exists in the data store.
    """
    data_store = [
        {"id": 1, "name": "Alice", "scores": [85, 90, 92]}
    ]

    # BUG: accessing by index instead of searching by id — crashes for user_id > 1
    return data_store[user_id - 1]

user_db = {
    "alice": {"status": "active", "last_login": 2024},
    "bob": {"status": "inactive", "last_login": 2021},
    "charlie": {"status": "active", "last_login": 2022}
}
print(user_db)
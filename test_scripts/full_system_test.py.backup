from type_error import calculate_user_average

def run_reports():
    print("Starting system report generation...\n")
    
    user_ids_to_process = [1, 2, 3]
    
    for uid in user_ids_to_process:
        print(f"Processing User {uid}...")
        
        # When uid=2 or uid=3, calculate_user_average will crash.
        # AutoDev will need to track the traceback across system_main -> system_processor -> system_db
        avg = calculate_user_average(uid)
        
        print(f"User {uid} average score: {avg}\n")

if __name__ == "__main__":
    run_reports()
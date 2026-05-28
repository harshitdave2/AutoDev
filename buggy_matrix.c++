#include <iostream>
#include <vector>
#include <string>

// ----------------------------------------
// Feature 1: Calculate Average Score
// BUG: Division by zero when scores vector is empty
// ----------------------------------------
int calculate_average(const std::vector<int>& scores) {
    int total = 0;
    for (int score : scores) {
        total += score;
    }
    // C++ will crash here with a Floating point exception if scores is empty
    return total / scores.size(); 
}

// ----------------------------------------
// Feature 2: Get User Score by Index
// BUG: Out of bounds array access
// ----------------------------------------
int get_score_by_index(const std::vector<int>& scores, int index) {
    // Accessing an invalid index without checking bounds
    return scores[index];
}

// ----------------------------------------
// Feature 3: Format User Report
// BUG: Null pointer dereference
// ----------------------------------------
void print_user_report(std::string* username, const std::vector<int>& scores) {
    // Dereferencing a pointer without checking if it is nullptr (Segfault)
    std::cout << "User: " << *username << " | ";
    
    int avg = calculate_average(scores);
    std::cout << "Avg: " << avg << std::endl;
}

// ----------------------------------------
// Feature 4: Trigger Execution
// ----------------------------------------
int main() {
    std::cout << "--- Starting AutoDev C++ Test System ---" << std::endl;

    // Test 1: Empty scores will trigger Division By Zero
    std::vector<int> empty_scores;
    std::string user1 = "Alice";
    print_user_report(&user1, empty_scores);

    // Test 2: Out of bounds will return garbage memory or Segfault
    std::vector<int> valid_scores = {85, 90, 95};
    int bad_score = get_score_by_index(valid_scores, 10); // Index 10 doesn't exist
    std::cout << "Bad Score Retrieval: " << bad_score << std::endl;

    // Test 3: Passing a nullptr will cause a Segmentation Fault
    std::string* null_user = nullptr;
    print_user_report(null_user, valid_scores);

    return 0;
}
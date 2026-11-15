/*
 * benchmarks/cpp/segfault.cpp
 * Bug: Array/vector out-of-bounds access (made deterministic with vector::at).
 */
#include <iostream>
#include <vector>

int find_max(const std::vector<int>& arr) {
    int max_val = arr[0];
    // BUG: <= arr.size() should be < arr.size()
    for (int i = 1; i <= (int)arr.size(); i++) {
        if (arr.at(i) > max_val) {  // vector::at throws at arr.size()
            max_val = arr.at(i);
        }
    }
    return max_val;
}

int main() {
    std::vector<int> numbers = {3, 7, 1, 9, 4, 6, 2};
    std::cout << "Array: ";
    for (int n : numbers) std::cout << n << " ";
    std::cout << std::endl;
    int max_val = find_max(numbers);
    std::cout << "Max value: " << max_val << std::endl;
    return 0;
}

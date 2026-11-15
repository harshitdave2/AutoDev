#include <iostream>
#include <vector>

int find_max(const std::vector<int>& arr) {
    int max_val = arr[0];
    for (std::size_t i = 1; i < arr.size(); ++i) {
        if (arr[i] > max_val) {
            max_val = arr[i];
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

#include <iostream>
#include <vector>
#include <string>
using namespace std;

//  Reverse a string in-place 
void reverseString(string& s) {
    int n = s.length();
    for (int i = 0; i < n / 2; i++) {
        char temp = s[i];
        s[i] = s[n - i];                        //  ERROR 1 (Easy)
        s[n - i] = temp;
    }
}

//  Binary Search 
int binarySearch(vector<int>& arr, int target) {
    int low = 0, high = arr.size() - 1;

    while (low <= high) {
        int mid = (low + high) / 2;
        if (arr[mid] == target)
            return mid;
        else if (arr[mid] < target)
            low = mid + 1;
        else
            high = mid - 1;
    }
    return -1;
}

//  Stack implementation using vector 
class Stack {
private:
    vector<int> data;

public:
    void push(int val) {
        data.push_back(val);
    }

    void pop() {
        data.pop_back();
    }

    int top() {
        return data.back();
    }

    bool isEmpty() {
        return data.empty();
    }
};

//  Count word frequency in a sentence 
int countWord(string sentence, string word) {
    int count = 0;
    int pos = 0;

    while ((pos = sentence.find(word, pos)) != string::npos) {
        count++;
        pos++;
    }
    return count;
}

//  Matrix multiplication (2x2) 
void multiplyMatrix(int A[2][2], int B[2][2], int C[2][2]) {
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < 2; j++) {
            C[i][j] = 0;
            for (int k = 0; k < 2; k++) {
                C[i][j] += A[i][k] * B[i][j];  //  ERROR 2 (Medium)
            }
        }
    }
}

//  Merge two sorted vectors 
vector<int> mergeSorted(vector<int> a, vector<int> b) {
    vector<int> result;
    int i = 0, j = 0;

    while (i < a.size() && j < b.size()) {
        if (a[i] <= b[j])
            result.push_back(a[i++]);
        else
            result.push_back(b[j++]);
    }
    while (i < a.size()) result.push_back(a[i++]);
    while (j < b.size()) result.push_back(b[j++]);

    return result;
}

//  Cache-based Fibonacci (memoization) 
int fibMemo(int n, vector<int>& memo) {
    if (n <= 1) return n;
    if (memo[n] != -1) return memo[n];     
    memo[n] = fibMemo(n - 1, memo) + fibMemo(n - 2, memo);
    return memo[n];
}

int computeFib(int n) {
    vector<int> memo(n, -1);               //  ERROR 3 (Hard)
    return fibMemo(n, memo);
}

//  Main 
int main() {
    // Test reverseString
    string s = "hello";
    reverseString(s);
    cout << "Reversed: " << s << endl;

    // Test binarySearch
    vector<int> arr = {1, 3, 5, 7, 9, 11};
    cout << "Found at index: " << binarySearch(arr, 7) << endl;

    // Test Stack
    Stack st;
    st.push(10); st.push(20); st.push(30);
    cout << "Stack Top: " << st.top() << endl;
    st.pop();
    cout << "After Pop: " << st.top() << endl;

    // Test countWord
    cout << "Word count: " << countWord("the cat sat on the mat", "the") << endl;

    // Test multiplyMatrix
    int A[2][2] = {{1, 2}, {3, 4}};
    int B[2][2] = {{5, 6}, {7, 8}};
    int C[2][2] = {};
    multiplyMatrix(A, B, C);
    cout << "Matrix C[0][0]: " << C[0][0] << endl;  // Expected: 19

    // Test mergeSorted
    vector<int> x = {1, 3, 5};
    vector<int> y = {2, 4, 6};
    vector<int> merged = mergeSorted(x, y);
    cout << "Merged: ";
    for (int v : merged) cout << v << " ";
    cout << endl;

    // Test computeFib
    cout << "Fib(6): " << computeFib(6) << endl;   // Expected: 8

    return 0;
}
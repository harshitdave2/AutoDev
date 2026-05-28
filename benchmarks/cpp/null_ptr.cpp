/*
 * benchmarks/cpp/null_ptr.cpp  
 * Bug: Null pointer dereference — pointer not checked before dereference
 */
#include <iostream>
#include <string>

struct Node {
    int value;
    Node* next;
    Node(int v) : value(v), next(nullptr) {}
};

Node* find_value(Node* head, int target) {
    while (head != nullptr) {
        if (head->value == target) return head;
        head = head->next;
    }
    return nullptr;  // Returns null if not found
}

int main() {
    Node* head = new Node(10);
    head->next = new Node(20);
    head->next->next = new Node(30);

    // BUG: find_value returns nullptr for 99, then we dereference it
    Node* found = find_value(head, 99);
    std::cout << "Found value: " << found->value << std::endl;  // CRASH

    // Cleanup
    while (head) {
        Node* temp = head;
        head = head->next;
        delete temp;
    }
    return 0;
}

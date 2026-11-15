#include <iostream>

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
    return nullptr;
}

int main() {
    Node* head = new Node(10);
    head->next = new Node(20);
    head->next->next = new Node(30);

    Node* found = find_value(head, 99);
    if (found == nullptr) {
        std::cout << "Value not found: 99" << std::endl;
    } else {
        std::cout << "Found value: " << found->value << std::endl;
    }

    while (head) {
        Node* temp = head;
        head = head->next;
        delete temp;
    }
    return 0;
}

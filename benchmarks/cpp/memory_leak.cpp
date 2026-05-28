/*
 * benchmarks/cpp/memory_leak.cpp
 * Bug: Double-free of dynamically allocated memory
 */
#include <iostream>
#include <cstring>

class StringBuffer {
public:
    char* data;
    int size;

    StringBuffer(const char* str) {
        size = strlen(str) + 1;
        data = new char[size];
        strcpy(data, str);
    }

    // BUG: No copy constructor — default bitwise copy means two objects
    // share the same data pointer, causing double-free
    ~StringBuffer() {
        delete[] data;
    }
};

void process(StringBuffer buf) {  // Passed by value — causes copy!
    std::cout << "Processing: " << buf.data << std::endl;
}  // buf destructor called here — first free

int main() {
    StringBuffer sb("Hello, World!");
    process(sb);  // Copy made, destructor called at end of process()
    std::cout << "Done: " << sb.data << std::endl;  // sb.data now dangling
    // sb destructor called here — DOUBLE FREE / CRASH
    return 0;
}

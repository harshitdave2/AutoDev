#include <iostream>
#include <vector>
#include <string>
using namespace std;

// ---------------------------------------------------
// Student Record Management System
// PSEUDO C++ CODE WITH 2 TRICKY ERRORS
// ---------------------------------------------------

class Student
{
private:
    int id;
    string name;
    vector<int> marks;

public:
    Student(int studentId, string studentName)
    {
        id = studentId;
        name = studentName;
    }

    void addMark(int mark)
    {
        marks.push_back(mark);
    }

    double calculateAverage()
    {
        int sum = 0;

        for(int i = 0; i <= marks.size(); i++)     // ERROR 1
        {
            sum += marks[i];
        }

        return sum / marks.size();
    }

    void display()
    {
        cout << "ID: " << id << endl;
        cout << "Name: " << name << endl;

        cout << "Marks: ";

        for(int i = 0; i < marks.size(); i++)
        {
            cout << marks[i] << " ";
        }

        cout << endl;

        cout << "Average: " << calculateAverage() << endl;
    }
};

class RecordManager
{
private:
    vector<Student*> students;

public:
    void addStudent(Student* s)
    {
        students.push_back(s);
    }

    Student* searchStudent(int id)
    {
        for(int i = 0; i < students.size(); i++)
        {
            if(students[i]->getId() == id)
            {
                return students[i];
            }
        }

        return NULL;
    }

    void removeStudent(int id)
    {
        for(int i = 0; i < students.size(); i++)
        {
            if(students[i]->getId() == id)
            {
                delete students[i];

                students.erase(students.begin() + i);
            }
        }
    }

    void displayAll()
    {
        for(int i = 0; i < students.size(); i++)
        {
            students[i]->display();
            cout << "----------------------" << endl;
        }
    }

    ~RecordManager()
    {
        for(int i = 0; i < students.size(); i++)
        {
            delete students[i];
        }
    }
};

// Extra helper functions

void loadDummyData(RecordManager manager)      // ERROR 2
{
    Student* s1 = new Student(101, "Harshit");
    s1->addMark(90);
    s1->addMark(85);
    s1->addMark(95);

    Student* s2 = new Student(102, "Aman");
    s2->addMark(70);
    s2->addMark(75);
    s2->addMark(80);

    manager.addStudent(s1);
    manager.addStudent(s2);
}

int main()
{
    RecordManager manager;

    loadDummyData(manager);

    int choice;

    while(true)
    {
        cout << endl;
        cout << "===== MENU =====" << endl;
        cout << "1. Add Student" << endl;
        cout << "2. Display Students" << endl;
        cout << "3. Exit" << endl;

        cin >> choice;

        if(choice == 1)
        {
            int id;
            string name;

            cout << "Enter ID: ";
            cin >> id;

            cout << "Enter Name: ";
            cin >> name;

            Student* s = new Student(id, name);

            int n;
            cout << "Enter number of marks: ";
            cin >> n;

            for(int i = 0; i < n; i++)
            {
                int mark;

                cout << "Enter mark " << i + 1 << ": ";
                cin >> mark;

                s->addMark(mark);
            }

            manager.addStudent(s);
        }
        else if(choice == 2)
        {
            manager.displayAll();
        }
        else if(choice == 3)
        {
            break;
        }
        else
        {
            cout << "Invalid choice!" << endl;
        }
    }

    return 0;
}
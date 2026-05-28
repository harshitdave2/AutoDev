#include <iostream>
#include <vector>
using namespace std;

int sum(vector<int>& v){
    int s=0;
    for(int i=0;i<=v.size();i++){ // bug
        s+=v[i];
    }
    return s;
}

int main(){
    vector<int> v={1,2,3,4};
    cout<<sum(v)<<endl;
}

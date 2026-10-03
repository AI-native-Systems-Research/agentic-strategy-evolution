#include <iostream>
#include <vector>
#include <string>
#include <map>
#include <cstring>
using namespace std;

struct SAM {
    struct State { int len, link; int cnt; map<char,int> next; };
    vector<State> st;
    int last;
    void init() { st.clear(); st.push_back({0, -1, 0, {}}); last = 0; }
    void extend(char c) {
        int cur = st.size();
        st.push_back({st[last].len + 1, -1, 0, {}});
        int p = last;
        while (p != -1 && !st[p].next.count(c)) { st[p].next[c] = cur; p = st[p].link; }
        if (p == -1) { st[cur].link = 0; }
        else {
            int q = st[p].next[c];
            if (st[p].len + 1 == st[q].len) { st[cur].link = q; }
            else {
                int clone = st.size();
                st.push_back({st[p].len + 1, st[q].link, 0, st[q].next});
                while (p != -1 && st[p].next[c] == q) { st[p].next[c] = clone; p = st[p].link; }
                st[q].link = clone; st[cur].link = clone;
            }
        }
        last = cur;
    }
    long long countDistinct() {
        long long res = 0;
        for (int i = 1; i < (int)st.size(); i++) res += st[i].len - st[st[i].link].len;
        return res;
    }
};

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n; cin >> n;
    // word_i = "O" + string of X's of length 2*i
    vector<string> words(n);
    for(int i=0;i<n;i++){
        words[i] = "O" + string(2*(i+1), 'X');
    }
    for(int i=0;i<n;i++) cout << words[i] << "\n";
    cout.flush();

    // Precompute all n^2 pairs
    map<long long, pair<int,int>> power_map;
    SAM sam;
    for(int i=0;i<n;i++){
        for(int j=0;j<n;j++){
            string s = words[i] + words[j];
            sam.init();
            for(char c : s) sam.extend(c);
            long long p = sam.countDistinct();
            power_map[p] = {i+1, j+1};
        }
    }

    int q; cin >> q;
    while(q--){
        long long p; cin >> p;
        auto it = power_map.find(p);
        cout << it->second.first << " " << it->second.second << "\n";
        cout.flush();
    }
    return 0;
}
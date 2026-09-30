// Naive strip packing baseline
// Places each piece left-to-right in a horizontal strip with no vertical compaction.
// This wastes enormous vertical space (each column height = max piece height).
#include <bits/stdc++.h>
using namespace std;

int main(){
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;

    vector<vector<pair<int,int>>> shapes(n);
    long long totalCells = 0;

    for(int i = 0; i < n; i++){
        int k;
        cin >> k;
        shapes[i].resize(k);
        for(int j = 0; j < k; j++){
            cin >> shapes[i][j].first >> shapes[i][j].second;
        }
        totalCells += k;
    }

    // Simple strip packing: place each piece left-to-right, orient to minimize height
    int curX = 0;
    int maxH = 0;

    vector<array<int,4>> ans(n);

    for(int i = 0; i < n; i++){
        int minx = INT_MAX, miny = INT_MAX, maxx = INT_MIN, maxy = INT_MIN;
        for(auto &[x,y] : shapes[i]){
            minx = min(minx, x); miny = min(miny, y);
            maxx = max(maxx, x); maxy = max(maxy, y);
        }
        int w = maxx - minx + 1;
        int h = maxy - miny + 1;

        // Pick orientation: R=0 (original) or R=1 (90 CW) — whichever is wider
        if(w >= h){
            // Use original
            ans[i] = {curX - minx, 0 - miny, 0, 0};
            curX += w;
            maxH = max(maxH, h);
        } else {
            // Rotate 90 CW: (x,y) -> (y,-x)
            // After rotation: new width = h, new height = w
            // New min_x = miny, new min_y = -maxx
            ans[i] = {curX - miny, 0 - (-maxx), 1, 0};
            curX += h;
            maxH = max(maxH, w);
        }
    }

    cout << curX << " " << maxH << "\n";
    for(int i = 0; i < n; i++){
        cout << ans[i][0] << " " << ans[i][1] << " " << ans[i][2] << " " << ans[i][3] << "\n";
    }

    return 0;
}

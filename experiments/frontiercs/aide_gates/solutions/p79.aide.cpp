#include <iostream>
#include <cstdint>
#include <cmath>
#include <random>
#include <algorithm>
#include <vector>
#include <numeric>

using namespace std;

typedef unsigned long long ull;
typedef __int128 u128;

ull mulmod(ull a, ull b, ull m) {
    return (u128)a * b % m;
}

ull powmod(ull a, ull b, ull m) {
    ull r = 1;
    a %= m;
    while (b > 0) {
        if (b & 1) r = mulmod(r, a, m);
        a = mulmod(a, a, m);
        b >>= 1;
    }
    return r;
}

bool miller_rabin(ull n, ull a) {
    if (n % a == 0) return n == a;
    ull d = n - 1;
    int r = 0;
    while (d % 2 == 0) { d /= 2; r++; }
    ull x = powmod(a, d, n);
    if (x == 1 || x == n - 1) return true;
    for (int i = 0; i < r - 1; i++) {
        x = mulmod(x, x, n);
        if (x == n - 1) return true;
    }
    return false;
}

bool is_prime(ull n) {
    if (n < 2) return false;
    for (ull a : {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37}) {
        if (!miller_rabin(n, a)) return false;
    }
    return true;
}

ull pollard_rho(ull n) {
    if (n % 2 == 0) return 2;
    mt19937_64 rng(42);
    while (true) {
        ull x = rng() % (n - 2) + 2;
        ull y = x;
        ull c = rng() % (n - 1) + 1;
        ull d = 1;
        while (d == 1) {
            x = (mulmod(x, x, n) + c) % n;
            y = (mulmod(y, y, n) + c) % n;
            y = (mulmod(y, y, n) + c) % n;
            d = __gcd(x > y ? x - y : y - x, n);
        }
        if (d != n) return d;
    }
}

int bits_func(ull x) {
    if (x == 0) return 0;
    return 64 - __builtin_clzll(x);
}

ull simulate_time(ull a, ull d, ull n) {
    ull r = 1;
    ull total = 0;
    for (int i = 0; i < 60; i++) {
        if ((d >> i) & 1) {
            total += (ull)(bits_func(r) + 1) * (bits_func(a) + 1);
            r = mulmod(r, a, n);
        }
        total += (ull)(bits_func(a) + 1) * (bits_func(a) + 1);
        a = mulmod(a, a, n);
    }
    return total;
}

int main() {
    ios::sync_with_stdio(false);
    
    ull n;
    cin >> n;
    
    // Factor n
    ull p = pollard_rho(n);
    ull q = n / p;
    if (p > q) swap(p, q);
    
    ull m = (p - 1) * (q - 1);
    
    // Determine d bit by bit
    // Use a few different a values per bit for robustness
    ull d_found = 0;
    
    mt19937_64 rng(12345);
    
    // We'll query with several a values and determine bits one at a time
    // For each bit i, simulate with bit=0 and bit=1, see which matches
    
    // First gather some queries
    int num_queries = 200; // use multiple a values
    vector<ull> a_vals(num_queries);
    vector<ull> times(num_queries);
    
    for (int j = 0; j < num_queries; j++) {
        a_vals[j] = rng() % (n - 2) + 2;
        cout << "? " << a_vals[j] << "\n";
        cout.flush();
        cin >> times[j];
    }
    
    // Now determine each bit greedily
    for (int i = 0; i < 60; i++) {
        // Try bit i = 0 vs 1
        long long score0 = 0, score1 = 0;
        for (int j = 0; j < num_queries; j++) {
            ull t0 = simulate_time(a_vals[j], d_found, n);
            ull t1 = simulate_time(a_vals[j], d_found | (1ULL << i), n);
            long long diff0 = (long long)times[j] - (long long)t0;
            long long diff1 = (long long)times[j] - (long long)t1;
            // The one closer (but times[j] >= simulated since remaining bits add more)
            // Actually times[j] corresponds to full d, and we're building partial d
            // With partial d, simulate_time gives a lower bound. The closer one is better.
            // We want the one where the residual is smaller but non-negative for higher bits
            if (abs(diff0) < abs(diff1)) score0++;
            else score1++;
        }
        if (score1 > score0) {
            d_found |= (1ULL << i);
        }
    }
    
    // Verify d_found is coprime with m, if not try nearby
    if (__gcd(d_found, m) != 1 || d_found == 0 || d_found >= m) {
        // Just output best guess
    }
    
    cout << "! " << d_found << "\n";
    cout.flush();
    
    return 0;
}
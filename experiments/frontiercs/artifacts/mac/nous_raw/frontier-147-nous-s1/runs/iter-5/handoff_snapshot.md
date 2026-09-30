# Handoff — Iter 5

### Goal
Test whether a two-phase cooling schedule (linear exploration + exponential convergence) improves SA score over pure exponential cooling, both at the confirmed 4.8s time budget. Run 5 judge calls per arm and compare.

### Key Discoveries
- **4.8s is the confirmed optimal time budget (RP-6).** Mean 91.52, stdev 0.53 across 5 runs (iter-4). Use this for both arms.
- **The exponential cooling schedule is front-loaded.** At the midpoint (50% elapsed), T ≈ 0.006 — already 13× below T0. Most exploration happens in the first 30% of time.
- **Two-phase cooling keeps T 3.5× higher at midpoint.** Linear from T0=0.08 to T_mid=0.01 over 60%, then exponential T_mid→T1 over 40%. T ≈ 0.022 at midpoint vs 0.006.
- **Single probes this session:** 2.85s→91.6, 4.8s→90.4, two-phase 4.8s→91.0, 5.3s→90.5. All within judge variance (RP-5). Multi-run needed.
- **T0=0.1 is harmful.** Scored 90.8 at 5.3s and 90.7 at 2.85s (iter-3). Don't use.
- **5.3s shows no clear benefit over 4.8s** in probes (90.5 vs 90.4). Stick with 4.8s.

### System Interface
- **Build:** None — judge compiles automatically.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** stdout prints `SCORE: <n>` (0–100).
- **Baseline result:** 90.43 (4.8s, this session); iter-4 mean 91.52 ± 0.53.

### Code Map
- `solution.cpp:111` — `double T0 = 0.08, T1 = 0.0005;` — Temperature constants. Unchanged for both arms.
- `solution.cpp:113` — `double total_time = 2.85;` — **Change to 4.8 for both arms.**
- `solution.cpp:128` — `T = T0 * pow(T1 / T0, progress);` — **THE TARGET LINE.** Replace with two-phase logic for h-main. Keep as-is for h-control.
- `solution.cpp:116-117` — Best-score init and array copy. Unchanged.
- `solution.cpp:130-136` — Best-tracking check every 32K iters. Unchanged.
- `solution.cpp:80-102` — Greedy init. Unchanged.

### Code Targets
- **h-main** (`solution.cpp:113,128`):
  1. Change `double total_time = 2.85;` to `double total_time = 4.8;`
  2. Replace the single line `T = T0 * pow(T1 / T0, progress);` with two-phase logic:
     ```
     double phase1_frac = 0.6;
     double T_mid = 0.01;
     if (progress < phase1_frac) {
         double p1 = progress / phase1_frac;
         T = T0 + (T_mid - T0) * p1;
     } else {
         double p2 = (progress - phase1_frac) / (1.0 - phase1_frac);
         T = T_mid * pow(T1 / T_mid, p2);
     }
     ```
  3. `phase1_frac` and `T_mid` can be declared near T0/T1 at line 111.

- **h-control-negative** (`solution.cpp:113`): Change `double total_time = 2.85;` to `double total_time = 4.8;`. Keep exponential cooling unchanged.

### What I Tried That Didn't Work
- **5.3s time budget (90.5)**: No improvement over 4.8s in single probe. Diminishing returns or marginal TLEs possible.
- **5.3s + wider temp T0=0.1 (90.8)**: Wider temperature hurts, consistent with iter-3 finding.
- **Two-phase cooling single probe (91.0)**: Not clearly better than 4.8s baseline (90.4), but both are within judge noise. Multi-run needed.
- All prior dead ends still apply: compound moves (89.5), multi-start (87.9), 8s budget (91.9), kick moves (89.9), contract-expand (87.0), targeted selection (89.9), post-SA refinement (37.7), T0=0.1 (90.7), BSP init (83-86), paired boundary moves (0), area-biased proposals (85.7), adaptive step sizes (88.2), two-edge moves (89.7), SA with reheat (90.4), weighted rect selection (85.3).

### What I Excluded and Why
- **Time budget exploration (5.0-5.5s)**: Probes at 5.3s show no improvement. Would need 5+ runs to test properly, but better to focus on a mechanism change.
- **Spatial indexing for throughput**: Would increase iteration count by reducing O(N) max_expand cost, but complex to implement correctly (~60 lines, dynamic grid maintenance). Deferred for iter-6.
- **Temperature-adaptive step sizes**: Tried in iter-2 (88.2 at 2.85s). Could work better at 4.8s but uncertain mechanism.
- **T0/T1 tuning**: Tested T0=0.1 this session — still harmful. Current T0=0.08 appears near-optimal.

### Evolution of Thinking
Started by exploring time budget extension (5.3s) and temperature widening. Both probed worse than 4.8s baseline in single runs. Realized the cooling schedule *shape* is more interesting than the endpoints — the exponential cooling is heavily front-loaded, spending most exploration budget in the first 30% of time. Two-phase cooling redistributes this more evenly. The single probe (91.0 vs 90.4) is within noise but the mechanism is theoretically sound and hasn't been tested properly with multiple runs.

### Current Status
- **Validated:** 4.8s budget works (RP-6). Two-phase cooling code compiles and produces valid output (probe: 91.0). Both arm solutions ready in `runs/iter-5/inputs/`.
- **Uncertain:** Whether the 3.5× higher midpoint temperature from two-phase cooling actually translates to better SA exploration. The effect may be smaller than judge variance.
- **Suggested next:** (1) If two-phase cooling helps, optimize phase1_frac and T_mid (dose-response on these knobs). (2) If no effect, try spatial indexing to boost throughput (fundamentally different approach to getting more effective iterations). (3) Explore temperature-dependent move sizes as an alternative to cooling schedule changes.

### Warnings & Constraints
- Judge calls take 60-90s. Budget 10-15 minutes for 10 calls.
- Cannot compile locally on macOS — `bits/stdc++.h` not available.
- The xorshift RNG seed is fixed at 88172645463325252. Both arms use the same seed.
- Judge variance ~5 points stdev (RP-5). Single probes are unreliable.
- The two-phase cooling code must declare `phase1_frac` and `T_mid` as local variables inside the `if ((iter & 0x3FF) == 0)` block to avoid polluting the outer scope.

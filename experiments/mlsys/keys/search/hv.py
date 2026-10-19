"""Exact hypervolume, 4 objectives (as in the original campaign): maximize rps, minimize ttft_p99_ms,
minimize gpus (tp*instances), minimize total_kv_blocks. Reference point fixed: (0, 50000, 9, 11000)."""
REF = (0.0, 50000.0, 9.0, 11000.0)

def _hv(P, ref):
    # recursive slicing on the last coordinate; P in minimization form, all strictly better than ref
    if not P: return 0.0
    if len(ref) == 1: return ref[0] - min(p[0] for p in P)
    ks = sorted({p[-1] for p in P}) + [ref[-1]]
    tot = 0.0
    for i in range(len(ks) - 1):
        sl = [p[:-1] for p in P if p[-1] <= ks[i]]
        tot += _hv(sl, ref[:-1]) * (ks[i + 1] - ks[i])
    return tot

def nondominated(P):
    return [p for p in P if not any(all(q[i] <= p[i] for i in range(len(p))) and q != p for q in P)]

def hv(rows):
    """rows: dicts with rps, ttft_p99_ms, gpus, total_kv_blocks."""
    P = [(-r["rps"], r["ttft_p99_ms"], r["gpus"], r["total_kv_blocks"]) for r in rows]
    ref = (-REF[0], REF[1], REF[2], REF[3])
    P = [p for p in P if all(p[i] < ref[i] for i in range(4))]
    return _hv(nondominated(list(set(P))), ref)

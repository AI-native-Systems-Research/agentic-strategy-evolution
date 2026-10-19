"""Oracle for the pd-disagg verification task.

Ground truth: keys/pd/key.json, from our own BLIS sweep (BLIS 4e88b20, fixed setup, seeds 42-46; seed std ~0.001 ms).

Facts that hold for any reasonable fit range (checked in keys/pd, fit ranges 2-40 .. 2-100):
- the formula ITL = alpha/(1 - lambda W) fits within 2% at moderate rates (<= 60 req/s) for AL and AD;
- at high rate (>= 100) the formula OVERpredicts ITL, and the error grows with rate;
- AD has higher TTFT than AL at every rate, and lower ITL at every rate >= 2.

Grading uses the arm's claims (structured, from final/answer.json), each checked against the sweep, plus a fixed
phrase list for statements that are only expressed in prose. Every claimed mean ITL/TTFT is re-measured in a clean
BLIS build (C2).
"""
import json
import os
import re

from common import KEYS, blis_json, fraction

KEY = json.load(open(os.path.join(KEYS, "pd", "key.json")))
OBS = {p: {int(r): v for r, v in KEY["itl"][p]["observed_itl_ms"].items()} for p in ("never", "always")}
TTFT = {p: {int(r): v for r, v in KEY["ttft"][p].items()} for p in ("never", "always")}
CLEAN_BLIS = "/Users/toslali/mlsys_runs/repos/blis-pd-base"
FIXED = ["--model", "qwen/qwen3-14b", "--num-instances", "4", "--prefill-instances", "2", "--decode-instances", "2",
         "--num-requests", "300", "--prompt-tokens", "512", "--prompt-tokens-stdev", "0", "--output-tokens", "128",
         "--output-tokens-stdev", "0", "--routing-policy", "least-loaded"]

K4_PHRASES = [r"\bw\b[^.\n]{0,80}(not constant|non-?constant|varies|vary|decreas|sublinear|depends on (the )?(batch|load))",
              r"(constant|fixed)[- ](w|work|service[- ]cost|per[- ]request (work|cost)|marginal cost)[^.\n]{0,100}(break|fail|invalid|violat|assumption)",
              r"sub-?linear[^.\n]{0,80}(step|batch|iteration)", r"(step|iteration)[- ]time[^.\n]{0,100}(sub-?linear|concave|saturat)",
              r"amortiz[^.\n]{0,80}(batch|overhead|weight)", r"(weight[- ]load\w*|fixed overhead)[^.\n]{0,100}amortiz"]


def rate_policy(cond):
    c = (cond or "").lower()
    m = re.search(r"(?:rate|λ|lambda)\s*[=:]?\s*(\d+(?:\.\d+)?)", c) or re.search(r"(\d+(?:\.\d+)?)\s*(?:req/s|rps)", c)
    rate = float(m.group(1)) if m else None
    al = bool(re.search(r"\b(al|never|always[- ]local)\b|pd-decider[= ]never", c))
    ad = bool(re.search(r"\b(ad|always[- ]disagg\w*)\b|pd-decider[= ]always", c))
    pol = "never" if al and not ad else "always" if ad and not al else None
    return rate, pol


def _kind(metric):
    m = (metric or "").lower()
    if re.search(r"err|deviation|mape|residual|pct|percent|%|ratio|delta|diff", m):
        return "error"
    if "p99" in m or "p90" in m or "p95" in m or "p50" in m:
        return None
    if "itl" in m:
        return "itl"
    if "ttft" in m:
        return "ttft"
    return None


def remeasure(claim):
    """C2: re-run BLIS at the claim's condition. True if within 2% of the simulator, False if not, None if the claim
    is not a re-measurable mean ITL/TTFT at a stated rate and policy."""
    k = _kind(claim.get("metric"))
    if k not in ("itl", "ttft") or not isinstance(claim.get("value"), (int, float)):
        return None
    rate, pol = rate_policy(claim.get("condition"))
    if rate is None or pol is None or not (0 < rate <= 400):
        return None
    sd = re.search(r"seed\s*[=:]?\s*(\d+)", (claim.get("condition") or "").lower())
    d = blis_json(CLEAN_BLIS, FIXED + ["--pd-decider", pol, "--rate", f"{rate:g}", "--seed", sd.group(1) if sd else "42"])
    if d is None:
        return None
    truth = d["itl_mean_ms" if k == "itl" else "ttft_mean_ms"]
    return abs(truth - claim["value"]) <= 0.02 * abs(truth)


def score(answer, text):
    """answer: parsed final/answer.json; text: lowercased answer prose + claim metric/condition strings."""
    claims = [c for c in (answer or {}).get("claims", []) if isinstance(c, dict)]
    err_claims = []
    for c in claims:
        if _kind(c.get("metric")) == "error" and isinstance(c.get("value"), (int, float)):
            r, p = rate_policy(c.get("condition"))
            if r is not None:
                err_claims.append((r, c["value"], c))
    res = {}
    # K1: fit within ~2% at moderate rates (claim-based, or stated in prose).
    k1_claim = any(r <= 60 and abs(v) <= 2.0 for r, v, _ in err_claims)
    k1_text = bool(re.search(r"(within|under|below|<|≤|less than|about|~)\s*~?\s*[0-2](\.\d+)?\s*%", text)) and \
        bool(re.search(r"(fit|hold|accurate|match|agree|valid)", text))
    res["K1_fit_moderate"] = bool(k1_claim or k1_text)
    # K2: overprediction at high rate (>= 100), error growing with rate.
    hi = [(r, v) for r, v, _ in err_claims if r >= 100 and abs(v) >= 5]
    over_text = bool(re.search(r"over-?predict|over-?estimat|predicts? (a )?(higher|too high|larger)|"
                               r"(formula|model|prediction)[^.\n]{0,40}(higher|exceeds|above) (than )?(the )?(observ|measur|simul|blis)", text))
    under_text = bool(re.search(r"under-?predict|under-?estimat", text) and re.search(r"itl[^.\n]{0,60}under-?(predict|estimat)", text))
    hi_sign_ok = all(v > 0 for _, v in hi) if hi else None  # convention: (pred - obs)/obs > 0 = overprediction
    breaks_text = bool(re.search(r"(break|diverg|fail|deviat|degrad|no longer)[^.\n]{0,80}(high|heavy|large)[^.\n]{0,20}(rate|load)", text) or
                       re.search(r"(rate|load)s?\s*(>=|≥|above|beyond|over|of)\s*~?\s*(8\d|9\d|1[0-5]\d)", text))
    res["K2_breakdown_overpredict"] = bool((hi and hi_sign_ok) or (over_text and breaks_text and not under_text))
    # K3: AD TTFT higher than AL; AD ITL lower than AL.
    t1 = re.search(r"(\bad\b|always[- ]disagg\w*|disaggregat\w*)[^.\n]{0,100}(higher|larger|worse|greater|more|longer|adds?|pays?)[^.\n]{0,40}ttft", text)
    t2 = re.search(r"ttft[^.\n]{0,100}(higher|larger|worse|greater|longer)[^.\n]{0,60}(\bad\b|disaggregat)", text)
    t3 = re.search(r"(\bal\b|always[- ]local|local)[^.\n]{0,80}(lower|better|smaller|shorter)[^.\n]{0,40}ttft", text)
    i1 = re.search(r"(\bad\b|always[- ]disagg\w*|disaggregat\w*)[^.\n]{0,100}(lower|smaller|better|less|reduc)[^.\n]{0,40}itl", text)
    i2 = re.search(r"itl[^.\n]{0,100}(lower|smaller|better|reduc)[^.\n]{0,60}(\bad\b|disaggregat)", text)
    i3 = re.search(r"(\bal\b|always[- ]local)[^.\n]{0,80}(higher|worse|larger)[^.\n]{0,40}itl", text)
    res["K3_al_vs_ad"] = bool((t1 or t2 or t3) and (i1 or i2 or i3))
    res["K4_mechanism_soft"] = any(re.search(p, text) for p in K4_PHRASES)
    res["O1"] = bool(res["K1_fit_moderate"] and res["K2_breakdown_overpredict"] and res["K3_al_vs_ad"])
    rm = [remeasure(c) for c in claims]
    res["C2_remeasured_frac"] = fraction(rm)
    res["C3_false_claims"] = sum(1 for x in rm if x is False)
    res["n_remeasurable"] = sum(1 for x in rm if x is not None)
    res["O2_heldout"] = None
    return res

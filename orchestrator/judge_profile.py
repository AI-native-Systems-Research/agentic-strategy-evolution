"""v8 judge profile: what the official judge has shown about time limits and local-evaluator fidelity.

Inputs are only official measure results and local evaluator runs, never judge configuration or test data:

- official measures: JSONL lines ``{"ts": <epoch>, "sha256": <hex of the measured file>, "score": <n>}``
  (``rejected: true`` lines are skipped), written by the judge side at ``v8.official_log`` (default
  ``<work_dir>/official_measures.jsonl``);
- local runs: JSONL lines ``{"sha256": ..., "score": ..., "max_cpu_s": ...}`` that the local evaluator's
  command appends to ``<work_dir>/evaluator/local_runs.jsonl``;
- the stated time limit and the noise spread from the newest valid ``instrument.json``.

The two logs are joined on the file hash. ``<work_dir>/judge_profile.json`` holds the result and
``judge_profile.md`` a 2-3 line summary that every v8 session sees. Pure Python, no LLM calls.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path

from orchestrator.util import atomic_write

PROFILE_FILE = "judge_profile.json"
SUMMARY_FILE = "judge_profile.md"
OFFICIAL_FILE = "official_measures.jsonl"
LOCAL_FILE = "local_runs.jsonl"
TRUST_PAIRS = 2  # official measures per session compared with the local evaluator
TRUST_MARGIN = 5.0  # points allowed on top of twice the noise spread


def official_log_path(campaign: dict, work_dir: Path) -> Path:
    from orchestrator.design_profile import v8_settings
    p = v8_settings(campaign).official_log
    return Path(p).expanduser() if p else Path(work_dir) / OFFICIAL_FILE


def local_log_path(work_dir: Path) -> Path:
    from orchestrator.design_profile import EVALUATOR_DIR
    return Path(work_dir) / EVALUATOR_DIR / LOCAL_FILE


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = Path(path).read_text(errors="ignore").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def official_measures(campaign: dict, work_dir: Path) -> list[dict]:
    """Official measures in time order, each with a numeric score."""
    rows = [r for r in read_jsonl(official_log_path(campaign, work_dir))
            if not r.get("rejected") and _num(r.get("score")) is not None]
    return sorted(rows, key=lambda r: _num(r.get("ts")) or 0.0)


def best_official(campaign: dict, work_dir: Path) -> float | None:
    scores = [_num(r["score"]) for r in official_measures(campaign, work_dir)]
    return max(scores) if scores else None


def _local_by_sha(work_dir: Path) -> dict[str, dict]:
    """Newest local run per file hash."""
    out: dict[str, dict] = {}
    for r in read_jsonl(local_log_path(work_dir)):
        sha = str(r.get("sha256") or "")
        if sha:
            out[sha] = r
    return out


def _instrument(campaign: dict, work_dir: Path) -> dict:
    from orchestrator.instrument import latest_instrument
    found = latest_instrument(work_dir)
    return found[1] if found else {}


def noise_spread(campaign: dict, work_dir: Path) -> float | None:
    runs = (_instrument(campaign, work_dir).get("noise") or {}).get("runs") or []
    vals = [v for v in (_num(r) for r in runs) if v is not None]
    return (max(vals) - min(vals)) if len(vals) >= 2 else None


def _load(work_dir: Path) -> dict:
    try:
        data = json.loads((Path(work_dir) / PROFILE_FILE).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _trust(sessions: list[dict], pairs: list[dict], threshold: float, previous: dict) -> dict:
    """Untrusted (sticky) once a session's first two official measures disagree with the local evaluator."""
    if previous.get("trusted") is False:
        return previous
    windows = sessions or [{"label": "run", "start": 0.0, "end": None}]
    checked = None
    for w in windows:
        start, end = _num(w.get("start")) or 0.0, _num(w.get("end"))
        first = [p for p in pairs if p["ts"] >= start and (end is None or p["ts"] <= end)][:TRUST_PAIRS]
        if len(first) < TRUST_PAIRS:
            continue
        gap = sum(abs(p["official"] - p["local"]) for p in first) / len(first)
        rec = {"trusted": gap <= threshold, "session": w.get("label"), "mean_gap": round(gap, 3),
               "threshold": round(threshold, 3),
               "pairs": [{"official": p["official"], "local": p["local"]} for p in first]}
        if not rec["trusted"]:
            return rec
        checked = rec
    return checked or {"trusted": None, "threshold": round(threshold, 3)}


def update_judge_profile(campaign: dict, work_dir: Path) -> dict:
    """Recompute and write ``judge_profile.json`` and ``judge_profile.md``; return the profile."""
    from orchestrator.design_profile import v8_settings
    work_dir = Path(work_dir)
    old = _load(work_dir)
    inst = _instrument(campaign, work_dir)
    stated = _num(inst.get("time_limit_s"))
    noise = noise_spread(campaign, work_dir)
    local = _local_by_sha(work_dir)
    accepted, timeouts, pairs = None, [], []
    official = official_measures(campaign, work_dir)
    for r in official:
        sha, score = str(r.get("sha256") or ""), _num(r["score"])
        loc = local.get(sha)
        if loc is None:
            continue
        lscore, cpu = _num(loc.get("score")), _num(loc.get("max_cpu_s"))
        if lscore is not None:
            pairs.append({"ts": _num(r.get("ts")) or 0.0, "official": score, "local": lscore})
        if score > 0 and cpu is not None and (accepted is None or cpu > accepted["local_max_cpu_s"]):
            accepted = {"local_max_cpu_s": cpu, "official_score": score, "sha256": sha}
        if score == 0 and lscore is not None and lscore > 0:
            timeouts.append({"sha256": sha, "official_score": score, "local_score": lscore,
                             "local_max_cpu_s": cpu})
    profile = {
        "time_limit_s": stated,
        "assumed_time_limit_s": stated if stated else v8_settings(campaign).assumed_time_limit_s,
        "time_limit_source": "statement" if stated else "assumed (the statement gives none)",
        "longest_accepted_local": accepted,
        "likely_timeouts": timeouts,
        "n_official": len(official),
        "best_official": max((_num(r["score"]) for r in official), default=None),
        "noise_spread": noise,
        "sessions": old.get("sessions") or [],
    }
    profile["evaluator"] = _trust(profile["sessions"], pairs, 2 * (noise or 0.0) + TRUST_MARGIN,
                                  old.get("evaluator") or {})
    atomic_write(work_dir / PROFILE_FILE, json.dumps(profile, indent=2) + "\n")
    atomic_write(work_dir / SUMMARY_FILE, format_judge_summary(profile))
    return profile


def _fmt(x) -> str:
    return f"{x:.3g}" if isinstance(x, (int, float)) else str(x)


def format_judge_summary(p: dict) -> str:
    limit = p.get("assumed_time_limit_s")
    acc = p.get("longest_accepted_local")
    line1 = (f"- Time limit: {_fmt(limit)} s ({p.get('time_limit_source')}). "
             + (f"The longest local runtime that still scored > 0 officially is {_fmt(acc['local_max_cpu_s'])} s; "
                "stay below it and never fill time beyond it." if acc else
                "No officially accepted runtime yet: keep the worst case under that limit."))
    to = p.get("likely_timeouts") or []
    line2 = (f"- Likely timeouts: {len(to)} official 0 where the local evaluator scored > 0 for the same code "
             f"(local runtimes {', '.join(_fmt(t.get('local_max_cpu_s')) + ' s' for t in to[:3])}). "
             "Treat an official 0 with a local score as too slow." if to else
             "- Likely timeouts: none seen.")
    ev = p.get("evaluator") or {}
    if ev.get("trusted") is False:
        line3 = (f"- Local evaluator UNTRUSTED: local and official differ by {_fmt(ev.get('mean_gap'))} points "
                 f"(allowed {_fmt(ev.get('threshold'))}). Decide on official measures only.")
    elif ev.get("trusted"):
        line3 = "- Local evaluator agrees with the judge on the first official measures."
    else:
        line3 = "- Local evaluator not yet checked against the judge."
    return "## Judge profile (v8)\n\n" + "\n".join([line1, line2, line3]) + "\n"


def judge_summary(campaign: dict, work_dir: Path) -> str:
    """The current summary (recomputed); empty unless the campaign uses v8."""
    from orchestrator.design_profile import is_v8
    if not is_v8(campaign):
        return ""
    return format_judge_summary(update_judge_profile(campaign, work_dir))


def _record_session(work_dir: Path, label: str, start: float, end: float | None) -> None:
    data = _load(work_dir)
    sessions = [s for s in data.get("sessions") or [] if not (s.get("label") == label and s.get("start") == start)]
    sessions.append({"label": label, "start": start, "end": end})
    data["sessions"] = sessions
    atomic_write(Path(work_dir) / PROFILE_FILE, json.dumps(data, indent=2) + "\n")


@contextlib.contextmanager
def watch_session(campaign: dict, work_dir: Path, label: str, poll_s: float = 10.0):
    """Keep the judge profile fresh while a session runs, and record the session's time window."""
    from orchestrator.design_profile import is_v8
    if not is_v8(campaign):
        yield
        return
    start = time.time()
    _record_session(work_dir, label, start, None)
    stop = threading.Event()

    def loop():
        while not stop.wait(poll_s):
            with contextlib.suppress(Exception):
                update_judge_profile(campaign, work_dir)

    t = threading.Thread(target=loop, daemon=True, name=f"judge-profile-{label}")
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)
        _record_session(work_dir, label, start, time.time())
        with contextlib.suppress(Exception):
            update_judge_profile(campaign, work_dir)

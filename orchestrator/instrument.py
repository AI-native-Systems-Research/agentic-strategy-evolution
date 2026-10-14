"""v7 instrument checks: worst-case CPU time, measurement noise, knob relevance.

The build-evaluator session writes ``runs/iter-N/instrument.json`` (schema ``instrument.schema.json``).
Later sessions get a short summary of the newest valid file instead of guessing about speed or noise. A
missing or invalid file only logs a warning: a failed evaluator session must not stop the campaign.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jsonschema

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)

INSTRUMENT_FILE = "instrument.json"
SPEED_FIRST_FRACTION = 0.5  # laptop and judge machines differ, so half the limit is the safe line
HEADING = "## Instrument checks (v7)"
_SCHEMA = json.loads((Path(__file__).resolve().parent / "schemas" / "instrument.schema.json").read_text())
_ITER_RE = re.compile(r"^iter-(\d+)$")


def validate_instrument(data) -> list[str]:
    """Schema errors for an instrument.json payload (empty when valid)."""
    v = jsonschema.Draft7Validator(_SCHEMA)
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in v.iter_errors(data)]


def check_instrument(iter_dir: Path) -> str:
    """'valid', 'missing', or 'invalid: ...' for ``iter_dir/instrument.json``; warns unless valid."""
    path = Path(iter_dir) / INSTRUMENT_FILE
    if not path.is_file():
        logger.warning("v7: %s is missing; later sessions get no instrument checks", path)
        return "missing"
    try:
        errors = validate_instrument(json.loads(path.read_text()))
    except ValueError as exc:
        errors = [f"not JSON ({exc})"]
    if errors:
        logger.warning("v7: %s is invalid and will be ignored: %s", path, "; ".join(errors[:3]))
        return "invalid: " + "; ".join(errors[:3])
    return "valid"


def latest_instrument(work_dir: Path, iteration: int | None = None) -> tuple[str, dict] | None:
    """(``iter-N/instrument.json``, data) for the newest valid file at or before ``iteration``."""
    runs = Path(work_dir) / "runs"
    found = []
    for d in runs.iterdir() if runs.is_dir() else ():
        m = _ITER_RE.match(d.name)
        if m and (iteration is None or int(m.group(1)) <= iteration) and (d / INSTRUMENT_FILE).is_file():
            found.append((int(m.group(1)), d))
    for _n, d in sorted(found, reverse=True):
        try:
            data = json.loads((d / INSTRUMENT_FILE).read_text())
        except (OSError, ValueError):
            continue
        if not validate_instrument(data):
            return f"{d.name}/{INSTRUMENT_FILE}", data
    return None


def _num(x: float) -> str:
    return f"{x:.3g}" if abs(x) < 1000 else f"{x:.0f}"


def format_summary(source: str, data: dict) -> str:
    """The heading plus 2-3 lines. Spread, speed_first, and knob relevance are recomputed from the raw numbers."""
    cpu, limit = float(data["max_cpu_s"]), data.get("time_limit_s")
    if limit:
        speed_first = cpu > SPEED_FIRST_FRACTION * float(limit)
        worst = (f"max CPU {_num(cpu)} s on the largest inputs, time limit {_num(float(limit))} s "
                 f"({100 * cpu / float(limit):.0f}%).")
    else:
        speed_first = bool(data.get("speed_first"))
        worst = f"max CPU {_num(cpu)} s on the largest inputs, time limit unknown."
    if speed_first:
        worst += " Over half the limit: make it faster before any tuning."
    runs = [float(r) for r in data["noise"]["runs"]]
    lo, hi = min(runs), max(runs)
    spread = hi - lo
    lines = [f"{HEADING}, from `{source}`", "",
             f"- Worst case: {worst}",
             f"- Noise: {len(runs)} runs of the unchanged solution gave {_num(lo)} to {_num(hi)} (spread "
             f"{_num(spread)}). A gain below {_num(spread)} is not real; call a difference noise only by "
             "citing this."]
    knobs = data.get("knobs") or []
    if knobs:
        keep = [k["name"] for k in knobs if abs(float(k["delta"])) > spread]
        drop = [k["name"] for k in knobs if abs(float(k["delta"])) <= spread]
        lines.append(f"- Knobs, one at a time: above noise {', '.join(keep) or 'none'}; drop from sweeps "
                     f"{', '.join(drop) or 'none'}. No interaction claims from this.")
    return "\n".join(lines) + "\n"


def instrument_summary(campaign: dict, work_dir: Path, iteration: int | None = None) -> str:
    """Summary of the newest valid instrument.json; empty for other profiles or when there is none."""
    from orchestrator.design_profile import is_v7
    if not is_v7(campaign):
        return ""
    found = latest_instrument(work_dir, iteration)
    return format_summary(*found) if found else ""


def _upsert(path: Path, section: str) -> None:
    text = path.read_text()
    start = text.find(HEADING)
    if start != -1:
        nxt = re.search(r"^#{1,2} ", text[start + len(HEADING):], re.MULTILINE)
        end = start + len(HEADING) + nxt.start() if nxt else len(text)
        text = text[:start] + text[end:]
    atomic_write(path, text.rstrip() + "\n\n" + section)


def add_to_handoff(campaign: dict, work_dir: Path, iter_dir: Path, iteration: int) -> None:
    """Put the summary at the end of the campaign handoff and this iteration's snapshot (replacing an old one)."""
    section = instrument_summary(campaign, work_dir, iteration)
    if not section:
        return
    for path in (Path(work_dir) / "handoff.md", Path(iter_dir) / "handoff_snapshot.md"):
        if path.is_file():
            _upsert(path, section)

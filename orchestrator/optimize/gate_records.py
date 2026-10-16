"""Build-gate records out of the agent's reach, sealed with an HMAC.

The build oracles (2(b), 2(c), 2(d), the write scope, the build review) read
records the BUILD stage wrote: ``pre_build_tests.json``,
``baseline_equivalence.json``, ``build_scope.json`` and, after verify,
``authored_tests.json`` and ``build_review.json``. Agent-authored code runs
again after the build (the test command at verify, the run command in every
epoch), so a digest stored NEXT to a record can be rewritten together with it.
Two defences, neither of which trusts the work_dir alone:

* **Out of the repo.** A campaign with a build stage must keep its work_dir
  OUTSIDE the target repo (``NOUS_CAMPAIGN_PARENT``): the agent's cwd, and every
  target command's cwd, is the repo or a checkout of it.
* **HMAC seal.** Each record is sealed with HMAC-SHA256 under a per-campaign
  random key (``.nous_gate_key``, mode 0600, in the work_dir). A record edited
  without the key no longer verifies. ``load`` reads every record ONCE, at the
  top of verify and before any target code runs; the oracles then use those
  in-memory copies, so a rewrite during verify's own test run changes nothing
  they read.

Limits, stated: a process that can read ``.nous_gate_key`` can forge a seal. The
key never enters the repo or a target command's environment, but the build agent
runs as the same OS user, so this raises the bar rather than closing it; the
clean-checkout model (``clean_tree.py``) is what makes the MEASUREMENTS
independent of anything the agent left behind.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

KEY_FILE = ".nous_gate_key"
SEAL_FILE = "gate_records.seal"
BUILD_RECORDS = ("pre_build_tests.json", "baseline_equivalence.json", "build_scope.json")
VERIFY_RECORDS = ("authored_tests.json", "build_review.json")


class GateRecordError(RuntimeError):
    """A build-gate record is missing, unsealed, or fails its seal."""


def _key(work_dir: Path, *, create: bool = False) -> bytes:
    p = Path(work_dir) / KEY_FILE
    if not p.exists():
        if not create:
            raise GateRecordError(f"{KEY_FILE} is missing from the work_dir: the build "
                                  f"records cannot be verified")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    return bytes.fromhex(p.read_text().strip())


def ensure_key(work_dir: Path) -> None:
    _key(work_dir, create=True)


def _mac(key: bytes, name: str, data: bytes) -> str:
    return hmac.new(key, name.encode() + b"\0" + data, hashlib.sha256).hexdigest()


def seal(work_dir: Path, names) -> dict:
    """(Re)seal ``names``; an absent record is sealed as absent."""
    wd = Path(work_dir)
    key = _key(wd, create=True)
    sp = wd / SEAL_FILE
    current = json.loads(sp.read_text()) if sp.exists() else {}
    for n in names:
        p = wd / n
        current[n] = _mac(key, n, p.read_bytes()) if p.exists() else None
    sp.write_text(json.dumps(current, indent=2, sort_keys=True))
    return current


def check(work_dir: Path, name: str) -> str:
    """``ok`` | ``absent`` (sealed as absent) | ``unsealed`` | ``broken``."""
    wd = Path(work_dir)
    try:
        key = _key(wd)
        seals = json.loads((wd / SEAL_FILE).read_text())
    except (GateRecordError, OSError, ValueError):
        return "unsealed"
    if name not in seals:
        return "unsealed"
    p = wd / name
    if seals[name] is None:
        return "absent" if not p.exists() else "broken"
    if not p.exists():
        return "broken"
    return "ok" if hmac.compare_digest(seals[name], _mac(key, name, p.read_bytes())) else "broken"


def require_outside_repo(work_dir: Path, repo: Path | None) -> None:
    if repo is None:
        return
    try:
        Path(work_dir).resolve().relative_to(Path(repo).resolve())
    except ValueError:
        return
    raise GateRecordError(
        f"the campaign work_dir {work_dir} is INSIDE the target repo {repo}. A build "
        f"stage's agent, and every target command, runs in that repo, so its gate "
        f"records would be within their reach. Export NOUS_CAMPAIGN_PARENT to a "
        f"directory outside the repo (e.g. ~/nous-campaigns) and start a fresh "
        f"campaign.")


#: Records the build may legitimately not write (no control was attempted).
OPTIONAL = frozenset({"baseline_equivalence.json"})


def load(work_dir: Path, names=BUILD_RECORDS) -> dict:
    """Every record in ``names``, parsed, each verified against its seal. Raises
    :class:`GateRecordError` on a missing, unsealed, broken or unreadable one;
    an OPTIONAL record sealed as absent loads as None."""
    wd = Path(work_dir)
    out = {}
    for n in names:
        st = check(wd, n)
        if st == "absent" and n in OPTIONAL:
            out[n] = None
            continue
        if st != "ok":
            raise GateRecordError(
                f"build gate record {n} is {st}"
                + (" (missing)" if not (wd / n).exists() else "")
                + ": the evidence the build oracles read cannot be shown to be what "
                  "the build stage wrote. Re-run the build stage in a fresh work_dir.")
        try:
            out[n] = json.loads((wd / n).read_text())
        except (OSError, ValueError) as exc:
            raise GateRecordError(f"build gate record {n} is unreadable ({exc})") from exc
    return out

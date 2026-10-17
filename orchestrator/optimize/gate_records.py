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
  random key kept OUTSIDE the work_dir and the clean tree
  (``key_path``: ``~/.nous/keys/<hash>``, mode 0600, checked on every read). A record edited
  without the key no longer verifies. ``load`` reads every record ONCE, at the
  top of verify and before any target code runs; the oracles then use those
  in-memory copies, so a rewrite during verify's own test run changes nothing
  they read.

Limits, stated: a process that can read the key file can forge a seal. No path
relative to the repo, the work_dir or the clean tree reaches it, and no target
command's environment names it; but the build agent and target code run as the
same OS user, so code that knows Nous's layout can still find ``~/.nous/keys``.
This raises the bar rather than closing it; the
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

SEAL_FILE = "gate_records.seal"
BUILD_RECORDS = ("pre_build_tests.json", "baseline_equivalence.json", "build_scope.json",
                 "clean_tree.json", "mechanism.clean.patch", "mechanism.sha256",
                 "build_isolation.json")
#: Written when the clean tree is created (at verify), sealed at once.
TREE_RECORDS = ("clean_tree.manifest.json", "clean_tree.extras.json",
                "clean_tree.probe.json")
VERIFY_RECORDS = ("authored_tests.json", "build_review.json")


class GateRecordError(RuntimeError):
    """A build-gate record is missing, unsealed, or fails its seal."""


def key_path(work_dir: Path) -> Path:
    """The seal key's location: under the Nous state home (``NOUS_STATE_HOME``,
    default ``~/.nous``) in ``keys/``, named by a hash of the work_dir. NOT in
    the work_dir and not in the clean tree, so no relative path from either
    reaches it, and the target environment carries no path to it."""
    from orchestrator.work_dir_resolver import STATE_HOME_ENV

    home = os.environ.get(STATE_HOME_ENV)
    base = (Path(home).expanduser() if home else Path.home() / ".nous") / "keys"
    tag = hashlib.sha256(str(Path(work_dir).resolve()).encode()).hexdigest()[:24]
    return base / tag


def _key(work_dir: Path, *, create: bool = False) -> bytes:
    p = key_path(work_dir)
    if not p.exists():
        if not create:
            raise GateRecordError(f"the seal key for this work_dir ({p}) is missing: the "
                                  f"build records cannot be verified")
        p.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    mode = p.stat().st_mode & 0o777
    if mode & 0o077:
        raise GateRecordError(f"the seal key {p} is readable by others (mode "
                              f"{oct(mode)}); it must be 0600")
    return bytes.fromhex(p.read_text().strip())


def ensure_key(work_dir: Path) -> None:
    """Create the key for a work_dir that has never been sealed; once a seal
    file exists, a missing key is an error, never a reason to mint a new one
    (round 5, item 4: the build stage called this unconditionally)."""
    wd = Path(work_dir)
    _key(wd, create=not (wd / SEAL_FILE).exists())


def _mac(key: bytes, name: str, data: bytes) -> str:
    return hmac.new(key, name.encode() + b"\0" + data, hashlib.sha256).hexdigest()


def seal(work_dir: Path, names) -> dict:
    """(Re)seal ``names``; an absent record is sealed as absent."""
    wd = Path(work_dir)
    sp = wd / SEAL_FILE
    # A key is created only with the FIRST seal. Once seals exist, a missing
    # key is an error, never a reason to mint a new one (round 4): a fresh key
    # would let a later writer seal forged records that then verify.
    key = _key(wd, create=not sp.exists())
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
        if not n.endswith(".json"):
            out[n] = (wd / n).read_bytes()
            continue
        try:
            out[n] = json.loads((wd / n).read_text())
        except (OSError, ValueError) as exc:
            raise GateRecordError(f"build gate record {n} is unreadable ({exc})") from exc
    return out


#: The keys of baseline_equivalence.json the BUILD stage wrote (verify adds the
#: post-build measurement and its verdict).
BUILD_BASELINE_KEYS = ("levels", "pre", "pre_mean", "pre_unavailable", "tolerance_pct",
                       "workload_seeds", "workload_seed_env")


def confirm_build_part(work_dir: Path, sealed: dict) -> None:
    """Before verify reseals baseline_equivalence.json: its build-written keys
    on disk must equal the sealed copy loaded at the top of verify."""
    mem = sealed.get("baseline_equivalence.json")
    p = Path(work_dir) / "baseline_equivalence.json"
    if mem is None:
        if p.exists():
            raise GateRecordError("baseline_equivalence.json appeared during verify; the "
                                  "build recorded none")
        return
    try:
        disk = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise GateRecordError(f"baseline_equivalence.json became unreadable during "
                              f"verify ({exc})") from exc
    if {k: disk.get(k) for k in BUILD_BASELINE_KEYS} != {k: mem.get(k) for k in BUILD_BASELINE_KEYS}:
        raise GateRecordError(
            "the pre-build control measurement in baseline_equivalence.json was changed "
            "during verify (target code ran there); it will not be resealed. Re-run the "
            "build stage in a fresh work_dir.")

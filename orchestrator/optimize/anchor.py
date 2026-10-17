"""External anchoring of the pre-registration (#321, audit Q7).

``policy.json`` + ``policy.sha256`` live in the work_dir, so any writer of the
work_dir can rewrite the pair consistently and the in-process check (the hash
matches the policy) still passes. An ANCHOR is a copy of what was registered,
written somewhere else at compile time, before the first benchmark run:

* ``policy_sha256`` -- the sidecar, and the hash recomputed from
  ``policy.json`` (anchoring refuses when they differ);
* ``registration`` -- sha256 of the files the epoch's pre-registration is
  made of: ``policy.json``, ``campaign.epoch-<e>.yaml``, the run-order salt
  record and ``mechanism.sha256`` when present (``gate_records.seal`` is
  not: verify legitimately reseals after compile);
* ``inputs`` -- ``provenance.input_hashes`` at that moment (the rows of the
  iterations that ran before compile: plan/build/verify);
* ``digest`` -- sha256 of the canonical JSON of everything above, which is
  the value to timestamp.

Where anchors go:

1. ALWAYS, at compile: an append-only JSONL under the Nous state home,
   ``$NOUS_STATE_HOME/anchors/<work_dir tag>/epoch-<e>.jsonl`` (default
   ``~/.nous``). Outside the work_dir; written with no subprocess.
2. On request, ``nous anchor``: ``--out FILE`` writes the anchor as canonical
   JSON, ready for an RFC 3161 timestamp authority or OpenTimestamps;
   ``--git REPO`` commits it to ``refs/nous/anchors/<run_id>/epoch-<e>`` in a
   git repository; ``--push REMOTE`` (opt-in, needs ``--git``) pushes that ref.

THREAT MODEL, stated rather than implied. Locations 1 and 2 (an unpushed ref)
are writable by any process running as the same OS user, so a same-user agent
that rewrites ``policy.json`` and knows this layout can rewrite the anchor too.
They detect careless or partial edits, an edit by a process that does not know
about anchors, and a work_dir copied elsewhere and altered. Only a copy the
same user cannot rewrite afterwards -- a pushed ref on a remote that refuses
force-pushes, or a third-party timestamp of ``digest`` -- makes the
pre-registration verifiable against a same-user forger.

``verify`` never raises on a mismatch; it returns it, and every caller
(``report.json`` ``provenance.anchor``, ``nous reanalyze``, ``nous anchor
--verify``) reports it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = "nous-anchor/1"
LOCATOR = "anchors.json"   # in the work_dir: where `nous anchor` put extra copies
FAILURE = "anchor_failure.json"   # in the work_dir: why compile could not anchor
REF_PREFIX = "refs/nous/anchors"


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def anchor_dir(work_dir: Path) -> Path:
    """``<state home>/anchors/<tag>``: the same tag scheme as the seal key, so
    it is reached by no path relative to the work_dir or the clean tree."""
    from orchestrator.work_dir_resolver import STATE_HOME_ENV

    home = os.environ.get(STATE_HOME_ENV)
    base = (Path(home).expanduser() if home else Path.home() / ".nous") / "anchors"
    tag = hashlib.sha256(str(Path(work_dir).resolve()).encode()).hexdigest()[:24]
    return base / tag


def _registration_files(work_dir: Path, epoch: int) -> dict[str, str]:
    wd = Path(work_dir)
    out = {}
    for name in ("policy.json", f"campaign.epoch-{epoch}.yaml",
                 f"run_order.epoch-{epoch}.json", "mechanism.sha256"):
        if (wd / name).exists():
            out[name] = _sha_file(wd / name)
    return out


def build_anchor(work_dir: Path, *, run_id: str | None = None) -> dict:
    """The anchor of the epoch whose policy is on disk. Raises ValueError when
    the pre-registration is not intact (an anchor of a broken one is worse
    than none)."""
    from orchestrator.optimize import policy as policy_mod
    from orchestrator.optimize.provenance import input_hashes

    wd = Path(work_dir)
    pol = policy_mod.read_policy(wd)
    if pol is None:
        raise ValueError(f"{wd} has no policy.json: nothing is registered yet")
    side = wd / "policy.sha256"
    recorded = side.read_text().strip() if side.exists() else None
    computed = policy_mod.policy_hash(pol)
    if recorded != computed:
        raise ValueError(
            f"policy.sha256 ({recorded!r}) does not match policy.json ({computed}); "
            f"refusing to anchor a pre-registration that is already not intact")
    epoch = int(pol.get("epoch", 1))
    body = {
        "schema": SCHEMA,
        "run_id": run_id or wd.name,
        "epoch": epoch,
        "policy_sha256": computed,
        "registration": _registration_files(wd, epoch),
        "inputs": input_hashes(wd),
        # How much of this epoch had run when it was anchored. 0 = before any
        # data, the only moment an anchor can bind a pre-registration.
        "epoch_transitions_at_anchor": epoch_transitions_on_disk(wd, epoch),
    }
    return {**body, "digest": hashlib.sha256(_canonical(body).encode()).hexdigest(),
            "anchored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "anchored_at_note": "self-asserted clock; timestamp `digest` externally "
                                "for a time a same-user process cannot set"}


def epoch_transitions_on_disk(work_dir: Path, epoch: int) -> int:
    """Transitions of ``epoch`` already in ``transitions.jsonl`` (data ran)."""
    from orchestrator.optimize import policy as policy_mod

    return sum(1 for t in policy_mod.read_transitions(Path(work_dir))
               if t.get("epoch", 1) == epoch)


class ReanchorAfterData(ValueError):
    """A different policy would be anchored for an epoch that already has data."""


def refuse_reanchor_after_data(work_dir: Path, anchor: dict) -> None:
    """Raise when ``anchor`` registers a policy other than the one already
    anchored for its epoch, after that epoch's first transition. Revising a
    pre-registration after seeing data is exactly what the anchor exists to
    expose, so the product's own command must never launder it."""
    hist = _local_anchors(work_dir).get(anchor["epoch"], [])
    bound = _binding(hist)
    if (bound is not None and bound.get("policy_sha256") != anchor["policy_sha256"]
            and anchor.get("epoch_transitions_at_anchor", 0) > 0):
        raise ReanchorAfterData(
            f"epoch {anchor['epoch']} was anchored with policy "
            f"{str(bound.get('policy_sha256'))[:12]} and has "
            f"{anchor['epoch_transitions_at_anchor']} transition(s) since; refusing "
            f"to anchor policy {anchor['policy_sha256'][:12]} for it after data. "
            f"A revised design is a new epoch (resume recompiles one).")


def _binding(hist: list[dict]) -> dict | None:
    """The anchor that binds an epoch: the LATEST written before any of its
    data (a verify retried before the screen may legitimately re-register).
    Histories from before ``epoch_transitions_at_anchor`` existed bind on the
    latest entry, as they always did."""
    if not hist:
        return None
    pre = [h for h in hist if h.get("epoch_transitions_at_anchor", 0) == 0]
    return pre[-1] if pre else hist[0]


def record_local(work_dir: Path, anchor: dict) -> Path:
    """Append ``anchor`` to the state-home history (append-only: a re-anchor of
    the same epoch never erases the earlier entry)."""
    d = anchor_dir(work_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"epoch-{anchor['epoch']}.jsonl"
    with open(p, "a") as fh:
        fh.write(_canonical(anchor) + "\n")
    return p


def anchor_at_compile(work_dir: Path) -> Path | None:
    """Called right after the policy is written: anchor it locally. A failure
    is logged with its reason and leaves the campaign running unanchored (the
    in-work_dir hash check still applies); verification then reports
    'no anchor' rather than a match."""
    try:
        return record_local(work_dir, build_anchor(work_dir))
    except (OSError, ValueError) as exc:
        logger.error("pre-registration NOT anchored outside the work_dir: %s", exc)
        try:
            (Path(work_dir) / FAILURE).write_text(json.dumps(
                {"reason": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        except OSError:
            pass
        return None


# ── extra copies: a file, a git ref, a pushed ref ─────────────────────────────

def _git(repo: Path, *args, input_: str | None = None) -> str:
    env = {**os.environ}
    for k, v in (("GIT_AUTHOR_NAME", "nous"), ("GIT_AUTHOR_EMAIL", "nous@localhost"),
                 ("GIT_COMMITTER_NAME", "nous"), ("GIT_COMMITTER_EMAIL", "nous@localhost")):
        env.setdefault(k, v)
    proc = subprocess.run(["git", "-C", str(repo), *args], input=input_,
                          capture_output=True, text=True, timeout=60, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def ref_name(anchor: dict) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(anchor["run_id"]))
    return f"{REF_PREFIX}/{safe}/epoch-{anchor['epoch']}"


def write_git(repo: Path, anchor: dict) -> str:
    """Commit the anchor as ``anchor.json`` in an orphan commit and point
    ``ref_name(anchor)`` at it. Returns the commit id."""
    ref = ref_name(anchor)
    try:
        existing = read_git(repo, ref)
    except (RuntimeError, ValueError):
        existing = None
    if existing is not None:
        if existing.get("digest") == anchor["digest"]:
            return _git(repo, "rev-parse", ref)
        raise RuntimeError(
            f"{ref} already holds a different anchor (digest "
            f"{str(existing.get('digest'))[:12]}); an anchor ref is never moved")
    blob = _git(repo, "hash-object", "-w", "--stdin",
                input_=json.dumps(anchor, indent=2, sort_keys=True) + "\n")
    tree = _git(repo, "mktree", input_=f"100644 blob {blob}\tanchor.json\n")
    commit = _git(repo, "commit-tree", tree, "-m",
                  f"nous anchor {anchor['run_id']} epoch {anchor['epoch']}\n\n"
                  f"policy_sha256 {anchor['policy_sha256']}\ndigest {anchor['digest']}\n")
    # Create-only: the empty old value makes update-ref fail if the ref exists.
    _git(repo, "update-ref", ref, commit, "")
    return commit


def push_git(repo: Path, remote: str, anchor: dict) -> None:
    ref = ref_name(anchor)
    _git(repo, "push", remote, f"{ref}:{ref}")


def read_git(repo: Path, ref: str) -> dict:
    return json.loads(_git(repo, "cat-file", "-p", f"{ref}:anchor.json"))


def read_remote(repo: Path, remote: str, ref: str) -> dict:
    """The anchor as the REMOTE holds it: fetched into a private namespace, so
    neither the local ref nor anything in the work_dir is trusted."""
    tmp = f"refs/nous/verify/{ref.removeprefix(REF_PREFIX + '/')}"
    _git(repo, "fetch", "--no-tags", "--force", remote, f"{ref}:{tmp}")
    try:
        return read_git(repo, tmp)
    finally:
        try:
            _git(repo, "update-ref", "-d", tmp)
        except RuntimeError:
            pass


def add_locator(work_dir: Path, entry: dict) -> None:
    p = Path(work_dir) / LOCATOR
    cur = json.loads(p.read_text()) if p.exists() else []
    if entry not in cur:
        cur.append(entry)
    p.write_text(json.dumps(cur, indent=2, sort_keys=True))


# ── verification ─────────────────────────────────────────────────────────────

def _local_anchors(work_dir: Path) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    d = anchor_dir(work_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("epoch-*.jsonl")):
        for ln in p.read_text().splitlines():
            try:
                a = json.loads(ln)
            except ValueError:
                continue
            if isinstance(a, dict) and isinstance(a.get("epoch"), int):
                out.setdefault(a["epoch"], []).append(a)
    return out


def _check_one(work_dir: Path, a: dict, where: str) -> list[str]:
    """Mismatches between one anchor and the work_dir, as sentences."""
    from orchestrator.optimize import policy as policy_mod

    wd = Path(work_dir)
    e = a.get("epoch")
    bad: list[str] = []
    body = {k: v for k, v in a.items() if k not in ("digest", "anchored_at", "anchored_at_note")}
    if hashlib.sha256(_canonical(body).encode()).hexdigest() != a.get("digest"):
        bad.append(f"{where}: the anchor's own digest does not match its contents")
    pol = policy_mod.read_policy(wd)
    if pol is not None and int(pol.get("epoch", 1)) == e:
        if policy_mod.policy_hash(pol) != a.get("policy_sha256"):
            bad.append(f"{where}: epoch {e} anchored policy {str(a.get('policy_sha256'))[:12]} "
                       f"but policy.json now hashes to {policy_mod.policy_hash(pol)[:12]}")
        for name, h in (a.get("registration") or {}).items():
            p = wd / name
            if not p.exists():
                bad.append(f"{where}: {name} was anchored but is missing")
            elif _sha_file(p) != h:
                bad.append(f"{where}: {name} changed after it was anchored")
    else:
        # An earlier epoch: policy.json was overwritten by the recompile, but
        # its registered campaign and salt survive, and every transition it
        # ran under carries its policy hash.
        for name, h in (a.get("registration") or {}).items():
            if name in ("policy.json", "mechanism.sha256"):
                continue
            p = wd / name
            if p.exists() and _sha_file(p) != h:
                bad.append(f"{where}: {name} changed after it was anchored")
    for t in policy_mod.read_transitions(wd):
        if t.get("epoch", 1) == e and t.get("policy_hash") != a.get("policy_sha256"):
            bad.append(f"{where}: transitions.jsonl iteration {t.get('iteration')} of epoch "
                       f"{e} ran under policy {str(t.get('policy_hash'))[:12]}, not the "
                       f"anchored {str(a.get('policy_sha256'))[:12]}")
            break
    for name, h in (a.get("inputs") or {}).items():
        p = wd / name
        if not p.exists():
            bad.append(f"{where}: input {name} was anchored but is missing")
        elif _sha_file(p) != h:
            bad.append(f"{where}: input {name} changed after it was anchored")
    return bad


def verify(work_dir: Path, *, extra: list[dict] | None = None,
           use_git: bool = False, git_repo: Path | None = None,
           remote: str | None = None, run_id: str | None = None) -> dict:
    """``{"present", "matches", "mismatches", "where", "anchors", "reanchored"}``.

    Checks the state-home history: per epoch, the BINDING anchor (the latest
    written before any of that epoch's data, see ``_binding``). An epoch
    re-registered before its data is listed in ``reanchored`` (not a
    mismatch); a different policy anchored AFTER data is a mismatch. Also
    every anchor in ``extra`` (e.g. an exported ``--out`` file); with
    ``use_git``, every git ref ``anchors.json`` lists; and with ``git_repo``
    (plus ``remote``) the ref for each anchored epoch named by the CALLER, so
    a forger who edits ``anchors.json`` cannot drop it -- with ``remote`` it
    is the remote's copy that is read. ``matches`` is None when no anchor
    exists: the pre-registration is then self-attested only.
    """
    wd = Path(work_dir)
    checked: list[tuple[str, dict]] = []
    reanchored = []
    problems: list[str] = []
    local = _local_anchors(wd)
    for e, hist in sorted(local.items()):
        bound = _binding(hist)
        checked.append(("state_home", bound))
        if len({h.get("policy_sha256") for h in hist}) > 1:
            reanchored.append(e)
        for h in hist:
            if (h.get("epoch_transitions_at_anchor", 0) > 0
                    and h.get("policy_sha256") != bound.get("policy_sha256")):
                problems.append(
                    f"state_home: epoch {e} was re-anchored AFTER data with policy "
                    f"{str(h.get('policy_sha256'))[:12]} (bound: "
                    f"{str(bound.get('policy_sha256'))[:12]})")
    for a in extra or []:
        checked.append(("file", a))
    if git_repo is not None:
        rid = run_id or (next(iter(local.values()))[0].get("run_id") if local else wd.name)
        for e in sorted(local) or [1]:
            ref = ref_name({"run_id": rid, "epoch": e})
            where = f"{'remote ' + remote if remote else 'git'}:{ref}"
            try:
                a = (read_remote(Path(git_repo), remote, ref) if remote
                     else read_git(Path(git_repo), ref))
                checked.append((where, a))
            except (RuntimeError, OSError, ValueError) as exc:
                problems.append(f"{where}: no readable anchor ({exc})")
    if use_git:
        loc = wd / LOCATOR
        for ent in (json.loads(loc.read_text()) if loc.exists() else []):
            if ent.get("kind") != "git":
                continue
            try:
                checked.append((f"git:{ent['ref']}", read_git(Path(ent["repo"]), ent["ref"])))
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                problems.append(f"git:{ent.get('ref')}: listed in {LOCATOR} but unreadable "
                                f"({exc})")
    for where, a in checked:
        problems.extend(_check_one(wd, a, where))
    absent_because = None
    if not checked:
        fp = wd / FAILURE
        try:
            absent_because = (json.loads(fp.read_text()).get("reason") if fp.exists()
                              else "no anchor was written (a Nous older than #321, or "
                                   "the state-home copy is on another machine)")
        except (OSError, ValueError):
            absent_because = f"{FAILURE} is unreadable"
    return {
        "absent_because": absent_because,
        "present": bool(checked),
        "matches": (not problems) if checked else None,
        "mismatches": problems,
        "where": ", ".join(sorted({w for w, _ in checked})) or None,
        "anchors": len(checked),
        "reanchored": reanchored,
    }

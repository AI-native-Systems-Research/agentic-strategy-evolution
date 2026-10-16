"""Process isolation for the build agent (round 2, A3).

The build agent's tools run as child processes. A process it starts and leaves
running (a background server, a ``nohup`` loop, a ``setsid`` daemon) would
outlive the agent call and could edit the target, or Nous's records, after
every check has run. ``track`` watches the build call: before it, it records
every existing descendant of this process; while it runs, a poller records
every NEW descendant (with its process group) every ``interval`` seconds; after
it, every recorded process still alive is a SURVIVOR. Survivors are killed --
their whole process group when it is not ours -- and the build fails, with the
record in ``build_isolation.json``.

Why polling: a process that detaches is reparented away from us, so a single
scan after the call cannot find it; the poller sees it while it is still a
descendant. Limit, stated: a process that double-forks and detaches within one
polling interval can escape. Environment-variable tagging would close that, but
macOS does not expose other processes' environments.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class ObservationError(RuntimeError):
    """The process table could not be read: isolation cannot be shown."""


def _table() -> dict[int, tuple[int, int]]:
    """``{pid: (ppid, pgid)}`` for every process. Raises
    :class:`ObservationError` when ``ps`` fails or returns nothing: an empty
    table would read as "no survivors" (round 3, C1)."""
    try:
        proc = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid="], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ObservationError(f"could not observe processes: {exc}") from exc
    if proc.returncode != 0:
        raise ObservationError(f"could not observe processes: ps exited {proc.returncode}")
    t = {}
    for ln in proc.stdout.splitlines():
        parts = ln.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            t[int(parts[0])] = (int(parts[1]), int(parts[2]))
    if not t:
        raise ObservationError("could not observe processes: ps listed none")
    return t


def descendants(root: int, table: dict | None = None) -> dict[int, int]:
    """``{pid: pgid}`` of every descendant of ``root``."""
    table = _table() if table is None else table
    kids: dict[int, list[int]] = {}
    for pid, (ppid, _pg) in table.items():
        kids.setdefault(ppid, []).append(pid)
    out, stack = {}, [root]
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c not in out and c != root:
                out[c] = table[c][1]
                stack.append(c)
    return out


def _alive(pid: int) -> bool:
    """True unless the process is shown to be gone (or a zombie). When the
    table cannot be read the answer is True: unknown is not dead (C1)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                            text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return not st.startswith("Z")


class BuildSurvivors(RuntimeError):
    pass


@contextmanager
def track(work_dir: Path, *, interval: float = 0.2):
    """Context manager around the build call; raises :class:`BuildSurvivors`
    after it when a process the build started is still running."""
    me = os.getpid()
    my_pgid = os.getpgid(0)
    try:
        before = set(descendants(me))
    except ObservationError as exc:
        raise BuildSurvivors(f"{exc}; the build cannot be shown to leave nothing running") from exc
    seen: dict[int, int] = {}
    poll_errors: list[str] = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            try:
                for pid, pg in descendants(me).items():
                    if pid not in before:
                        seen.setdefault(pid, pg)
            except Exception as exc:  # noqa: BLE001 -- recorded, and fails the build
                poll_errors.append(f"{type(exc).__name__}: {exc}")
            stop.wait(interval)

    th = threading.Thread(target=poll, daemon=True)
    th.start()
    try:
        yield
    finally:
        stop.set()
        th.join(timeout=5)
    try:
        for pid, pg in descendants(me).items():
            if pid not in before:
                seen.setdefault(pid, pg)
    except ObservationError as exc:
        poll_errors.append(str(exc))
    survivors = sorted(p for p in seen if _alive(p))
    killed = []
    for pid in survivors:
        pg = seen[pid]
        try:
            if pg != my_pgid:
                os.killpg(pg, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except (ProcessLookupError, PermissionError):
            pass
    record = {"observed_processes": len(seen), "survivors": survivors, "killed": killed,
              "interval_s": interval, "poll_errors": poll_errors}
    (Path(work_dir) / "build_isolation.json").write_text(json.dumps(record, indent=2))
    if poll_errors:
        raise BuildSurvivors(
            f"the build's processes could not be observed throughout the call "
            f"({poll_errors[:3]}); the build cannot be shown to leave nothing "
            f"running. See build_isolation.json.")
    if survivors:
        time.sleep(0.05)
        raise BuildSurvivors(
            f"the build left {len(survivors)} process(es) running after the agent call "
            f"returned (pids {survivors}); they were killed. A process that outlives the "
            f"build could change the target or Nous's records after every check. Make "
            f"the build's background work finish before it returns. See "
            f"build_isolation.json.")

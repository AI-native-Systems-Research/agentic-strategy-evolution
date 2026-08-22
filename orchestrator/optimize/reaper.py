"""Terminate the target adapter's whole process tree, not just its head.

THE DEFECT, REPRODUCED
----------------------
After a campaign was killed, an orphaned ``claude_agent_sdk`` process with
``PPID 1`` was still running — and billing — 18 hours later, from a campaign
stopped a day earlier. SIGTERM to the parent did not reap it.

The mechanism is not specific to the SDK, and it is reproducible in four lines.
``subprocess.run(cmd, timeout=T)`` kills only the DIRECT child when the timeout
fires. Anything that child spawned is reparented to PID 1 and keeps running.
Measured on this machine:

    $ python parent.py            # subprocess.run(timeout=2) on a script
    timed out as expected         # whose body does `sleep 300 &`
    $ ps -o pid,ppid,command
    97500  1  sleep 300           # orphaned, still alive
    97501  1  sleep 300

That is exactly the shape of a real benchmark adapter: a shell script that
starts a server, drives load against it, and prints JSON. Kill the script and
the server survives — holding a GPU, a port, or an API key.

THE FIX, AND WHY THIS ONE
-------------------------
``start_new_session=True`` makes the child a process-group leader, so the whole
subtree shares one process-group id, and ``os.killpg`` reaches all of it. Same
measurement after the change:

    $ python parent2.py
    timed out; killed process group
    $ ps -o pid,ppid,command
    (none — tree fully reaped)

Alternatives considered and rejected:

* **``atexit``** — does not run on SIGKILL, and the reported case was a hard
  kill. It is kept as a BACKSTOP here (see ``_register_atexit``) but cannot be
  the primary mechanism.
* **Signal handlers** — the campaign is a library as much as a CLI, and
  installing a global SIGTERM handler from library code would silently
  override an embedding application's own. The handler is therefore opt-in
  (``install_signal_handlers``), called from the CLI entry point only.
* **``setsid(1)`` the binary** — not available on macOS, and this must work on
  both macOS and Linux.
* **Process groups only, with no tracking** — insufficient for the SDK path,
  which spawns via ``anyio.open_process`` inside the vendored transport where
  this module cannot pass ``start_new_session``. Hence the registry: what we
  cannot spawn correctly, we at least track and reap.

TWO SEAMS, DELIBERATELY SEPARATE
--------------------------------
``run_in_process_group`` replaces the ``subprocess.run`` call in the target
adapter path, where we control the spawn. ``track``/``reap_all`` is the
registry for children spawned elsewhere. Neither makes any decision about
campaign flow.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

#: Live process handles this process spawned, so a terminating campaign can
#: reap trees it would otherwise orphan. A set of the handles themselves rather
#: than of pids: a bare pid can be recycled by the OS between registration and
#: reaping, and signalling a recycled pid kills an unrelated process.
_TRACKED: "set" = set()
_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False

#: Seconds to wait for a group to exit after SIGTERM before escalating to
#: SIGKILL. Short: this runs on the way out, and a benchmark child that ignores
#: SIGTERM is exactly the case that produced an 18-hour orphan.
GRACE_SECONDS = 5.0


def _supports_process_groups() -> bool:
    """POSIX only. On Windows there is no ``killpg``; callers degrade to plain kill."""
    return hasattr(os, "killpg") and hasattr(os, "getpgid") and os.name == "posix"


def track(proc) -> None:
    """Register a live child so ``reap_all`` can terminate its tree."""
    if proc is None:
        return
    with _LOCK:
        _TRACKED.add(proc)
    _register_atexit()


def untrack(proc) -> None:
    """Deregister a child that has already exited."""
    with _LOCK:
        _TRACKED.discard(proc)


def kill_tree(proc, *, grace: float = GRACE_SECONDS) -> bool:
    """SIGTERM then SIGKILL the child's whole process group. True if reaped.

    Escalation is not optional politeness: the reported orphan had survived a
    SIGTERM to its parent for 18 hours. SIGTERM first so a well-behaved child
    can flush and exit; SIGKILL after ``grace`` so a badly-behaved one still
    dies.

    Falls back to signalling the process alone when the group cannot be
    resolved — which happens when the child was NOT spawned with
    ``start_new_session=True`` (it then shares our own group, and killing that
    group would kill us).
    """
    if proc is None or proc.poll() is not None:
        untrack(proc)
        return True

    pgid = None
    if _supports_process_groups():
        try:
            pgid = os.getpgid(proc.pid)
            if pgid == os.getpgid(0):
                # The child shares OUR process group, so it was not started in
                # a new session. Killing the group would kill this process too.
                # Signal the child alone and say so — a leaked grandchild here
                # is a spawn-site defect this function cannot repair.
                logger.warning(
                    "kill_tree: pid %d shares this process's group (%d), so it "
                    "was not spawned with start_new_session=True; signalling "
                    "the process alone. Any grandchildren it spawned will be "
                    "orphaned — fix the spawn site to use "
                    "reaper.run_in_process_group.", proc.pid, pgid,
                )
                pgid = None
        except (OSError, ProcessLookupError):
            pgid = None

    def _signal(sig) -> None:
        if pgid is not None:
            os.killpg(pgid, sig)
        else:
            proc.send_signal(sig)

    try:
        _signal(signal.SIGTERM)
    except (OSError, ProcessLookupError):
        untrack(proc)
        return True

    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            _signal(signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:  # pragma: no cover - kernel-level stall
            logger.error(
                "kill_tree: pid %d survived SIGKILL after %.0fs", proc.pid, grace,
            )
            untrack(proc)
            return False
    untrack(proc)
    return True


def reap_all(*, grace: float = GRACE_SECONDS) -> int:
    """Terminate every tracked child's tree. Returns how many were reaped."""
    with _LOCK:
        procs = list(_TRACKED)
    reaped = 0
    for proc in procs:
        try:
            if proc.poll() is None:
                if kill_tree(proc, grace=grace):
                    reaped += 1
            else:
                untrack(proc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("reap_all: could not reap pid %r: %s",
                           getattr(proc, "pid", "?"), exc)
    if reaped:
        logger.info("reaped %d orphaned child process tree(s)", reaped)
    return reaped


def _register_atexit() -> None:
    """Best-effort backstop for a clean interpreter exit.

    Explicitly NOT the primary mechanism: ``atexit`` does not run on SIGKILL,
    and the reported failure was a hard kill. It catches the ordinary cases —
    an unhandled exception, ``sys.exit``, the end of ``main`` — where a child
    is still in flight.
    """
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    import atexit
    atexit.register(reap_all)
    _ATEXIT_REGISTERED = True


def install_signal_handlers() -> None:
    """Reap tracked trees on SIGTERM/SIGINT, then re-raise the default action.

    OPT-IN, and called from the CLI entry point only. Library code must not
    install global signal handlers: an application embedding ``nous`` has its
    own, and silently replacing them would be a worse bug than the one this
    fixes. Only installs where a handler is not already set to something other
    than the default, so it cannot clobber a caller's.
    """
    if threading.current_thread() is not threading.main_thread():
        # signal.signal only works on the main thread; a worker calling this is
        # a no-op rather than an error.
        return

    def _handler(signum, _frame):
        logger.info("signal %d received — reaping child process trees", signum)
        reap_all()
        # Restore the default and re-raise, so the process dies with the
        # conventional status for that signal rather than exiting 0 and hiding
        # the fact that it was killed.
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except (OSError, ValueError):  # pragma: no cover - defensive
            sys.exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            current = signal.getsignal(sig)
            if current in (signal.SIG_DFL, signal.default_int_handler):
                signal.signal(sig, _handler)
        except (OSError, ValueError):  # pragma: no cover - platform-dependent
            continue
    _register_atexit()


def run_in_process_group(cmd, *, cwd=None, env=None, timeout=None,
                         text: bool = True, capture_output: bool = True):
    """``subprocess.run``, but a timeout reaps the child's whole process tree.

    Drop-in for the ``subprocess.run`` call in the target-adapter path. Returns
    a ``subprocess.CompletedProcess`` and raises ``subprocess.TimeoutExpired``
    on timeout, so every existing caller's ``except`` clause keeps working —
    this changes what happens to the CHILDREN, not the interface.

    ``start_new_session=True`` is the whole mechanism: it puts the child in a
    new session and process group, so ``os.killpg`` on timeout reaches every
    process it spawned. Without it, a benchmark script that backgrounds a
    server leaves that server running after the timeout, which is the measured
    defect this module exists for.
    """
    pipe = subprocess.PIPE if capture_output else None
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=pipe, stderr=pipe, text=text,
        start_new_session=_supports_process_groups(),
    )
    track(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        # Drain whatever the child wrote before it died: the partial output is
        # what `_dump_failed_run` records, and losing it would make a timeout
        # unattributable.
        try:
            out, err = proc.communicate(timeout=1)
        except (subprocess.TimeoutExpired, ValueError, OSError):  # pragma: no cover
            out, err = "", ""
        raise subprocess.TimeoutExpired(
            cmd, timeout, output=out, stderr=err,
        ) from None
    except BaseException:
        # Includes KeyboardInterrupt: a Ctrl-C during a measurement must not
        # leave the benchmark's server running.
        kill_tree(proc)
        raise
    finally:
        untrack(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

"""#322: the post-batch survivor check must not count a process that is still
EXITING after nous killed it as one that escaped.

Field case: 9 timed-out rows, each a multi-GB simulator SIGKILLed by kill_tree;
under load the check ran while they were tearing down. In that window
kill(pid, 0) succeeds, getpgid(pid) raises ESRCH and killpg(pgid, 0) still
answers. The old check put every such pid in ``escaped`` and the stage failed
after 6.5 hours. The race is timing-dependent, so these tests drive the exact
OS answers seen in the field probe at the os-call seam, plus one real
end-to-end process test. Behavioral: they assert what take_survivors returns.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from orchestrator.optimize import isolation, reaper

_MY_PGID = os.getpgid(0)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


@pytest.fixture(autouse=True)
def _drain():
    reaper.take_survivors()
    yield
    reaper.take_survivors()


def test_a_member_that_raises_esrch_on_getpgid_is_gone_not_escaped(monkeypatch):
    """The field probe: _alive() True, getpgid ESRCH, ps stat Z."""
    pid, pgid = 424242, 424242
    monkeypatch.setattr(isolation, "_alive", lambda p: True)
    monkeypatch.setattr(reaper, "start_time", lambda p: "Mon Oct 19 10:00:00 2026")

    def _getpgid(p):
        if p == 0:
            return _MY_PGID
        raise ProcessLookupError(p)

    monkeypatch.setattr(reaper.os, "getpgid", _getpgid)
    monkeypatch.setattr(reaper, "_group_alive", lambda g: False)
    monkeypatch.setattr(reaper, "_settle", lambda g, d, seconds=None: None)
    reaper._reap_leftover_group(
        pgid, ["adapter"], ({pid: pgid}, [], {pid: "Mon Oct 19 10:00:00 2026"}))
    assert reaper.take_survivors() == []


def test_a_group_whose_only_members_are_zombies_is_not_a_survivor(monkeypatch):
    """killpg(pgid, 0) still answers while the last member is a zombie."""
    monkeypatch.setattr(reaper, "_group_alive", lambda g: True)
    monkeypatch.setattr(reaper, "_group_members", lambda g: [])
    monkeypatch.setattr(reaper, "_settle", lambda g, d, seconds=None: None)
    killed = []
    monkeypatch.setattr(reaper.os, "killpg", lambda g, s: killed.append((g, s)))
    reaper._reap_leftover_group(777001, ["adapter"], ({}, [], {}))
    assert reaper.take_survivors() == []
    assert killed == []


def test_a_genuinely_escaped_process_is_still_caught(monkeypatch):
    """The fix must not blind the check: a live descendant in ANOTHER group
    (it called setsid) is a survivor and is killed."""
    pid, pgid, other = 515151, 515150, 600000
    monkeypatch.setattr(isolation, "_alive", lambda p: True)
    monkeypatch.setattr(reaper, "start_time", lambda p: "same")
    monkeypatch.setattr(reaper.os, "getpgid",
                        lambda p: _MY_PGID if p == 0 else other)
    monkeypatch.setattr(reaper, "_group_alive", lambda g: False)
    monkeypatch.setattr(reaper, "_settle", lambda g, d, seconds=None: None)
    killed = []
    monkeypatch.setattr(reaper.os, "killpg", lambda g, s: killed.append(g))
    reaper._reap_leftover_group(pgid, ["adapter"], ({pid: pgid}, [], {pid: "same"}))
    (s,) = reaper.take_survivors()
    assert s["escaped_session"] == [pid] and other in killed


def test_the_settle_waits_for_a_slow_teardown_then_returns():
    """A real child that takes ~0.6 s to exit after SIGTERM: the settle
    period lets it finish instead of the check counting it."""
    p = subprocess.Popen([sys.executable, "-c",
                          "import signal,time\n"
                          "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(0.6), exit(0)))\n"
                          "time.sleep(30)"],
                         start_new_session=True)
    time.sleep(0.3)
    os.killpg(p.pid, 15)
    t0 = time.monotonic()
    reaper._settle(p.pid, {p.pid: p.pid}, seconds=10)
    p.wait(timeout=5)
    assert 0.3 < time.monotonic() - t0 < 5
    reaper._reap_leftover_group(p.pid, ["slow"], ({}, [], {}))
    assert reaper.take_survivors() == []


def test_a_timed_out_command_with_a_slow_exiting_grandchild_is_not_a_survivor(tmp_path):
    """End to end: the command times out, kill_tree SIGKILLs the group, and a
    grandchild that is still tearing down when the check runs is not counted."""
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n")
    with pytest.raises(subprocess.TimeoutExpired):
        reaper.run_in_process_group([sys.executable, str(script)], timeout=1.0)
    assert reaper.take_survivors() == []

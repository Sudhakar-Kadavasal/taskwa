"""Send-pacing / ban-hygiene tests (v1.6.5).

The timing code was the repo's biggest untested area. These tests exercise the
pure planner and the global throttle - no real sleeping beyond a few hundred
milliseconds, and no network.
"""
import os
import random
import tempfile
import time

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BACKUP_DIR", tempfile.mkdtemp())

import pytest

from app import waha
from app.waha import MIN_INTERVAL, plan_gaps


# ---------------- plan_gaps: the spacing ----------------
def test_every_gap_lands_in_the_configured_range():
    gaps = plan_gaps(12, 15, 30, random.Random(1))
    assert len(gaps) == 11
    assert all(15 <= g <= 30 for g in gaps)


def test_twelve_digests_take_a_few_minutes_not_ninety_seconds():
    gaps = plan_gaps(12, 15, 30, random.Random(7))
    assert 2.5 * 60 <= sum(gaps) <= 6 * 60


def test_gaps_do_not_shrink_as_the_team_grows():
    """The reason this is a gap rule and not a fixed window: a bigger fan-out
    is the RISKIER one, so it must not be sent faster - it just takes longer."""
    small = plan_gaps(5, 15, 30, random.Random(2))
    big = plan_gaps(60, 15, 30, random.Random(2))
    assert all(15 <= g <= 30 for g in small + big)
    assert sum(big) > sum(small) * 5


def test_zero_gaps_for_a_dry_run_rehearsal():
    assert plan_gaps(10, 0, 0) == [0.0] * 9


def test_single_message_has_no_gaps():
    assert plan_gaps(1, 15, 30) == []
    assert plan_gaps(0, 15, 30) == []


def test_gaps_are_not_machine_perfect():
    """A fixed rhythm is exactly what an automation detector looks for."""
    gaps = plan_gaps(20, 15, 30, random.Random(11))
    assert len(set(round(g, 3) for g in gaps)) > 15


def test_reversed_bounds_are_tolerated():
    assert all(15 <= g <= 30 for g in plan_gaps(5, 30, 15, random.Random(4)))


# ---------------- the global throttle ----------------
@pytest.fixture(autouse=True)
def fast_throttle(monkeypatch):
    """Shrink the interval so the tests run in milliseconds, not minutes."""
    monkeypatch.setattr(waha, "MIN_INTERVAL", 0.10)
    monkeypatch.setattr(waha, "MAX_INTERVAL", 0.12)
    waha._last_send_at[0] = 0.0
    yield


def test_throttle_separates_two_immediate_sends():
    waha._throttle()
    t0 = time.monotonic()
    waha._throttle()
    assert time.monotonic() - t0 >= 0.10 - 0.01


def test_throttle_does_not_delay_a_lone_message():
    """An interactive reply must not wait: nothing was sent recently."""
    waha._last_send_at[0] = time.monotonic() - 60
    t0 = time.monotonic()
    waha._throttle()
    assert time.monotonic() - t0 < 0.02


def test_throttle_holds_across_concurrent_batches():
    """Two batches running at once (a nudge and the digest) must not produce
    two sends at the same instant - this is the guarantee that replaced the
    old whole-batch lock."""
    import threading
    stamps = []

    def worker():
        for _ in range(4):
            waha._throttle()
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    deltas = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(d >= 0.10 - 0.02 for d in deltas), deltas


def test_paced_send_does_not_hold_a_whole_batch_lock(monkeypatch):
    """The batch must not hold a global lock: an urgent blocker alert has to
    get out while a slow digest run is still trickling."""
    sent = []
    monkeypatch.setattr(waha, "send_text", lambda cid, txt: sent.append(cid))
    monkeypatch.setattr(waha.time, "sleep", lambda s: None)   # no real waiting
    waha.paced_send([(f"{i}@c.us", "hi") for i in range(5)],
                    min_gap=15, max_gap=30)
    assert len(sent) == 5

"""Gateway auto-recovery (v1.7.1).

Two layers under test:

(a) plan_gateway_action() - the PURE decision (no DB, no sleeping): when to
    auto-restart a FAILED/STOPPED session, when to hold on the backoff, and
    when to stop and escalate to a human. Restarting is NEVER the answer for a
    genuine logout (SCAN_QR_CODE / PASSKEY) or a dead container (UNREACHABLE) -
    a restart can't fix those and looping it only adds ban risk on a personal
    number.

(b) check_gateway_health() - the wiring: reads the PREVIOUS status before
    session_status() refreshes the cache (the bug this release fixes: the old
    code read it after, so the was-WORKING -> now-FAILED transition was never
    detectable), calls restart_session on the right ticks, respects the cap,
    and clears the budget the moment the session is WORKING again.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import scheduler, waha
from app.db import engine, session_scope, get_setting, set_setting
from app.models import Base
from app.scheduler import (plan_gateway_action, check_gateway_health,
                           AUTO_RESTART_MAX, AUTO_RESTART_BACKOFF_MIN)


# ---------------- pure decision matrix ----------------
def test_working_is_a_noop():
    assert plan_gateway_action("WORKING", 0, None, True) == "noop"
    assert plan_gateway_action("WORKING", 3, 999, True) == "noop"


def test_first_failure_restarts_immediately():
    assert plan_gateway_action("FAILED", 0, None, True) == "restart"
    assert plan_gateway_action("STOPPED", 0, None, True) == "restart"
    assert plan_gateway_action("NOT_STARTED", 0, None, True) == "restart"


def test_backoff_holds_until_the_window_elapses():
    # attempt 1 must wait AUTO_RESTART_BACKOFF_MIN[1] minutes
    need = AUTO_RESTART_BACKOFF_MIN[1]
    assert plan_gateway_action("FAILED", 1, need - 0.1, True) == "wait"
    assert plan_gateway_action("FAILED", 1, need, True) == "restart"
    assert plan_gateway_action("FAILED", 1, need + 100, True) == "restart"
    # no timestamp on record (never restarted yet this streak) -> allowed
    assert plan_gateway_action("FAILED", 1, None, True) == "restart"


def test_widening_backoff_is_monotonic():
    assert AUTO_RESTART_BACKOFF_MIN == sorted(AUTO_RESTART_BACKOFF_MIN)


def test_cap_reached_escalates():
    assert plan_gateway_action("FAILED", AUTO_RESTART_MAX, 999, True) == "escalate"
    assert plan_gateway_action("FAILED", AUTO_RESTART_MAX + 5, 999, True) == "escalate"


def test_disabled_never_restarts():
    assert plan_gateway_action("FAILED", 0, None, False) == "escalate"


@pytest.mark.parametrize("status", ["SCAN_QR_CODE", "PASSKEY_REQUIRED",
                                    "PASSKEY_CONFIRMATION_REQUIRED",
                                    "UNREACHABLE", "UNKNOWN"])
def test_non_restartable_statuses_never_restart(status):
    # regardless of attempts/backoff/enabled, these are escalate-only
    assert plan_gateway_action(status, 0, None, True) == "escalate"
    assert plan_gateway_action(status, 2, 999, True) == "escalate"


# ---------------- wiring / state machine ----------------
@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    scheduler._last_alerted_status["value"] = None
    yield


def _set(**kw):
    with session_scope() as s:
        for k, v in kw.items():
            set_setting(s, k, v)


def _fake_status(value):
    """Stand-in for waha.session_status(): returns `value` AND writes the
    cache, exactly like the real one - so `prev` on the next tick is correct."""
    def _f():
        with session_scope() as s:
            set_setting(s, "gateway_status", value)
            set_setting(s, "gateway_status_at", "t")
        return value
    return _f


def _restart_counter(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(waha, "restart_session",
                        lambda: calls.__setitem__("n", calls["n"] + 1) or True)
    return calls


def _get(key):
    with session_scope() as s:
        return get_setting(s, key)


def test_first_failed_tick_restarts_and_counts(db, monkeypatch):
    _set(gateway_status="WORKING", auto_restart_enabled=True,
         gateway_restart_attempts=0)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("FAILED"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 1
    assert _get("gateway_restart_attempts") == 1
    assert _get("gateway_restart_at")            # a timestamp was stamped


def test_second_tick_inside_backoff_holds(db, monkeypatch):
    # one restart already made, stamped just now -> next tick must WAIT
    _set(gateway_status="FAILED", auto_restart_enabled=True,
         gateway_restart_attempts=1,
         gateway_restart_at=datetime.utcnow().isoformat(timespec="seconds"))
    monkeypatch.setattr(scheduler, "session_status", _fake_status("FAILED"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 0                        # held, no restart
    assert _get("gateway_restart_attempts") == 1  # unchanged


def test_tick_after_backoff_restarts_again(db, monkeypatch):
    old = (datetime.utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
    _set(gateway_status="FAILED", auto_restart_enabled=True,
         gateway_restart_attempts=1, gateway_restart_at=old)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("FAILED"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 1
    assert _get("gateway_restart_attempts") == 2


def test_cap_stops_restarting(db, monkeypatch):
    old = (datetime.utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
    _set(gateway_status="FAILED", auto_restart_enabled=True,
         gateway_restart_attempts=AUTO_RESTART_MAX, gateway_restart_at=old)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("FAILED"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 0                        # gave up, escalates instead
    assert _get("gateway_restart_attempts") == AUTO_RESTART_MAX


def test_disabled_setting_blocks_restart(db, monkeypatch):
    _set(gateway_status="FAILED", auto_restart_enabled=False,
         gateway_restart_attempts=0)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("FAILED"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 0


def test_scan_qr_is_never_auto_restarted(db, monkeypatch):
    _set(gateway_status="WORKING", auto_restart_enabled=True,
         gateway_restart_attempts=0)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("SCAN_QR_CODE"))
    calls = _restart_counter(monkeypatch)
    check_gateway_health()
    assert calls["n"] == 0
    assert _get("gateway_restart_attempts") == 0


def test_recovery_clears_budget_and_warms_lids(db, monkeypatch):
    _set(gateway_status="FAILED", auto_restart_enabled=True,
         gateway_restart_attempts=3,
         gateway_restart_at=datetime.utcnow().isoformat(timespec="seconds"))
    warm = {"n": 0}
    monkeypatch.setattr(waha, "list_groups",
                        lambda: warm.__setitem__("n", warm["n"] + 1) or [])
    monkeypatch.setattr(scheduler, "session_status", _fake_status("WORKING"))
    _restart_counter(monkeypatch)
    check_gateway_health()
    assert _get("gateway_restart_attempts") == 0   # budget cleared
    assert _get("gateway_restart_at") == ""
    assert warm["n"] == 1                           # lid map warmed on recovery

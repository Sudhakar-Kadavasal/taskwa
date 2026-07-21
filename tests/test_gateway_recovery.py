"""Gateway health check is OBSERVE-ONLY (v1.7.2).

The auto-restarter was removed by design: restarting/re-pairing a personal
WhatsApp number repeatedly is itself a ban signal, so recovery is a MANUAL
button on the Health page, never automatic. These tests lock that in:

- check_gateway_health() NEVER restarts the session, whatever the status.
- It still refreshes the cached status and, on recovery to WORKING, warms the
  LID->phone map (the one useful side effect, unrelated to restarting).
- The prev-status bug stays fixed: prev is read before session_status()
  overwrites the cache, so a WORKING->FAILED transition is detectable.
"""
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import scheduler, waha
from app.db import engine, session_scope, get_setting, set_setting
from app.models import Base
from app.scheduler import check_gateway_health


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


def _get(key):
    with session_scope() as s:
        return get_setting(s, key)


def _fake_status(value):
    """Stand-in for waha.session_status(): returns `value` AND writes the cache,
    exactly like the real one - so `prev` on the next tick is correct."""
    def _f():
        with session_scope() as s:
            set_setting(s, "gateway_status", value)
            set_setting(s, "gateway_status_at", "t")
        return value
    return _f


def _guard_no_restart(monkeypatch):
    """Any call to a session-mutating WAHA action fails the test loudly."""
    def _boom(*a, **k):
        raise AssertionError("health check must NOT touch the session")
    monkeypatch.setattr(waha, "restart_session", _boom)
    monkeypatch.setattr(waha, "stop_session", _boom)
    monkeypatch.setattr(waha, "logout_session", _boom)
    monkeypatch.setattr(waha, "start_session", _boom)


@pytest.mark.parametrize("status", ["FAILED", "STOPPED", "NOT_STARTED",
                                    "SCAN_QR_CODE", "UNREACHABLE", "STARTING"])
def test_health_check_never_restarts(db, monkeypatch, status):
    _set(gateway_status="WORKING")
    _guard_no_restart(monkeypatch)
    monkeypatch.setattr(scheduler, "session_status", _fake_status(status))
    check_gateway_health()                      # must not raise
    assert _get("gateway_status") == status      # cache refreshed


def test_working_is_a_noop_and_refreshes_cache(db, monkeypatch):
    _set(gateway_status="FAILED")
    _guard_no_restart(monkeypatch)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("WORKING"))
    # list_groups runs the LID warmup on recovery - stub it so no network
    warm = {"n": 0}
    monkeypatch.setattr(waha, "list_groups",
                        lambda: warm.__setitem__("n", warm["n"] + 1) or [])
    check_gateway_health()
    assert _get("gateway_status") == "WORKING"
    assert warm["n"] == 1        # warmed once, because prev != WORKING


def test_no_warmup_when_already_working(db, monkeypatch):
    _set(gateway_status="WORKING")
    _guard_no_restart(monkeypatch)
    monkeypatch.setattr(scheduler, "session_status", _fake_status("WORKING"))
    warm = {"n": 0}
    monkeypatch.setattr(waha, "list_groups",
                        lambda: warm.__setitem__("n", warm["n"] + 1) or [])
    check_gateway_health()
    assert warm["n"] == 0        # steady WORKING -> no repeated warmup


def test_auto_restart_machinery_is_gone(db):
    """Guard against a future accidental reintroduction of the auto-restarter."""
    assert not hasattr(scheduler, "plan_gateway_action")
    assert not hasattr(scheduler, "AUTO_RESTART_MAX")
    # the settings that fed it are gone from defaults too
    from app.db import DEFAULTS
    assert "auto_restart_enabled" not in DEFAULTS
    assert "gateway_restart_attempts" not in DEFAULTS

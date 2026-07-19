"""Settings-page validation for the board-snapshot section (v1.7 follow-up).

Covers what test_weekly_boards.py doesn't: the HTTP-level guardrails in
settings_save - rejecting (not truncating) more than 2 days, rejecting a
stale admin_id, and that a valid submission actually persists."""
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ui
from app.db import engine, get_setting, session_scope, set_setting
from app.models import Base, Member


BASE_FORM = {
    "timezone": "Asia/Dubai", "send_times": "08:00", "ack_mode": "reaction",
    "hourly_cap": 60, "min_gap_seconds": 15, "max_gap_seconds": 30,
    "jitter_minutes": 6, "purge_after_days": 30,
    "weekly_board_time": "08:05",
}


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        set_setting(s, "setup_complete", True)
        s.add(Member(name="Sudhakar", phone="971500000001", role="admin"))
    monkeypatch.setattr(ui, "_authed", lambda request: True)
    app = FastAPI()
    app.include_router(ui.router)
    return TestClient(app)


def test_more_than_two_days_rejected_nothing_saved(client):
    form = dict(BASE_FORM, **{"weekly_board_days": ["0", "1", "2"]})
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    assert "/settings?err=" in r.headers["location"]
    with session_scope() as s:
        # rejected submission must not have partially applied ANY setting,
        # including the unrelated ones on the same form
        assert get_setting(s, "weekly_board_days") == []
        assert get_setting(s, "hourly_cap") == 60   # untouched default, not saved


def test_two_days_accepted_and_persisted(client):
    form = dict(BASE_FORM, **{"weekly_board_days": ["0", "3"]})
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    assert "/settings?err=" not in r.headers["location"]
    with session_scope() as s:
        assert sorted(get_setting(s, "weekly_board_days")) == [0, 3]


def test_stale_admin_id_rejected(client):
    with session_scope() as s:
        s.add(Member(name="Retired", phone="971500000098", role="admin",
                     active=False))
    with session_scope() as s:
        retired_id = s.query(Member).filter(Member.name == "Retired").first().id
    form = dict(BASE_FORM, **{"weekly_board_admin_id": retired_id})
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    assert "/settings?err=" in r.headers["location"]
    with session_scope() as s:
        assert get_setting(s, "weekly_board_admin_id") == 0   # not saved


def test_valid_admin_id_persisted(client):
    with session_scope() as s:
        s.add(Member(name="Mathew", phone="971500000099", role="admin"))
    with session_scope() as s:
        mathew_id = s.query(Member).filter(Member.name == "Mathew").first().id
    form = dict(BASE_FORM, **{"weekly_board_admin_id": mathew_id})
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    assert "/settings?err=" not in r.headers["location"]
    with session_scope() as s:
        assert get_setting(s, "weekly_board_admin_id") == mathew_id


def test_settings_page_shows_admin_dropdown_and_day_checkboxes(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Board snapshot" in r.text
    assert "Weekly board snapshot" not in r.text   # old heading is gone
    assert 'name="weekly_board_days"' in r.text
    assert 'name="weekly_board_admin_id"' in r.text

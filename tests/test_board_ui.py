"""Dashboard board page + preview-to-self button.

The web preview must obey the same invariant as the WhatsApp command: every
rendered image is addressed to the admin's own WhatsApp, never to the selected
member/group. Auth is stubbed; the render + dispatch path is real (send_image
is captured so nothing hits the gateway)."""
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ui, waha
from app.db import engine, SessionLocal, session_scope, set_setting
from app.models import Base, Member, Group, Task
from app.engine import create_task


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        set_setting(s, "setup_complete", True)
    monkeypatch.setattr(ui, "_authed", lambda request: True)  # skip login
    app = FastAPI()
    app.include_router(ui.router)          # only the UI router - no scheduler
    return TestClient(app)


@pytest.fixture()
def team():
    with session_scope() as s:
        s.add(Member(name="Sudhakar", phone="971500000001", role="admin"))
        s.add(Member(name="Ravi", phone="971500000002", role="member"))
        s.add(Group(name="Site A", chat_id="120363111@g.us"))
    with session_scope() as s:
        admin = s.query(Member).filter(Member.phone == "971500000001").first()
        ravi = s.query(Member).filter(Member.phone == "971500000002").first()
        g = s.query(Group).first()
        create_task(s, title="Ravi task", assignee=ravi, creator=admin)
        create_task(s, title="Group task", assignee=ravi, creator=admin,
                    post_to_group_id=g.id)
        return admin.id, ravi.id, g.id


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(waha, "send_image",
                        lambda chat, png, cap: calls.append((chat, png, cap)))
    return calls


# ---------------- GET /board ----------------
def test_board_page_renders(client, team):
    r = client.get("/board")
    assert r.status_code == 200
    assert "Board" in r.text
    assert "IN PROGRESS" in r.text or "In progress".upper() in r.text
    assert "Preview selected boards" in r.text   # the picker is present


def test_board_page_assignee_filter(client, team):
    admin_id, ravi_id, _ = team
    r = client.get(f"/board?assignee={ravi_id}")
    assert r.status_code == 200
    assert "Ravi task" in r.text


# ---------------- POST /board/preview ----------------
def test_preview_sends_selected_member_to_admin_only(client, team, monkeypatch):
    admin_id, ravi_id, _ = team
    calls = _capture(monkeypatch)
    r = client.post("/board/preview", data={"member_ids": [ravi_id]},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "/board?msg=" in r.headers["location"]
    # one image, addressed to the ADMIN's chat, not Ravi's
    assert len(calls) == 1
    chat, png, cap = calls[0]
    assert chat == "971500000001@c.us"   # admin, NOT 971500000002 (Ravi)
    assert png[:4] == b"\x89PNG" and "Ravi" in cap


def test_preview_member_and_group_all_to_admin(client, team, monkeypatch):
    admin_id, ravi_id, g_id = team
    calls = _capture(monkeypatch)
    r = client.post("/board/preview",
                    data={"member_ids": [ravi_id], "group_ids": [g_id]},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(calls) == 2
    assert all(chat == "971500000001@c.us" for chat, _, _ in calls)
    caps = [c for _, _, c in calls]
    assert any("Site A" in c and "group" in c for c in caps)


def test_preview_empty_selection_errors(client, team, monkeypatch):
    calls = _capture(monkeypatch)
    r = client.post("/board/preview", data={}, follow_redirects=False)
    assert r.status_code == 303
    assert "/board?err=" in r.headers["location"]
    assert calls == []          # nothing rendered or sent


def test_board_page_shows_admin_picker_when_multiple_admins(client, team, monkeypatch):
    with session_scope() as s:
        s.add(Member(name="Mathew", phone="971500000099", role="admin"))
    r = client.get("/board")
    assert r.status_code == 200
    assert '<select name="admin_id">' in r.text
    assert "Mathew" in r.text


def test_board_page_hides_picker_for_single_admin(client, team, monkeypatch):
    r = client.get("/board")
    assert r.status_code == 200
    assert '<select name="admin_id">' not in r.text
    assert 'name="admin_id" value=' in r.text   # hidden field still present


def test_preview_defaults_to_lowest_id_admin_when_unspecified(client, team, monkeypatch):
    admin_id, ravi_id, _ = team
    with session_scope() as s:
        s.add(Member(name="Mathew", phone="971500000099", role="admin"))
    calls = _capture(monkeypatch)
    r = client.post("/board/preview", data={"member_ids": [ravi_id]},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(calls) == 1
    assert calls[0][0] == "971500000001@c.us"   # Sudhakar (lowest id), not Mathew


def test_preview_honours_explicit_admin_choice(client, team, monkeypatch):
    admin_id, ravi_id, _ = team
    with session_scope() as s:
        s.add(Member(name="Mathew", phone="971500000099", role="admin"))
    with session_scope() as s:
        mathew_id = s.query(Member).filter(Member.name == "Mathew").first().id
    calls = _capture(monkeypatch)
    r = client.post("/board/preview",
                    data={"member_ids": [ravi_id], "admin_id": mathew_id},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(calls) == 1
    assert calls[0][0] == "971500000099@c.us"   # Mathew, as explicitly chosen


def test_preview_rejects_inactive_admin_id(client, team, monkeypatch):
    admin_id, ravi_id, _ = team
    with session_scope() as s:
        s.add(Member(name="Retired", phone="971500000098", role="admin",
                     active=False))
    with session_scope() as s:
        retired_id = s.query(Member).filter(Member.name == "Retired").first().id
    calls = _capture(monkeypatch)
    r = client.post("/board/preview",
                    data={"member_ids": [ravi_id], "admin_id": retired_id},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "/board?err=" in r.headers["location"]
    assert calls == []   # never falls back to sending to someone else


def test_preview_selected_empty_member_still_renders(client, monkeypatch):
    """A member with no tasks, ticked explicitly, still renders (the picker
    must never silently drop a selection)."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        set_setting(s, "setup_complete", True)
        s.add(Member(name="Sudhakar", phone="971500000001", role="admin"))
        s.add(Member(name="Idle", phone="971500000005", role="member"))
    with session_scope() as s:
        idle = s.query(Member).filter(Member.phone == "971500000005").first()
        idle_id = idle.id
    calls = _capture(monkeypatch)
    r = client.post("/board/preview", data={"member_ids": [idle_id]},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(calls) == 1
    assert calls[0][0] == "971500000001@c.us"

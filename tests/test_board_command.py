"""/board and admin-only /board preview.

Invariant under test: a member's own /board renders to THEIR DM; the admin's
/board preview renders any/all boards but sends every image to the ADMIN's own
DM - never to the person the board is about (private rehearsal). Non-admins
can't preview at all."""
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.db import engine, SessionLocal
from app.models import Base, Member, Group, Task
from app.engine import create_task
from app.commands import handle_message


@pytest.fixture()
def s():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def team(s):
    admin = Member(name="Sudhakar", phone="971500000001", role="admin")
    ravi = Member(name="Ravi", phone="971500000002", role="member")
    priya = Member(name="Priya", phone="971500000003", role="member")
    s.add_all([admin, ravi, priya])
    s.commit()
    return admin, ravi, priya


def _seed(s, team):
    """One personal task each, plus a group with one posted task."""
    admin, ravi, priya = team
    create_task(s, title="Admin task", assignee=admin, creator=admin)
    create_task(s, title="Ravi task", assignee=ravi, creator=admin)
    g = Group(name="Site A", chat_id="120363111@g.us")
    s.add(g)
    s.flush()
    create_task(s, title="Group task", assignee=priya, creator=admin,
                post_to_group_id=g.id)
    s.commit()
    return g


def _admin_chat(admin):
    return f"{admin.phone}@c.us"


# ---------------- /board (self) ----------------
def test_board_renders_to_sender_dm(s, team):
    admin, ravi, _ = team
    create_task(s, title="Ravi task", assignee=ravi, creator=admin)
    s.commit()
    r = handle_message(s, ravi, "/board", admin)
    assert len(r.image_sends) == 1
    chat, png, cap = r.image_sends[0]
    assert chat == "971500000002@c.us"   # ravi's OWN dm, not the admin
    assert isinstance(png, (bytes, bytearray)) and png[:4] == b"\x89PNG"
    assert cap == "Your board"
    assert r.text == ""                  # nothing posted to any chat but the image


def test_myboard_alias_works(s, team):
    admin, ravi, _ = team
    r = handle_message(s, ravi, "/myboard", admin)
    assert len(r.image_sends) == 1
    assert r.image_sends[0][0] == "971500000002@c.us"


# ---------------- /board preview (admin) ----------------
def test_preview_no_args_all_boards_to_admin(s, team):
    admin, ravi, priya = team
    _seed(s, team)
    r = handle_message(s, admin, "/board preview", admin)
    # 3 members with tasks + 1 group with a task
    assert len(r.image_sends) == 4
    # EVERY image is addressed to the admin, nobody else
    assert all(chat == _admin_chat(admin) for chat, _, _ in r.image_sends)
    assert all(png[:4] == b"\x89PNG" for _, png, _ in r.image_sends)
    caps = [c for _, _, c in r.image_sends]
    assert any("Site A" in c and "group" in c for c in caps)


def test_preview_named_member_only_to_admin(s, team):
    admin, ravi, priya = team
    _seed(s, team)
    r = handle_message(s, admin, "/board preview @Ravi", admin)
    assert len(r.image_sends) == 1
    chat, png, cap = r.image_sends[0]
    assert chat == _admin_chat(admin)    # to the admin, NOT to Ravi
    assert "Ravi" in cap
    assert png[:4] == b"\x89PNG"


def test_preview_named_group_only_to_admin(s, team):
    admin, ravi, priya = team
    g = _seed(s, team)
    r = handle_message(s, admin, "/board preview #Site.A", admin)
    assert len(r.image_sends) == 1
    chat, _, cap = r.image_sends[0]
    assert chat == _admin_chat(admin)
    assert "Site A" in cap and "group" in cap


def test_preview_named_member_renders_even_if_empty(s, team):
    """An explicitly named member is rendered even with no tasks - the admin
    asked for it. (No-args mode skips empties; named mode does not.)"""
    admin, ravi, _ = team   # no tasks seeded at all
    r = handle_message(s, admin, "/board preview @Priya", admin)
    assert len(r.image_sends) == 1
    assert r.image_sends[0][0] == _admin_chat(admin)


# ---------------- guards ----------------
def test_preview_refused_for_non_admin(s, team):
    admin, ravi, priya = team
    _seed(s, team)
    r = handle_message(s, ravi, "/board preview", admin)
    assert not r.image_sends
    assert "admin" in (r.text or "").lower()


def test_preview_silent_in_group(s, team):
    admin, _, _ = team
    _seed(s, team)
    r = handle_message(s, admin, "/board preview", admin, is_group=True)
    assert not r.image_sends
    assert r.unmatched and not r.text


def test_preview_unresolved_name_reports_not_sends(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/board preview @Nobody", admin)
    assert not r.image_sends
    assert "resolve" in (r.text or "").lower()


def test_preview_no_tasks_says_nothing_to_preview(s, team):
    admin, _, _ = team   # active members but zero tasks
    r = handle_message(s, admin, "/board preview", admin)
    assert not r.image_sends
    assert "nothing to preview" in (r.text or "").lower()

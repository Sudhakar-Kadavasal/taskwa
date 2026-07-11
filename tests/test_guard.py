"""Outbound allowlist guard: nobody unregistered ever receives a message."""
import os, sys, tempfile
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BACKUP_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import engine, SessionLocal, session_scope, set_setting
from app.models import Base, Member, Group, MessageLog
from app.waha import send_text


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        set_setting(s, "dry_run", True)
        s.add(Member(name="Sk", phone="971500000001", role="admin"))
        s.add(Group(name="Team", chat_id="120363001@g.us"))
        s.add(Member(name="Ex", phone="971500000009", role="member",
                     active=False))


def _log_status(chat_id):
    s = SessionLocal()
    row = (s.query(MessageLog).filter(MessageLog.chat_id == chat_id)
            .order_by(MessageLog.id.desc()).first())
    s.close()
    return row.status if row else None


def test_member_receives():
    assert send_text("971500000001@c.us", "hi") is True
    assert _log_status("971500000001@c.us") == "dryrun"


def test_registered_group_receives():
    assert send_text("120363001@g.us", "hi") is True
    assert _log_status("120363001@g.us") == "dryrun"


def test_stranger_blocked():
    assert send_text("971599999999@c.us", "hi") is False
    assert _log_status("971599999999@c.us") == "blocked"


def test_unregistered_group_blocked():
    assert send_text("120363999@g.us", "hi") is False
    assert _log_status("120363999@g.us") == "blocked"


def test_deactivated_member_blocked():
    assert send_text("971500000009@c.us", "hi") is False
    assert _log_status("971500000009@c.us") == "blocked"


# ---------------- cold-boot catch-up slot logic (v1.3.1) ----------------
from datetime import datetime, timedelta, timezone as _tz
from app.scheduler import latest_due_slot


def test_latest_due_slot():
    tz = _tz.utc
    now = datetime(2026, 7, 11, 10, 0, tzinfo=tz)
    # 08:00 today is the most recent due slot
    assert latest_due_slot(now, ["08:00"]).hour == 8
    assert latest_due_slot(now, ["08:00"]).day == 11
    # 17:00 hasn't happened today -> yesterday's 17:00
    s = latest_due_slot(now, ["17:00"])
    assert s.day == 10 and s.hour == 17
    # multiple slots -> the latest past one wins
    s = latest_due_slot(now, ["08:00", "09:30", "17:00"])
    assert (s.hour, s.minute) == (9, 30)
    # no times -> None
    assert latest_due_slot(now, []) is None


# ---------------- bulk member import (v1.5.0) ----------------
from app.engine import bulk_add_members


def test_bulk_add_members_dedupe_and_normalise():
    s = SessionLocal()
    try:
        before = s.query(Member).count()
        added, skipped = bulk_add_members(s, [
            {"name": "Ravi", "phone": "+91 98407 67767", "role": "member"},
            {"name": "", "phone": "971500000111", "role": "admin"},   # name falls back to phone
            {"name": "Dup", "phone": "9198 40767767", "role": "member"},  # dup of row 1
            {"name": "Sk", "phone": "971500000001", "role": "member"},    # already exists
            {"name": "NoPhone", "phone": "", "role": "member"},
            {"name": "BadRole", "phone": "971500000222", "role": "root"}, # role coerced
        ])
        s.flush()
        assert added == 3 and skipped == 3
        m = (s.query(Member)
              .filter(Member.phone == "919840767767").first())
        assert m and m.name == "Ravi"
        m2 = s.query(Member).filter(Member.phone == "971500000111").first()
        assert m2.name == "971500000111" and m2.role == "admin"
        m3 = s.query(Member).filter(Member.phone == "971500000222").first()
        assert m3.role == "member"
        s.rollback()
    finally:
        s.close()


# ---------------- broadcasts (v1.6.0) ----------------
from app.broadcasts import days_to_cron, render_message, recipients_for
from app.models import Broadcast as _B
import json as _j


def test_days_to_cron():
    assert days_to_cron([0, 2, 4]) == "mon,wed,fri"
    assert days_to_cron([]) == "*"
    assert days_to_cron(list(range(7))) == "*"
    assert days_to_cron([6]) == "sun"
    assert days_to_cron([9, -1, 3]) == "thu"   # invalid days dropped


def test_render_message_placeholders():
    out = render_message("Hi! Today is {day}, {date}.", "UTC")
    assert "{day}" not in out and "{date}" not in out
    assert render_message("no placeholders", "UTC") == "no placeholders"
    # bad tz falls back without crashing
    assert "{day}" not in render_message("{day}", "Not/AZone")


def test_recipients_resolution_and_inactive_skipped():
    s = SessionLocal()
    try:
        m1 = Member(name="A", phone="971500001111")
        m2 = Member(name="B", phone="971500002222", active=False)
        g1 = Group(name="G", chat_id="120363999@g.us")
        s.add_all([m1, m2, g1]); s.flush()
        b = _B(name="t", message="hello",
               member_ids=_j.dumps([m1.id, m2.id, 424242]),
               group_ids=_j.dumps([g1.id]))
        r = recipients_for(s, b)
        assert r == ["971500001111@c.us", "120363999@g.us"]
        s.rollback()
    finally:
        s.close()

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

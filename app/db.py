import json
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import env

os.makedirs(env.data_dir, exist_ok=True)
DB_PATH = os.path.join(env.data_dir, "tasks.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------- settings helpers ----------------
DEFAULTS = {
    "setup_complete": False,
    "admin_password_hash": "",
    "timezone": "Asia/Dubai",
    "send_times": ["08:00"],
    "dry_run": True,
    "ack_mode": "reaction",          # none | reaction | reply
    "personal_mode": False,          # bot runs on the owner's personal number
    "hourly_cap": 60,
    "min_gap_seconds": 15,           # spacing between two messages of a run
    "max_gap_seconds": 30,
    "jitter_minutes": 6,             # +/- drift on every scheduled start time
    "purge_after_days": 30,
    "weekly_board_enabled": False,   # board snapshot - OFF until ready
    "weekly_board_days": [],         # list of 0=Mon..6=Sun; max 2; empty = no cron
    "weekly_board_time": "08:05",
    "weekly_board_test_mode": False,  # redirect every image to one admin (rehearsal)
    "weekly_board_admin_id": 0,      # 0 = auto (lowest-id active admin)
    "last_send": "",
    "last_backup": "",
    "gateway_status": "UNKNOWN",
    "gateway_status_at": "",
}


def get_setting(s, key):
    from .models import Setting
    row = s.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return json.loads(row.value)


def set_setting(s, key, value):
    from .models import Setting
    row = s.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=json.dumps(value))
        s.add(row)
    else:
        row.value = json.dumps(value)

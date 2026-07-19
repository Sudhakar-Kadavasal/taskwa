"""Board snapshot scheduler job (v1.7, step 5 + follow-up).

Three things under test: (a) scheduling is gated by weekly_board_enabled AND
at least one (max 2) day being configured - test mode never affects whether
the job exists; (b) the recipient split - test mode redirects every image to
an admin, real mode delivers to each member's/group's own chat (that
real-vs-preview recipient contrast is intentional; see send_weekly_boards'
docstring); (c) the test-mode admin is configurable (weekly_board_admin_id),
defaulting to the lowest-id active admin, and a stale id skips rather than
silently falling back to someone else."""
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import scheduler, waha
from app.db import engine, session_scope, set_setting
from app.models import Base, Member, Group
from app.engine import create_task
from app.scheduler import (send_weekly_boards, reload_board_jobs,
                           _BOARD_JOB_ID)


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    # never leave the shared module scheduler holding a board job between tests
    if scheduler.scheduler.get_job(_BOARD_JOB_ID):
        scheduler.scheduler.remove_job(_BOARD_JOB_ID)


def _team_with_tasks():
    """Admin with NO tasks (so it's skipped and can't muddy the recipient
    assertions), two members and a group that DO have tasks."""
    with session_scope() as s:
        s.add(Member(name="Sudhakar", phone="971500000001", role="admin"))
        s.add(Member(name="Ravi", phone="971500000002", role="member"))
        s.add(Member(name="Priya", phone="971500000003", role="member"))
        s.add(Group(name="Site A", chat_id="120363111@g.us"))
    with session_scope() as s:
        admin = s.query(Member).filter(Member.phone == "971500000001").first()
        ravi = s.query(Member).filter(Member.phone == "971500000002").first()
        priya = s.query(Member).filter(Member.phone == "971500000003").first()
        g = s.query(Group).first()
        create_task(s, title="Ravi task", assignee=ravi, creator=admin)
        create_task(s, title="Priya task", assignee=priya, creator=admin)
        create_task(s, title="Group task", assignee=ravi, creator=admin,
                    post_to_group_id=g.id)


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(waha, "send_image",
                        lambda chat, png, cap: calls.append((chat, png, cap)))
    return calls


def _set(**kw):
    with session_scope() as s:
        for k, v in kw.items():
            set_setting(s, k, v)


# ---------------- scheduling gate ----------------
def test_disabled_registers_no_job(db):
    _set(weekly_board_enabled=False)
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is None


def test_enabled_registers_the_job(db):
    _set(weekly_board_enabled=True, weekly_board_days=[2], weekly_board_time="09:15")
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is not None


def test_enabled_but_no_days_registers_no_job(db):
    """enabled=true alone isn't enough - at least one day must be ticked."""
    _set(weekly_board_enabled=True, weekly_board_days=[], weekly_board_time="09:15")
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is None


def test_two_days_registers_one_job_firing_on_both(db):
    _set(weekly_board_enabled=True, weekly_board_days=[0, 3],
         weekly_board_time="09:15")
    reload_board_jobs()
    job = scheduler.scheduler.get_job(_BOARD_JOB_ID)
    assert job is not None
    assert "mon" in str(job.trigger) and "thu" in str(job.trigger)


def test_more_than_two_days_defensively_capped(db):
    """settings_save is the primary guard against >2 days; this proves the
    scheduler itself never blows up or schedules more than 2 even if a bad
    value somehow reaches storage another way."""
    import re
    _set(weekly_board_enabled=True, weekly_board_days=[0, 1, 2, 3],
         weekly_board_time="09:15")
    reload_board_jobs()
    job = scheduler.scheduler.get_job(_BOARD_JOB_ID)
    assert job is not None
    dow = re.search(r"day_of_week='([^']*)'", str(job.trigger)).group(1)
    assert len(dow.split(",")) <= 2   # at most 2 day tokens, not 4


def test_test_mode_does_not_gate_scheduling(db):
    """enabled=true + test_mode=true + a configured day must STILL register
    the job - test mode changes only the recipient, never whether the cron
    fires. This is the full risk-free rehearsal combination."""
    _set(weekly_board_enabled=True, weekly_board_test_mode=True,
         weekly_board_days=[0])
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is not None


def test_reload_removes_job_when_disabled_again(db):
    _set(weekly_board_enabled=True, weekly_board_days=[0])
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is not None
    _set(weekly_board_enabled=False)
    reload_board_jobs()
    assert scheduler.scheduler.get_job(_BOARD_JOB_ID) is None


# ---------------- recipient split ----------------
def test_test_mode_redirects_everything_to_admin(db, monkeypatch):
    _team_with_tasks()
    _set(weekly_board_enabled=True, weekly_board_test_mode=True)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert len(calls) == 3          # Ravi, Priya, Site A - admin has no tasks
    admin_chat = "971500000001@c.us"
    # EVERY image goes to the admin; no real member/group chat is ever a target
    assert all(chat == admin_chat for chat, _, _ in calls)
    caps = [c for _, _, c in calls]
    assert any("would go to: Ravi" in c for c in caps)
    assert any("would go to: Priya" in c for c in caps)
    assert any("would go to: Site A" in c and "group" in c for c in caps)
    # explicit: nobody but the admin was addressed
    assert "971500000002@c.us" not in [chat for chat, _, _ in calls]
    assert "120363111@g.us" not in [chat for chat, _, _ in calls]


def test_real_mode_delivers_to_each_own_chat_not_admin(db, monkeypatch):
    """CONTRAST WITH TEST MODE / PREVIEW: with test mode off, each board is
    sent to that MEMBER'S / GROUP'S own chat - NOT the admin's. Do not "fix"
    this to send to the admin; the preview and test-mode paths do that on
    purpose, this real weekly send does not."""
    _team_with_tasks()
    _set(weekly_board_enabled=True, weekly_board_test_mode=False)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert len(calls) == 3
    targets = sorted(chat for chat, _, _ in calls)
    assert targets == ["120363111@g.us",        # the group
                       "971500000002@c.us",      # Ravi's own chat
                       "971500000003@c.us"]      # Priya's own chat
    # the admin (no tasks) is never in the recipient set in real mode
    assert "971500000001@c.us" not in targets
    caps = [c for _, _, c in calls]
    assert all("would go to:" not in c for c in caps)   # no test tagging


def test_disabled_send_is_a_noop(db, monkeypatch):
    _team_with_tasks()
    _set(weekly_board_enabled=False)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert calls == []          # gate inside the job, not just the scheduler


def test_test_mode_without_active_admin_skips(db, monkeypatch):
    """Test mode with no admin to redirect to must NOT fall through to a real
    team send - it skips entirely."""
    with session_scope() as s:
        s.add(Member(name="Ravi", phone="971500000002", role="member"))
    with session_scope() as s:
        ravi = s.query(Member).filter(Member.phone == "971500000002").first()
        create_task(s, title="Ravi task", assignee=ravi)
    _set(weekly_board_enabled=True, weekly_board_test_mode=True)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert calls == []


# ---------------- explicit admin_id (Settings dropdown) ----------------
def test_test_mode_honours_explicit_admin_choice(db, monkeypatch):
    """weekly_board_admin_id, when set, overrides the lowest-id-admin default."""
    _team_with_tasks()
    with session_scope() as s:
        s.add(Member(name="Mathew", phone="971500000099", role="admin"))
    with session_scope() as s:
        mathew_id = s.query(Member).filter(Member.name == "Mathew").first().id
    _set(weekly_board_enabled=True, weekly_board_test_mode=True,
         weekly_board_admin_id=mathew_id)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert len(calls) == 3
    # Mathew (explicitly chosen), NOT Sudhakar (lowest id)
    assert all(chat == "971500000099@c.us" for chat, _, _ in calls)


def test_test_mode_stale_admin_id_skips_not_falls_back(db, monkeypatch):
    """A configured admin_id that's no longer an active admin must skip the
    run, never silently fall back to a different admin (same rule as the
    dashboard preview picker)."""
    _team_with_tasks()
    with session_scope() as s:
        s.add(Member(name="Retired", phone="971500000098", role="admin",
                     active=False))
    with session_scope() as s:
        retired_id = s.query(Member).filter(Member.name == "Retired").first().id
    _set(weekly_board_enabled=True, weekly_board_test_mode=True,
         weekly_board_admin_id=retired_id)
    calls = _capture(monkeypatch)
    send_weekly_boards()
    assert calls == []   # not redirected to Sudhakar (lowest id) either

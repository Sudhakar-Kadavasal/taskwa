"""Parser + engine tests. Run: pytest -q"""
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.db import engine, SessionLocal
from app.models import Base, Member, Task
from app.engine import (change_status, create_task, open_tasks_for,
                        PermissionError_, InvalidTransition)
from app.commands import handle_message, parse_date_word


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


def _task(s, team, **kw):
    admin, ravi, _ = team
    defaults = dict(title="Buy cement", assignee=ravi, creator=admin)
    defaults.update(kw)
    t = create_task(s, **defaults)
    s.commit()
    return t


# ---------------- status protocol ----------------
def test_done_by_assignee(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, f"{t.id} done", admin)
    assert r.react and not r.text
    assert s.get(Task, t.id).status == "done"


def test_done_by_non_assignee_refused(s, team):
    admin, ravi, priya = team
    t = _task(s, team)
    r = handle_message(s, priya, f"{t.id} done", admin)
    assert r.text and "assignee" in r.text.lower() or "admin" in r.text.lower()
    assert s.get(Task, t.id).status == "open"


def test_admin_can_close_anyones_task(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, admin, f"{t.id} done", admin)
    assert r.react
    assert s.get(Task, t.id).status == "done"


def test_in_progress_variants(s, team):
    admin, ravi, _ = team
    for text in ["{} in progress", "{} inprogress", "{} in-progress", "{} wip",
                 "#{} In Progress"]:
        t = _task(s, team)
        r = handle_message(s, ravi, text.format(t.id), admin)
        assert r.react, text
        assert s.get(Task, t.id).status == "in_progress", text


def test_blocker_requires_reason_and_alerts_admin(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, f"{t.id} blocker", admin)
    assert r.text and "reason" in r.text.lower()
    r = handle_message(s, ravi, f"{t.id} blocker waiting on supplier quote", admin)
    assert r.react and r.alert_admin and "supplier" in r.alert_admin
    t2 = s.get(Task, t.id)
    assert t2.status == "blocked" and t2.blocker_reason == "waiting on supplier quote"


def test_reopen(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    handle_message(s, ravi, f"{t.id} done", admin)
    r = handle_message(s, ravi, f"{t.id} reopen", admin)
    assert r.react
    assert s.get(Task, t.id).status == "open"


def test_unknown_task(s, team):
    admin, ravi, _ = team
    r = handle_message(s, ravi, "999 done", admin)
    assert r.text and "no task" in r.text.lower()


def test_unmatched_gets_help_hint(s, team):
    admin, ravi, _ = team
    r = handle_message(s, ravi, "hello there", admin)
    assert r.text and "/help" in r.text


# ---------------- /add with confirmation ----------------
def test_add_confirm_flow(s, team):
    admin, ravi, priya = team
    r = handle_message(s, admin, "/add Send invoice @Priya fri !high", admin)
    assert r.text and "Y to confirm" in r.text and "Priya" in r.text
    r2 = handle_message(s, admin, "y", admin)
    assert "Created task #" in r2.text
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == "Send invoice"
    assert t.assignee_id == priya.id
    assert t.priority == "high"
    assert t.due_date is not None and t.due_date.weekday() == 4


def test_add_cancel(s, team):
    admin, _, _ = team
    handle_message(s, admin, "/add Something @Ravi", admin)
    r = handle_message(s, admin, "n", admin)
    assert "Cancelled" in r.text
    assert s.query(Task).count() == 0


def test_add_unknown_member(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/add Fix pump @Bob", admin)
    assert "recognise" in r.text


# ---------------- queries ----------------
def test_mytasks_and_list(s, team):
    admin, ravi, _ = team
    _task(s, team, title="Task A")
    _task(s, team, title="Task B", priority="high")
    r = handle_message(s, ravi, "/mytasks", admin)
    assert "Task A" in r.text and "Task B" in r.text
    # high priority listed first
    assert r.text.index("Task B") < r.text.index("Task A")
    r2 = handle_message(s, ravi, "/help", admin)
    assert "blocker" in r2.text


# ---------------- date words ----------------
def test_date_words():
    today = date(2026, 7, 10)  # a Friday
    assert parse_date_word("today", today) == today
    assert parse_date_word("tomorrow", today) == today + timedelta(days=1)
    assert parse_date_word("fri", today) == today + timedelta(days=7)  # next fri
    assert parse_date_word("mon", today) == date(2026, 7, 13)
    assert parse_date_word("25/07", today) == date(2026, 7, 25)
    assert parse_date_word("01/03", today) == date(2027, 3, 1)  # rolls forward
    assert parse_date_word("banana", today) is None


# ---------------- engine guards ----------------
def test_cancelled_is_terminal(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    change_status(s, t, admin, "cancelled")
    with pytest.raises(InvalidTransition):
        change_status(s, t, admin, "open")


def test_blocked_days_and_digest_order(s, team):
    admin, ravi, _ = team
    t1 = _task(s, team, title="Low", priority="low")
    t2 = _task(s, team, title="High", priority="high")
    t3 = _task(s, team, title="DueSoon", due_date=date.today())
    tasks = open_tasks_for(s, ravi)
    assert [t.title for t in tasks] == ["High", "DueSoon", "Low"]


# ---------------- personal-number / group silence support ----------------
def test_unmatched_flag_set_only_for_chatter(s, team):
    admin, ravi, _ = team
    assert handle_message(s, ravi, "hello there", admin).unmatched is True
    t = _task(s, team)
    # recognised-but-wrong commands are NOT unmatched (user addressed the bot)
    assert handle_message(s, ravi, "999 done", admin).unmatched is False
    assert handle_message(s, ravi, f"{t.id} blocker", admin).unmatched is False
    assert handle_message(s, ravi, "/help", admin).unmatched is False


# ---------------- numbered digest protocol (v1.2) ----------------
from app.engine import save_digest_refs
from app.digest import build_member_digest, ordered_for_digest


def test_digest_numbers_and_positional_reply(s, team):
    admin, ravi, _ = team
    t1 = _task(s, team, title="Alpha", priority="high")
    t2 = _task(s, team, title="Beta")
    ordered = ordered_for_digest(open_tasks_for(s, ravi))
    save_digest_refs(s, ravi, ordered)
    s.flush()
    text = build_member_digest(ravi, ordered)
    assert "1. [HIGH] Alpha" in text and "2. Beta" in text and "#" not in text
    # "1 done" closes the HIGH task (digest position), not serial 1
    r = handle_message(s, ravi, "1 done", admin)
    assert r.react
    assert s.get(Task, t1.id).status == "done"
    assert s.get(Task, t2.id).status == "open"


def test_dotted_number_and_block_alias(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, f"{t.id}. block waiting on cement", admin)
    assert r.react and r.alert_admin
    assert s.get(Task, t.id).status == "blocked"


def test_bare_done_single_task(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, "done", admin)
    assert r.react
    assert s.get(Task, t.id).status == "done"


def test_bare_block_single_task_needs_reason(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, "block", admin)
    assert r.text and "reason" in r.text.lower()
    r = handle_message(s, ravi, "block stuck at customs", admin)
    assert r.react and "customs" in r.alert_admin


def test_bare_done_multiple_tasks_prompts_softly(s, team):
    admin, ravi, _ = team
    _task(s, team, title="A"); _task(s, team, title="B")
    r = handle_message(s, ravi, "done", admin)
    assert r.unmatched is True          # silent in groups/personal mode
    assert "add the number" in r.text   # visible hint on a dedicated bot DM
    assert all(t.status == "open" for t in s.query(Task).all())


def test_quoted_reply_resolves_task(s, team):
    admin, ravi, _ = team
    t1 = _task(s, team, title="Alpha")
    t2 = _task(s, team, title="Beta")
    # swipe-reply on the creation echo of Beta
    r = handle_message(s, ravi, "done", admin,
                       quoted=f"Created task #{t2.id}: Beta -> Ravi")
    assert r.react
    assert s.get(Task, t2.id).status == "done"
    assert s.get(Task, t1.id).status == "open"


def test_quoted_full_digest_is_ambiguous(s, team):
    admin, ravi, _ = team
    _task(s, team, title="A"); _task(s, team, title="B")
    ordered = ordered_for_digest(open_tasks_for(s, ravi))
    save_digest_refs(s, ravi, ordered)
    s.flush()
    digest = build_member_digest(ravi, ordered)
    r = handle_message(s, ravi, "done", admin, quoted=digest)
    assert r.text and "several tasks" in r.text
    assert all(t.status == "open" for t in s.query(Task).all())


# ---------------- group digest numbering + de-dup (v1.3) ----------------
from app.models import Group
from app.engine import save_group_digest_refs
from app.digest import build_group_digest


def test_group_digest_numbered_with_footer_and_resolution(s, team):
    admin, ravi, priya = team
    grp = Group(name="Team", chat_id="120363001@g.us")
    s.add(grp); s.flush()
    t1 = _task(s, team, title="Group task A", post_to_group_id=grp.id)
    t2 = create_task(s, title="Group task B", assignee=priya, creator=admin,
                     post_to_group_id=grp.id)
    s.flush()
    ordered = [t1, t2]
    save_group_digest_refs(s, grp.id, ordered)
    s.flush()
    text = build_group_digest(grp, ordered)
    assert "1. Group task A" in text and "2. Group task B" in text
    assert "Reply:  1 done" in text and "#" not in text
    # Ravi replies "1 done" in the group -> group map -> his task
    r = handle_message(s, ravi, "1 done", admin, is_group=True,
                       group_id=grp.id)
    assert r.react
    assert s.get(Task, t1.id).status == "done"
    # Ravi tries "2 done" -> Priya's task -> permission refused
    r = handle_message(s, ravi, "2 done", admin, is_group=True,
                       group_id=grp.id)
    assert r.text and "Priya" in r.text
    assert s.get(Task, t2.id).status == "open"


def test_group_tasks_not_duplicated_in_dm_digest(s, team):
    admin, ravi, _ = team
    grp = Group(name="Team", chat_id="120363002@g.us")
    s.add(grp); s.flush()
    _task(s, team, title="DM only")
    _task(s, team, title="Group only", post_to_group_id=grp.id)
    from app.digest import ordered_for_digest
    tasks = open_tasks_for(s, ravi)
    dm_tasks = [t for t in tasks if t.post_to_group_id not in {grp.id}]
    assert [t.title for t in dm_tasks] == ["DM only"]
    # /mytasks still shows everything
    r = handle_message(s, ravi, "/mytasks", admin)
    assert "DM only" in r.text and "Group only" in r.text


# ---------------- /add in a group (v1.3.1) ----------------
def test_group_add_assign_and_autopost(s, team):
    admin, ravi, priya = team
    grp = Group(name="Team", chat_id="120363003@g.us")
    s.add(grp); s.flush()
    # Ravi creates a task for Priya inside the group
    r = handle_message(s, ravi, "/add Send invoice @Priya fri", admin,
                       is_group=True, group_id=grp.id)
    assert "Y to confirm" in r.text and "Priya" in r.text
    # Priya's 'y' must NOT confirm Ravi's draft
    r2 = handle_message(s, priya, "y", admin, is_group=True, group_id=grp.id)
    assert s.query(Task).count() == 0
    # Ravi confirms
    r3 = handle_message(s, ravi, "y", admin, is_group=True, group_id=grp.id)
    assert "Created task #" in r3.text
    t = s.query(Task).first()
    assert t.assignee_id == priya.id
    assert t.post_to_group_id == grp.id   # auto-posts to the group it came from


def test_native_mention_by_phone_digits(s, team):
    admin, ravi, priya = team
    r = handle_message(s, ravi, f"/add Call the auditor @{priya.phone}", admin)
    assert r.text and "Priya" in r.text and "Y to confirm" in r.text

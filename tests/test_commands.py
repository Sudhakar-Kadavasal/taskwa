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


# ------- assignee notification + acceptance dialogue (v1.6.3) -------
def test_created_receipt_has_reply_footer_when_self_assigned(s, team):
    admin, _, _ = team
    handle_message(s, admin, "/add Pay the rent", admin)
    r = handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert f"Reply:  {t.id} done" in r.text          # no more dead-end receipt


def test_assignee_notified_with_acceptance_dialogue(s, team):
    admin, _, priya = team
    handle_message(s, admin, "/add Send invoice @Priya fri", admin)
    r = handle_message(s, admin, "y", admin)
    assert "asked to accept" in r.text               # creator told what happens
    assert len(r.extra_sends) == 1                   # DM queued for Priya
    cid, txt = r.extra_sends[0]
    assert cid == "971500000003@c.us"
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert "New task from Sudhakar" in txt
    assert "Reply Y to accept" in txt
    assert f"{t.id} done" in txt                     # serial footer included
    r2 = handle_message(s, priya, "y", admin)        # Priya accepts
    assert "Accepted" in r2.text
    assert s.get(Task, t.id).status == "open"        # accepted != started


def test_group_posted_task_skips_assignee_dm(s, team):
    admin, ravi, _ = team
    handle_message(s, admin, "/add Fix pump @Ravi", admin,
                   is_group=True, group_id=1)
    r = handle_message(s, admin, "y", admin, is_group=True, group_id=1)
    assert not r.extra_sends                         # group digest covers it
    assert "daily list" in r.text


def test_stale_expired_pending_does_not_crash_notification(s, team):
    """Regression (live 11 Jul): an EXPIRED PendingConfirm left in the table
    (member_id is UNIQUE) crashed notify_assignee with IntegrityError,
    rolling back task creation entirely."""
    from datetime import datetime, timedelta
    import json as _json
    from app.models import PendingConfirm
    admin, ravi, _ = team
    s.add(PendingConfirm(member_id=ravi.id,                   # stale leftover
                         draft_json=_json.dumps({"kind": "accept", "task_id": 999}),
                         expires_at=datetime.utcnow() - timedelta(hours=1)))
    s.flush()
    handle_message(s, admin, "/add Fix pump @Ravi", admin)
    r = handle_message(s, admin, "y", admin)                  # crashed before
    assert "Created task #" in r.text
    assert len(r.extra_sends) == 1
    assert "Reply Y to accept" in r.extra_sends[0][1]
    pends = s.query(PendingConfirm).filter(
        PendingConfirm.member_id == ravi.id).all()
    assert len(pends) == 1                                    # replaced, not duplicated
    assert _json.loads(pends[0].draft_json)["task_id"] != 999


def test_active_pending_not_clobbered_by_notification(s, team):
    """If the assignee has a LIVE confirmation in flight (their own /add
    draft), the acceptance dialogue is skipped - their draft survives."""
    admin, ravi, priya = team
    handle_message(s, ravi, "/add My own thing", admin)       # Ravi's live draft
    handle_message(s, admin, "/add Fix pump @Ravi", admin)
    r = handle_message(s, admin, "y", admin)
    assert len(r.extra_sends) == 1
    assert "Reply Y to accept" not in r.extra_sends[0][1]     # no dialogue
    r2 = handle_message(s, ravi, "y", admin)                  # confirms HIS draft
    assert "Created task #" in r2.text and "My own thing" in r2.text


def test_silence_counts_as_accepted_after_window(s, team):
    """30 min without Y/N -> auto-accepted, audit event written, queue
    cleared; a still-live dialogue and expired /add drafts are untouched."""
    from datetime import datetime, timedelta
    import json as _json
    from app.models import PendingConfirm, StatusEvent
    from app.scheduler import expire_acceptance_dialogs
    admin, ravi, priya = team
    t = _task(s, team)                                        # Ravi's task
    s.add(PendingConfirm(member_id=ravi.id,                   # expired accept
          draft_json=_json.dumps({"kind": "accept", "task_id": t.id}),
          expires_at=datetime.utcnow() - timedelta(minutes=1)))
    s.add(PendingConfirm(member_id=priya.id,                  # live accept
          draft_json=_json.dumps({"kind": "accept", "task_id": t.id}),
          expires_at=datetime.utcnow() + timedelta(minutes=25)))
    s.add(PendingConfirm(member_id=admin.id,                  # expired draft
          draft_json=_json.dumps({"title": "x", "assignee_id": admin.id,
                                  "priority": "medium", "due": ""}),
          expires_at=datetime.utcnow() - timedelta(minutes=1)))
    s.commit()
    expire_acceptance_dialogs()
    left = {p.member_id for p in s.query(PendingConfirm).all()}
    assert ravi.id not in left                    # swept
    assert priya.id in left and admin.id in left  # untouched
    ev = (s.query(StatusEvent)
           .filter(StatusEvent.task_id == t.id,
                   StatusEvent.note.like("auto-accepted%")).all())
    assert len(ev) == 1 and ev[0].actor_id == ravi.id
    assert s.get(Task, t.id).status == "open"     # task itself unchanged


def test_decline_returns_task_to_creator(s, team):
    admin, ravi, _ = team
    handle_message(s, admin, "/add Fix pump @Ravi", admin)
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    r = handle_message(s, ravi, "n", admin)          # Ravi declines
    assert f"back to {admin.name}" in r.text
    assert s.get(Task, t.id).assignee_id == admin.id  # returned to initiator
    assert s.get(Task, t.id).status == "open"         # never cancelled
    assert len(r.extra_sends) == 1                    # creator gets one DM
    cid, txt = r.extra_sends[0]
    assert cid == "971500000001@c.us" and "declined" in txt
    assert not r.alert_admin                          # no second message


# ------- block waiting on @person -> unblock returns it (v1.6.3) -------
def test_block_waiting_on_person_and_unblock(s, team):
    admin, ravi, priya = team
    t = _task(s, team)                                # Ravi's task
    r = handle_message(s, ravi, f"{t.id} block waiting on @Priya", admin)
    assert r.react
    task = s.get(Task, t.id)
    assert task.status == "blocked"
    assert task.waiting_on_id == priya.id
    assert len(r.extra_sends) == 1                    # Priya notified (DM)
    cid, txt = r.extra_sends[0]
    assert cid == "971500000003@c.us"
    assert "waiting on you" in txt and f"{t.id} unblock" in txt
    assert "Waiting on: Priya" in r.alert_admin
    # Priya releases it
    r2 = handle_message(s, priya, f"{t.id} unblock sent the quote", admin)
    assert r2.react
    task = s.get(Task, t.id)
    assert task.status == "in_progress"               # back with Ravi, active
    assert task.waiting_on_id is None
    assert task.assignee_id == ravi.id
    assert len(r2.extra_sends) == 1                   # Ravi told it's back
    cid2, txt2 = r2.extra_sends[0]
    assert cid2 == "971500000002@c.us"
    assert "back to you, Ravi" in txt2 and f"{t.id} done" in txt2


def test_waiting_person_cannot_close_the_task(s, team):
    admin, ravi, priya = team
    t = _task(s, team)
    handle_message(s, ravi, f"{t.id} block waiting on @Priya", admin)
    r = handle_message(s, priya, f"{t.id} done", admin)   # not her call
    assert r.text and "can't move" in r.text
    assert s.get(Task, t.id).status == "blocked"


def test_unblock_by_uninvolved_member_refused(s, team):
    admin, ravi, priya = team
    t = _task(s, team)
    handle_message(s, ravi, f"{t.id} block waiting on supplier", admin)
    assert s.get(Task, t.id).waiting_on_id is None    # no @member mentioned
    r = handle_message(s, priya, f"{t.id} unblock", admin)
    assert r.text and "admin" in r.text               # permission refused
    assert s.get(Task, t.id).status == "blocked"


def test_unblock_on_unblocked_task(s, team):
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, f"{t.id} unblock", admin)
    assert "isn't blocked" in r.text


def test_digest_shows_waiting_on(s, team):
    from app.digest import build_member_digest, waiting_on_section
    admin, ravi, priya = team
    t = _task(s, team)
    handle_message(s, ravi, f"{t.id} block waiting on @Priya", admin)
    s.flush()
    task = s.get(Task, t.id)
    text = build_member_digest(ravi, [task])
    assert "waiting on Priya" in text                 # Ravi sees who owes him
    lines = waiting_on_section([task])
    assert any("Buy cement (Ravi)" in ln for ln in lines)
    assert any(f"{t.id} unblock" in ln for ln in lines)


# ------- creator can close or cancel their task (v1.6.3) -------
def test_creator_marks_own_created_task_done(s, team):
    admin, ravi, priya = team
    # priya (a plain member) creates a task for ravi
    t = _task(s, team, creator=priya)
    r = handle_message(s, priya, f"{t.id} done", admin)
    assert r.react
    assert s.get(Task, t.id).status == "done"
    assert len(r.extra_sends) == 1                    # ravi is told
    cid, txt = r.extra_sends[0]
    assert cid == "971500000002@c.us" and "closed task" in txt


def test_creator_cancels_with_reason(s, team):
    admin, ravi, priya = team
    t = _task(s, team, creator=priya)
    r = handle_message(s, priya, f"{t.id} cancel client called it off", admin)
    assert r.react
    assert s.get(Task, t.id).status == "cancelled"
    assert "client called it off" in r.extra_sends[0][1]


def test_creator_cannot_set_other_statuses(s, team):
    admin, ravi, priya = team
    t = _task(s, team, creator=priya)
    r = handle_message(s, priya, f"{t.id} in progress", admin)
    assert r.text and "can't move" in r.text          # scoped: done/cancel only
    assert s.get(Task, t.id).status == "open"


def test_assignee_cannot_cancel(s, team):
    admin, ravi, _ = team
    t = _task(s, team)                                # creator = admin
    r = handle_message(s, ravi, f"{t.id} cancel", admin)
    assert r.text and "cancel" in r.text.lower()      # refused
    assert s.get(Task, t.id).status == "open"


def test_admin_can_cancel_any_task(s, team):
    admin, ravi, priya = team
    t = _task(s, team, creator=priya)
    r = handle_message(s, admin, f"{t.id} cancel", admin)
    assert r.react
    assert s.get(Task, t.id).status == "cancelled"


def test_uninvolved_member_still_refused(s, team):
    admin, ravi, priya = team
    t = _task(s, team)                                # admin -> ravi
    r = handle_message(s, priya, f"{t.id} done", admin)
    assert r.text and "admin" in r.text
    assert s.get(Task, t.id).status == "open"


# ------- v1.6.4: #group tag, /nudge, /adduser, /myadd, role help -------
import app.commands as C
from app.models import Broadcast, Group


@pytest.fixture()
def grp(s):
    g = Group(name="Site B Construction", chat_id="120363555@g.us")
    g2 = Group(name="Site Office", chat_id="120363556@g.us")
    s.add_all([g, g2]); s.commit()
    return g, g2


def test_add_with_group_tag_announces_on_y(s, team, grp, monkeypatch):
    admin, ravi, _ = team
    g, _g2 = grp
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: True)
    r = handle_message(s, admin, "/add Fix the pump @Ravi #site.b fri", admin)
    assert "announced in Site B Construction" in r.text
    r2 = handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.post_to_group_id == g.id
    assert "Announced in Site B Construction" in r2.text
    assert len(r2.extra_sends) == 1
    cid, txt = r2.extra_sends[0]
    assert cid == g.chat_id
    assert "New task for Ravi" in txt and f"{t.id} done" in txt


def test_add_group_tag_ambiguous_refused(s, team, grp):
    admin, _, _ = team
    r = handle_message(s, admin, "/add Fix pump @Ravi #site", admin)
    assert "matches several groups" in r.text
    assert s.query(Task).count() == 0


def test_add_group_tag_membership_enforced(s, team, grp, monkeypatch):
    admin, ravi, priya = team
    g, _ = grp
    # priya (member) is NOT in the group - verified absence
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: False)
    handle_message(s, priya, "/add Order rebar @Ravi #site.b", admin)
    r = handle_message(s, priya, "y", admin)
    assert "Not created" in r.text
    assert s.query(Task).count() == 0
    # unverifiable -> refused with hint
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: None)
    handle_message(s, priya, "/add Order rebar @Ravi #site.b", admin)
    r2 = handle_message(s, priya, "y", admin)
    assert "couldn't verify" in r2.text
    # admins bypass the check entirely
    monkeypatch.setattr(C, "_creator_in_group",
                        lambda m, cid: (_ for _ in ()).throw(AssertionError))
    handle_message(s, admin, "/add Order rebar @Ravi #site.b", admin)
    r3 = handle_message(s, admin, "y", admin)
    assert "Created task #" in r3.text


def test_nudge_create_flow(s, team, grp):
    admin, ravi, _ = team
    g, _g2 = grp
    r = handle_message(s, admin,
                       "/nudge 07:30 mon,wed,fri @Ravi #site.b "
                       "Good morning - plan for {day}?", admin)
    assert "Create nudge" in r.text and "07:30" in r.text
    assert "Ravi" in r.text and "Site B Construction" in r.text
    r2 = handle_message(s, admin, "y", admin)
    assert "created" in r2.text
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    assert b.send_time == "07:30" and b.active
    import json as _jj
    assert _jj.loads(b.days) == [0, 2, 4]
    assert ravi.id in _jj.loads(b.member_ids)
    assert g.id in _jj.loads(b.group_ids)
    assert b.tz   # pinned at creation


def test_nudge_manage_and_reschedule(s, team, grp):
    admin, _, _ = team
    handle_message(s, admin, "/nudge 07:30 daily #site.b Hello", admin)
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).first()
    # list
    r = handle_message(s, admin, "/nudges", admin)
    assert f"{b.id}." in r.text and "07:30" in r.text
    # pause / resume (no Y/N - reversible)
    handle_message(s, admin, f"/nudge off {b.id}", admin)
    assert not s.get(Broadcast, b.id).active
    handle_message(s, admin, f"/nudge on {b.id}", admin)
    assert s.get(Broadcast, b.id).active
    # reschedule keeps text
    r2 = handle_message(s, admin, f"/nudge {b.id} 08:15 tue,thu", admin)
    assert "updated" in r2.text
    assert s.get(Broadcast, b.id).send_time == "08:15"
    # delete needs Y
    handle_message(s, admin, f"/nudge delete {b.id}", admin)
    r3 = handle_message(s, admin, "y", admin)
    assert "Deleted" in r3.text
    assert s.query(Broadcast).count() == 0


def test_nudge_requires_recipients_and_message(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/nudge 07:30 mon Hello there", admin)
    assert "Who is it for" in r.text
    r2 = handle_message(s, admin, "/nudge 07:30 mon @Ravi", admin)
    assert "needs a message" in r2.text


def test_admin_commands_refused_for_members_and_groups(s, team):
    admin, ravi, _ = team
    r = handle_message(s, ravi, "/nudge 07:30 @Priya Hello", admin)
    assert "admin command" in r.text
    r2 = handle_message(s, admin, "/nudges", admin, is_group=True, group_id=1)
    assert r2.unmatched and not r2.text is None or r2.unmatched
    r3 = handle_message(s, ravi, "/adduser 971509999999 New Guy", admin)
    assert "admin command" in r3.text


def test_adduser_flow_and_reactivate(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/adduser +971 50 999 8877 Dillon M", admin)
    assert "Dillon M" in r.text and "971509998877" in r.text
    r2 = handle_message(s, admin, "y", admin)
    assert "Added Dillon M" in r2.text
    m = s.query(Member).filter(Member.phone == "971509998877").first()
    assert m and m.active and m.role == "member"
    # duplicate refused
    r3 = handle_message(s, admin, "/adduser 971509998877 Dillon M", admin)
    assert "already registered" in r3.text
    # deactivate then re-add -> reactivate
    m.active = False; s.flush()
    handle_message(s, admin, "/adduser 971509998877 Dillon M", admin)
    r4 = handle_message(s, admin, "y", admin)
    assert "Re-activated" in r4.text
    assert s.query(Member).filter(Member.phone == "971509998877").count() == 1


def test_myadd_lists_created_tasks(s, team):
    admin, ravi, priya = team
    handle_message(s, priya, "/add Fix pump @Ravi", admin)
    handle_message(s, priya, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    r = handle_message(s, priya, "/myadd", admin)
    assert f"#{t.id} Fix pump -> Ravi" in r.text
    assert f"{t.id} cancel" in r.text
    r2 = handle_message(s, ravi, "/myadd", admin)
    assert "No open tasks created by you" in r2.text


def test_help_is_role_aware(s, team):
    admin, ravi, _ = team
    r_member = handle_message(s, ravi, "/help", admin)
    r_admin = handle_message(s, admin, "/help", admin)
    assert "/nudge" not in r_member.text
    assert "/myadd" in r_member.text
    assert "/nudge" in r_admin.text and "/adduser" in r_admin.text
    # in a group even the admin gets only the member help
    r_grp = handle_message(s, admin, "/help", admin, is_group=True, group_id=1)
    assert "/adduser" not in r_grp.text


# ------- v1.6.5: spaced names (@Ravi.Shankar), nudge needs a time -------
@pytest.fixture()
def spaced(s, team):
    """A member whose name contains a space."""
    m = Member(name="Ravi Shankar", phone="971500000004", role="member")
    s.add(m); s.commit()
    return m


def test_help_lists_slash_commands_first_and_dot_names(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/help", admin)
    t = r.text
    # every /command appears before the status verbs
    assert t.index("/add ") < t.index("1 done")
    assert t.index("/help") < t.index("1 done")
    assert "@Ravi.Shankar" in t          # spaced-name example
    assert "1 block <reason>" in t       # status verbs still documented


def test_nudge_dotted_spaced_name(s, team, spaced):
    admin, _, _ = team
    r = handle_message(s, admin,
                       "/nudge 7:30 Tue @Ravi.Shankar What is the status",
                       admin)
    assert "Create nudge" in r.text and "Ravi Shankar" in r.text
    assert "07:30" in r.text
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    import json as _jj
    assert b.send_time == "07:30" and _jj.loads(b.days) == [1]
    assert _jj.loads(b.member_ids) == [spaced.id]
    assert b.message == "What is the status"


def test_nudge_unquoted_spaced_name_greedy(s, team, spaced):
    """The original bug: '@Ravi shankar 7:30 Tue ...' silently lost the time."""
    admin, _, _ = team
    r = handle_message(s, admin,
                       "/nudge @Ravi shankar 7:30 Tue What is the status",
                       admin)
    assert "Create nudge" in r.text and "Ravi Shankar" in r.text
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    import json as _jj
    assert b.send_time == "07:30" and _jj.loads(b.days) == [1]
    assert b.message == "What is the status"


def test_nudge_greedy_does_not_eat_the_message(s, team, spaced):
    admin, _, _ = team
    handle_message(s, admin, "/nudge 08:00 @Ravi.Shankar Ravi send the report",
                   admin)
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    assert b.message == "Ravi send the report"


def test_nudge_without_time_refused(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/nudge @Ravi What is the status", admin)
    assert "When should it go out" in r.text
    assert s.query(Broadcast).count() == 0      # no silent manual-only nudge


def test_nudge_unknown_name_hints_at_dot(s, team):
    admin, _, _ = team
    r = handle_message(s, admin, "/nudge 07:30 @Nobody Hello", admin)
    assert "don't recognise" in r.text and "@Ravi.Shankar" in r.text


def test_add_accepts_spaced_names(s, team, spaced):
    admin, _, _ = team
    r = handle_message(s, admin, "/add Fix the pump @Ravi.Shankar fri", admin)
    assert "Ravi Shankar" in r.text
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == "Fix the pump" and t.assignee_id == spaced.id
    assert t.due_date is not None
    # unquoted form too - and the date word must survive
    r2 = handle_message(s, admin, "/add Order rebar @Ravi shankar tomorrow",
                        admin)
    assert "Ravi Shankar" in r2.text
    handle_message(s, admin, "y", admin)
    t2 = s.query(Task).order_by(Task.id.desc()).first()
    assert t2.title == "Order rebar" and t2.assignee_id == spaced.id
    assert t2.due_date == date.today() + timedelta(days=1)


def test_nudge_quoted_spaced_name(s, team, spaced):
    admin, _, _ = team
    r = handle_message(s, admin,
                       '/nudge 7:30 Tue @"Ravi Shankar" What is the status',
                       admin)
    assert "Create nudge" in r.text and "Ravi Shankar" in r.text
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    import json as _jj
    assert b.send_time == "07:30" and _jj.loads(b.days) == [1]
    assert _jj.loads(b.member_ids) == [spaced.id]
    assert b.message == "What is the status"


def test_curly_quotes_from_phone_keyboards(s, team, spaced, grp):
    """iOS/Android autocorrect curls quotes - both forms must resolve."""
    admin, _, _ = team
    g, _g2 = grp
    r = handle_message(s, admin,
                       "/nudge 07:30 @“Ravi Shankar” "
                       "#“Site B Construction” Status?", admin)
    assert "Create nudge" in r.text
    assert "Ravi Shankar" in r.text and "Site B Construction" in r.text
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    import json as _jj
    assert _jj.loads(b.member_ids) == [spaced.id]
    assert _jj.loads(b.group_ids) == [g.id]
    assert b.message == "Status?"


def test_add_quoted_name_and_group(s, team, spaced, grp, monkeypatch):
    admin, _, _ = team
    g, _g2 = grp
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: True)
    r = handle_message(s, admin,
                       '/add Fix the pump @"Ravi Shankar" #"Site B" fri', admin)
    assert "Ravi Shankar" in r.text and "Site B Construction" in r.text
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == "Fix the pump" and t.assignee_id == spaced.id
    assert t.post_to_group_id == g.id


def test_quotes_elsewhere_in_the_text_are_untouched(s, team):
    admin, ravi, _ = team
    handle_message(s, admin, '/add Fix the "big" pump @Ravi', admin)
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == 'Fix the "big" pump' and t.assignee_id == ravi.id


def test_block_waiting_on_spaced_name(s, team, spaced):
    """The block hand-off must resolve dotted/quoted names too - the old
    @(\\w+) regex silently truncated @Ravi.Shankar to @Ravi."""
    admin, ravi, _ = team
    t = _task(s, team)
    r = handle_message(s, ravi, f'{t.id} block waiting on @"Ravi Shankar"',
                       admin)
    assert s.get(Task, t.id).waiting_on_id == spaced.id
    assert any(spaced.phone in cid for cid, _ in r.extra_sends)
    # and the dotted form
    t2 = _task(s, team, title="Second")
    handle_message(s, ravi, f"{t2.id} block waiting on @Ravi.Shankar", admin)
    assert s.get(Task, t2.id).waiting_on_id == spaced.id


def test_reversed_curly_quote_from_a_phone(s, team, spaced, grp, monkeypatch):
    """A pasted/space-preceded quote curls the WRONG way: the opener arrives
    as the closing glyph. Insisting on a matched pair failed silently and
    dumped the raw tag into the task title."""
    admin, _, _ = team
    g, _g2 = grp
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: True)
    r = handle_message(
        s, admin,
        '/add Thennangur status update @”Ravi Shankar” #”Site B” !high', admin)
    assert "Ravi Shankar" in r.text and "Site B Construction" in r.text
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == "Thennangur status update"     # no stray #"..." in it
    assert t.assignee_id == spaced.id and t.post_to_group_id == g.id
    assert t.priority == "high"


def test_group_tag_unquoted_spaces(s, team, grp, monkeypatch):
    """#De Leadership team - no dot, no quotes - still resolves greedily."""
    admin, ravi, _ = team
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: True)
    g3 = Group(name="De Leadership team", chat_id="120363999@g.us")
    s.add(g3); s.commit()
    r = handle_message(s, admin,
                       "/add Project status update @Ravi #De Leadership team",
                       admin)
    assert "announced in De Leadership team" in r.text
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.title == "Project status update" and t.post_to_group_id == g3.id


def test_group_greedy_does_not_eat_the_nudge_message(s, team, grp):
    admin, _, _ = team
    g, _g2 = grp
    handle_message(s, admin, "/nudge 07:30 #site.b Site inspection at nine",
                   admin)
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    assert b.message == "Site inspection at nine"
    import json as _jj
    assert _jj.loads(b.group_ids) == [g.id]


def test_ambiguous_group_still_refused_after_greedy(s, team, grp):
    admin, _, _ = team
    r = handle_message(s, admin, "/add Fix pump @Ravi #site", admin)
    assert "matches several groups" in r.text
    assert s.query(Task).count() == 0


def test_time_formats_people_actually_type(s, team):
    from app.commands import _parse_time_token as pt
    assert pt("07:30") == pt("7:30") == pt("7.30") == pt("730") == pt("0730") \
        == pt("7:30am") == pt("730am") == "07:30"
    assert pt("7am") == "07:00" and pt("7PM") == "19:00"
    assert pt("730pm") == pt("19:30") == pt("7:30pm") == "19:30"
    assert pt("12am") == "00:00" and pt("12pm") == "12:00"
    # not times
    assert pt("3") is None          # a bare number is a nudge id
    assert pt("25:00") is None and pt("790") is None and pt("13pm") is None
    assert pt("fri") is None and pt("hello") is None


@pytest.mark.parametrize("typed,expect", [
    ("07:30", "07:30"), ("7:30", "07:30"), ("730", "07:30"), ("0730", "07:30"),
    ("7.30", "07:30"), ("7:30am", "07:30"), ("730am", "07:30"),
    ("7am", "07:00"), ("7 am", "07:00"), ("7:30 PM", "19:30"),
    ("19:30", "19:30"), ("730pm", "19:30"),
])
def test_nudge_accepts_every_time_spelling(s, team, typed, expect):
    admin, _, _ = team
    r = handle_message(s, admin, f"/nudge {typed} tue @Ravi Status?", admin)
    assert "Create nudge" in r.text, r.text
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).order_by(Broadcast.id.desc()).first()
    assert b.send_time == expect
    assert b.message == "Status?"


def test_nudge_id_still_beats_a_time_lookalike(s, team):
    """/nudge 3 08:15 must reschedule nudge 3, not create a 3 o'clock nudge."""
    admin, _, _ = team
    handle_message(s, admin, "/nudge 07:30 daily @Ravi Hello", admin)
    handle_message(s, admin, "y", admin)
    b = s.query(Broadcast).first()
    r = handle_message(s, admin, f"/nudge {b.id} 0815 thu", admin)
    assert "updated" in r.text
    assert s.get(Broadcast, b.id).send_time == "08:15"
    assert s.query(Broadcast).count() == 1
    # a bare id that doesn't exist is still an id, not a time
    r2 = handle_message(s, admin, "/nudge 99 08:15", admin)
    assert "no nudge 99" in r2.text


def test_help_shows_both_spaced_name_forms(s, team):
    admin, _, _ = team
    t = handle_message(s, admin, "/help", admin).text
    assert "@Ravi.Shankar" in t and '@"Ravi Shankar"' in t
    assert t.index("/add ") < t.index("1 done")


# ------- v1.6.5: renaming a member -------
def test_rename_changes_what_the_team_sees(s, team, grp, monkeypatch):
    """The stored name - not the phone's contact list - is what appears in a
    group announcement. Renaming must change it everywhere at once."""
    from app.engine import rename_member
    admin, ravi, _ = team
    g, _g2 = grp
    monkeypatch.setattr(C, "_creator_in_group", lambda m, cid: True)
    ok, msg = rename_member(s, ravi, "Ravi Shankar")
    assert ok and "Renamed Ravi to Ravi Shankar" in msg
    s.commit()
    handle_message(s, admin, "/add Fix the pump @Ravi.Shankar #site.b", admin)
    r = handle_message(s, admin, "y", admin)
    _cid, txt = r.extra_sends[0]
    assert "New task for Ravi Shankar" in txt      # the group sees the new name


def test_rename_refuses_a_duplicate(s, team):
    from app.engine import rename_member
    admin, ravi, priya = team
    ok, msg = rename_member(s, ravi, "priya")      # case-insensitive
    assert not ok
    assert "already used by" in msg and priya.phone in msg
    assert s.get(Member, ravi.id).name == "Ravi"   # unchanged


def test_rename_refuses_a_duplicate_of_an_inactive_member(s, team):
    """Otherwise reactivating that person later would create the collision."""
    from app.engine import rename_member
    admin, ravi, priya = team
    priya.active = False
    s.flush()
    ok, msg = rename_member(s, ravi, "Priya")
    assert not ok and "deactivated" in msg


def test_rename_warns_about_a_prefix_clash_but_allows_it(s, team):
    from app.engine import rename_member
    admin, ravi, _ = team
    extra = Member(name="Ravi Shankar", phone="971500000009", role="member")
    s.add(extra); s.flush()
    ok, msg = rename_member(s, ravi, "Ravi Kumar")
    assert ok
    assert "ambiguous" in msg and "@Ravi.Kumar" in msg
    assert s.get(Member, ravi.id).name == "Ravi Kumar"


def test_rename_rejects_empty_and_trims(s, team):
    from app.engine import rename_member
    admin, ravi, _ = team
    ok, msg = rename_member(s, ravi, "   ")
    assert not ok and "empty" in msg
    ok, _ = rename_member(s, ravi, "  Ravi   Shankar  ")
    assert ok and s.get(Member, ravi.id).name == "Ravi Shankar"


def test_adduser_reactivation_keeps_the_curated_name(s, team):
    """Re-adding a deactivated member must not silently overwrite the name
    that was set on the dashboard."""
    admin, _, _ = team
    m = Member(name="Ravi Shankar", phone="971509998877", role="member",
               active=False)
    s.add(m); s.commit()
    handle_message(s, admin, "/adduser 971509998877 Ravi", admin)
    r = handle_message(s, admin, "y", admin)
    assert "Re-activated" in r.text and "Name kept" in r.text
    assert s.get(Member, m.id).name == "Ravi Shankar"
    assert s.get(Member, m.id).active


def test_exact_short_name_still_wins_over_longer(s, team, spaced):
    """'Ravi' and 'Ravi Shankar' both exist: @Ravi must resolve to Ravi."""
    admin, ravi, _ = team
    handle_message(s, admin, "/add Fix pump @Ravi", admin)
    handle_message(s, admin, "y", admin)
    t = s.query(Task).order_by(Task.id.desc()).first()
    assert t.assignee_id == ravi.id


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

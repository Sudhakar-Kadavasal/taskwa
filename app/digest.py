"""Morning digest builder + sender (FR-11/12/13, D7/D8)."""
import logging
from datetime import date, datetime

from .db import get_setting, session_scope, set_setting
from .engine import (open_tasks_for, save_digest_refs,
                     save_group_digest_refs, sort_tasks)
from .models import Group, Member, Task
from .waha import chat_id_for_phone, paced_send

log = logging.getLogger("digest")


def _line(t: Task, n: int) -> str:
    pr = {"high": "[HIGH] ", "low": "[low] "}.get(t.priority, "")
    due = ""
    if t.due_date:
        if t.due_date < date.today():
            due = f"  - OVERDUE ({t.due_date:%d %b})"
        elif t.due_date == date.today():
            due = "  - due today"
        else:
            due = f"  - due {t.due_date:%a %d %b}"
    return f"  {n}. {pr}{t.title}{due}"


def ordered_for_digest(tasks: list[Task]) -> list[Task]:
    """Display order: active tasks first, blocked last - numbering follows."""
    return ([t for t in tasks if t.status != "blocked"]
            + [t for t in tasks if t.status == "blocked"])


def build_member_digest(member: Member, ordered: list[Task]) -> str:
    n = len(ordered)
    lines = [f"Good morning, {member.name} - "
             f"{n} open task{'s' if n != 1 else ''} today:", ""]
    for i, t in enumerate(ordered, 1):
        if t.status == "blocked":
            lines.append(f"  [!] {i}. {t.title} - BLOCKED "
                         f"{t.blocked_days}d: {t.blocker_reason}")
        else:
            lines.append(_line(t, i))
    lines += ["", "Reply:  1 done  |  1 in progress  |  1 block <reason>"]
    return "\n".join(lines)


def build_group_digest(group: Group, ordered: list[Task]) -> str:
    lines = [f"Team tasks - {date.today():%a %d %b}:", ""]
    for i, t in enumerate(ordered, 1):
        who = t.assignee.name
        if t.status == "blocked":
            lines.append(f"  [!] {i}. {t.title} ({who}) - BLOCKED "
                         f"{t.blocked_days}d: {t.blocker_reason}")
        else:
            lines.append(_line(t, i) + f"  ({who})")
    lines += ["", "Reply:  1 done  |  1 in progress  |  1 block <reason>"]
    return "\n".join(lines)


def send_daily_digests():
    """Called by the scheduler at each configured send time."""
    messages: list[tuple[str, str]] = []
    with session_scope() as s:
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        active_group_ids = {g.id for g in groups}
        members = s.query(Member).filter(Member.active.is_(True)).all()
        for m in members:
            tasks = open_tasks_for(s, m)
            # tasks announced in a group are not repeated in the personal DM
            tasks = [t for t in tasks
                     if t.post_to_group_id not in active_group_ids]
            if tasks:
                ordered = ordered_for_digest(tasks)
                save_digest_refs(s, m, ordered)
                messages.append((chat_id_for_phone(m.phone),
                                 build_member_digest(m, ordered)))
        for g in groups:
            gtasks = (s.query(Task)
                       .filter(Task.post_to_group_id == g.id,
                               Task.status.in_(("open", "in_progress", "blocked")))
                       .all())
            if gtasks:
                ordered = ordered_for_digest(sort_tasks(gtasks))
                save_group_digest_refs(s, g.id, ordered)
                messages.append((g.chat_id, build_group_digest(g, ordered)))
    log.info("digest run: %d messages", len(messages))
    paced_send(messages)
    with session_scope() as s:
        set_setting(s, "last_send", datetime.utcnow().isoformat(timespec="seconds"))


def alert_admins(text: str):
    """Send an immediate alert to every active admin (used for blockers)."""
    with session_scope() as s:
        admins = (s.query(Member)
                   .filter(Member.role == "admin", Member.active.is_(True)).all())
        targets = [(chat_id_for_phone(a.phone), text) for a in admins]
    paced_send(targets)

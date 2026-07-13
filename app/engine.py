"""Task engine: creation, status transitions, permissions, audit trail."""
from datetime import datetime, date

from .models import (DigestRef, GroupDigestRef, Task, Member,
                     StatusEvent, STATUSES, PRIORITIES)


class PermissionError_(Exception):
    pass


class InvalidTransition(Exception):
    pass


ALLOWED = {
    "open":        {"in_progress", "blocked", "done", "cancelled"},
    "in_progress": {"open", "blocked", "done", "cancelled"},
    "blocked":     {"open", "in_progress", "done", "cancelled"},
    "done":        {"open"},            # reopen
    "cancelled":   set(),
}


def create_task(s, *, title, assignee: Member, creator: Member | None = None,
                description: str = "", due_date: date | None = None,
                priority: str = "medium", post_to_group_id: int | None = None,
                channel: str = "dashboard", raw_text: str = "") -> Task:
    if priority not in PRIORITIES:
        priority = "medium"
    t = Task(title=title.strip()[:200], description=description,
             assignee_id=assignee.id,
             creator_id=creator.id if creator else None,
             due_date=due_date, priority=priority,
             post_to_group_id=post_to_group_id, status="open")
    s.add(t)
    s.flush()  # assign serial
    s.add(StatusEvent(task_id=t.id, actor_id=creator.id if creator else None,
                      from_status="", to_status="open", channel=channel,
                      raw_text=raw_text, note="created"))
    return t


def can_change_status(task: Task, actor: Member) -> bool:
    """D6: the assignee or an admin may change status; the person a blocked
    task is waiting on may release the block; the task's creator may close
    or cancel it. (Target-status scoping is enforced in change_status.)"""
    if actor.role == "admin" or actor.id == task.assignee_id:
        return True
    if task.status == "blocked" and actor.id == task.waiting_on_id:
        return True
    return actor.id == task.creator_id


def change_status(s, task: Task, actor: Member | None, new_status: str,
                  *, note: str = "", channel: str = "dashboard",
                  raw_text: str = "") -> Task:
    if new_status not in STATUSES:
        raise InvalidTransition(f"Unknown status '{new_status}'.")
    if new_status not in ALLOWED[task.status]:
        raise InvalidTransition(
            f"Task #{task.id} is '{task.status.replace('_', ' ')}' - "
            f"it cannot move to '{new_status.replace('_', ' ')}'.")
    if actor is not None and not can_change_status(task, actor):
        raise PermissionError_(
            f"Only {task.assignee.name} (the assignee) or an admin can update task #{task.id}.")
    if (actor is not None and actor.role != "admin"
            and actor.id != task.assignee_id):
        # scoped powers: waiting-on person may only release the block;
        # the creator may only close or cancel
        allowed_targets = set()
        if task.status == "blocked" and actor.id == task.waiting_on_id:
            allowed_targets |= {"in_progress", "open"}
        if actor.id == task.creator_id:
            allowed_targets |= {"done", "cancelled"}
        if new_status not in allowed_targets:
            raise PermissionError_(
                f"You can't move task #{task.id} to "
                f"'{new_status.replace('_', ' ')}' - only "
                f"{task.assignee.name} (the assignee) or an admin can.")
    if (new_status == "cancelled" and actor is not None
            and actor.role != "admin" and actor.id != task.creator_id):
        # cancelling is reserved: an assignee's way out is declining, not
        # killing the task later
        raise PermissionError_(
            f"Only the creator of task #{task.id} or an admin can cancel it.")
    old = task.status
    task.status = new_status
    if new_status == "blocked":
        task.blocker_reason = note
    if old == "blocked" and new_status != "blocked":
        task.blocker_reason = ""
        task.waiting_on_id = None
    task.completed_at = datetime.utcnow() if new_status == "done" else None
    s.add(StatusEvent(task_id=task.id, actor_id=actor.id if actor else None,
                      from_status=old, to_status=new_status, note=note,
                      channel=channel, raw_text=raw_text))
    return task


def open_tasks_for(s, member: Member) -> list[Task]:
    rows = (s.query(Task)
             .filter(Task.assignee_id == member.id,
                     Task.status.in_(("open", "in_progress", "blocked")))
             .all())
    return sort_tasks(rows)


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def sort_tasks(tasks: list[Task]) -> list[Task]:
    """High priority first, then earliest due date, then serial."""
    return sorted(tasks, key=lambda t: (
        PRIORITY_ORDER.get(t.priority, 1),
        t.due_date or date.max,
        t.id))


def member_by_phone(s, phone: str) -> Member | None:
    phone = "".join(ch for ch in phone if ch.isdigit())
    return (s.query(Member)
             .filter(Member.phone == phone, Member.active.is_(True))
             .first())


def save_digest_refs(s, member: Member, tasks: list[Task]):
    """Rebuild the member's number->task map (1-based, in display order)."""
    s.query(DigestRef).filter(DigestRef.member_id == member.id).delete()
    for i, t in enumerate(tasks, 1):
        s.add(DigestRef(member_id=member.id, pos=i, task_id=t.id))


def save_group_digest_refs(s, group_id: int, tasks: list[Task]):
    """Rebuild a group's number->task map (1-based, in display order)."""
    s.query(GroupDigestRef).filter(GroupDigestRef.group_id == group_id).delete()
    for i, t in enumerate(tasks, 1):
        s.add(GroupDigestRef(group_id=group_id, pos=i, task_id=t.id))


def resolve_ref(s, member: Member, num: int,
                group_id: int | None = None) -> Task | None:
    """A number in a reply means, in order: the number from THAT group's
    digest (when replying in a group), the member's own digest number,
    the global task serial as fallback."""
    if group_id is not None:
        gref = (s.query(GroupDigestRef)
                 .filter(GroupDigestRef.group_id == group_id,
                         GroupDigestRef.pos == num).first())
        if gref:
            t = s.get(Task, gref.task_id)
            if t:
                return t
    ref = (s.query(DigestRef)
            .filter(DigestRef.member_id == member.id, DigestRef.pos == num)
            .first())
    if ref:
        t = s.get(Task, ref.task_id)
        if t:
            return t
    return s.get(Task, num)


def rename_member(s, member: Member, new_name: str) -> tuple[bool, str]:
    """Rename a member. Returns (ok, message).

    The name is an ADDRESSING KEY, not a label: '@Ravi' is resolved against it.
    So a duplicate is refused outright - two members with the same name would
    make '@Ravi' resolve to an arbitrary one of them, and a task would land on
    the wrong person with no error anywhere. Checked against every member,
    active or not, so reactivating someone later can't create the collision.

    A PREFIX clash ('Ravi' vs 'Ravi Shankar') is allowed but reported: it only
    costs the '@Ravi' shorthand, which then refuses to guess and asks for the
    full (dotted or quoted) name. Annoying, never wrong."""
    name = " ".join(str(new_name or "").split())[:80]
    if not name:
        return False, "A name can't be empty."
    if name.lower() == member.name.lower() and name == member.name:
        return True, ""
    others = s.query(Member).filter(Member.id != member.id).all()
    clash = next((m for m in others if m.name.lower() == name.lower()), None)
    if clash:
        state = "" if clash.active else " (deactivated)"
        return False, (f"'{name}' is already used by {clash.phone}{state}. "
                       "Two members cannot share a name - '@" + name.split()[0]
                       + "' would become ambiguous and tasks could go to the "
                         "wrong person. Pick a different name.")
    old, member.name = member.name, name
    # Would the short form '@Ravi' now match more than one person? That is the
    # clash that costs the shorthand - not whether one full name prefixes
    # another. Allowed: the bot refuses to guess, so nothing goes astray.
    first = name.split()[0].lower()
    also = [m.name for m in others
            if m.active and m.name.lower().startswith(first)]
    if also:
        return True, (f"Renamed {old} to {name}. Note: {', '.join(also)} also "
                      f"starts with '{name.split()[0]}', so the short form "
                      f"'@{name.split()[0]}' is now ambiguous - the bot will "
                      f"ask for the full name (@{name.replace(' ', '.')}) "
                      "rather than guess.")
    return True, f"Renamed {old} to {name}."


def bulk_add_members(s, rows) -> tuple[int, int]:
    """Add many members at once. rows: [{'name','phone','role'}].
    Skips numbers already registered (any status), blanks, and duplicates
    within the batch. Returns (added, skipped)."""
    existing = {m.phone for m in s.query(Member).all()}
    added = skipped = 0
    for r in rows:
        phone = "".join(ch for ch in str(r.get("phone", "")) if ch.isdigit())
        name = str(r.get("name", "")).strip() or phone
        role = r.get("role") if r.get("role") in ("admin", "member") else "member"
        if not phone or phone in existing:
            skipped += 1
            continue
        s.add(Member(name=name[:80], phone=phone, role=role))
        existing.add(phone)
        added += 1
    return added, skipped

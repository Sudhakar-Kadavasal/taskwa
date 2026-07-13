"""Keyword command parser + handler.

Reply protocol — the numbers are the small 1, 2, 3 from the member's own
digest (global task serials also work as fallback):

  1 done                       close task 1
  1 in progress  (or: 1 wip)   mark started
  1 block <reason>             blocked + reason (also: blocker / blocked)
  1 reopen                     undo a mistaken done
  done / block <reason>        bare form - works when the member has exactly
                               one open task, or as a quoted (swipe) reply to
                               a bot message that names one task
  /add <title> @Name [!high|!low] [today|tomorrow|fri|25/07]
  /mytasks   /list   /help     y / n confirms or cancels a pending /add
"""
import json
import re
from datetime import date, datetime, timedelta

from .engine import (InvalidTransition, PermissionError_, change_status,
                     create_task, open_tasks_for, resolve_ref,
                     save_digest_refs, sort_tasks)
from .models import Member, PendingConfirm, StatusEvent, Task

HELP_TEXT = (
    "*Task bot - commands*\n"
    "1 done - close task 1 (your digest number)\n"
    "1 in progress - mark started\n"
    "1 block <reason> - report a blocker (alerts admin)\n"
    "1 block waiting on @Name - hand the block to that person\n"
    "1 unblock - release a block that waits on you\n"
    "1 reopen - undo a mistaken 'done'\n"
    "1 cancel - cancel a task you created (creator/admin only)\n"
    "Just 'done' works if you have a single open task,\n"
    "or swipe-reply on a task message and type 'done'.\n"
    "/add <title> @Name [!high|!low] [today|fri|25/07]\n"
    "/mytasks - your open tasks\n"
    "/list - open tasks you can see\n"
    "/help - this message"
)

VERB = r"(done|reopen|in\s*-?\s*progress|inprogress|wip|block(?:er|ed)?|unblock|cancel(?:led)?)"
RE_STATUS = re.compile(rf"^\s*#?(\d+)[.):]?\s+{VERB}\b\s*(.*)$",
                       re.IGNORECASE | re.DOTALL)
RE_BARE = re.compile(rf"^\s*{VERB}\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
RE_ADD = re.compile(r"^\s*/add\s+(.+)$", re.IGNORECASE | re.DOTALL)
RE_YES = re.compile(r"^\s*(y|yes)\s*$", re.IGNORECASE)
RE_NO = re.compile(r"^\s*(n|no)\s*$", re.IGNORECASE)

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}


def parse_date_word(word: str, today: date | None = None) -> date | None:
    today = today or date.today()
    w = word.lower().strip()
    if w == "today":
        return today
    if w == "tomorrow":
        return today + timedelta(days=1)
    if w in WEEKDAYS:
        delta = (WEEKDAYS[w] - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", w)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else today.year
        if yr < 100:
            yr += 2000
        try:
            result = date(yr, mo, d)
        except ValueError:
            return None
        if result < today and not m.group(3):
            result = date(yr + 1, mo, d)
        return result
    return None


class Reply:
    """What the webhook should do after handling a message.

    unmatched=True marks ordinary conversation - the webhook suppresses these
    replies in groups and in personal-number mode.
    extra_sends: additional (chat_id, text) messages to other recipients
    (e.g. notifying an assignee) - each still vetted by the send allowlist."""
    def __init__(self, text: str | None = None, react: bool = False,
                 alert_admin: str | None = None, unmatched: bool = False,
                 extra_sends: list | None = None):
        self.text = text
        self.react = react
        self.alert_admin = alert_admin
        self.unmatched = unmatched
        self.extra_sends = extra_sends or []


def _serial_footer(serial: int) -> str:
    """Reply instructions using the task's global serial (always resolvable)."""
    return (f"Reply:  {serial} done  |  {serial} in progress  |  "
            f"{serial} block <reason>")


def notify_assignee(s, t: Task, creator: Member | None):
    """Immediate DM for a task created for someone else. Returns
    (chat_id, text) to send, or None (self-assigned, group-posted, or
    inactive assignee). Adds a Y/N acceptance dialogue unless the assignee
    already has another confirmation in flight."""
    from .waha import chat_id_for_phone
    assignee = t.assignee
    if assignee is None or not assignee.active or t.post_to_group_id:
        return None
    if creator is not None and assignee.id == creator.id:
        return None
    due = f", due {t.due_date:%a %d %b}" if t.due_date else ""
    pr = " [HIGH]" if t.priority == "high" else ""
    who = creator.name if creator else "the dashboard"
    lines = [f"New task from {who}: {t.title}{due}{pr}"]
    has_active = (s.query(PendingConfirm)
                   .filter(PendingConfirm.member_id == assignee.id,
                           PendingConfirm.expires_at > datetime.utcnow())
                   .count() > 0)
    if not has_active:
        # clear any EXPIRED leftover first - member_id is UNIQUE, and a
        # stale row otherwise breaks the insert (v1.6.3 hotfix)
        s.query(PendingConfirm).filter(
            PendingConfirm.member_id == assignee.id).delete()
        s.add(PendingConfirm(
            member_id=assignee.id,
            draft_json=json.dumps({"kind": "accept", "task_id": t.id}),
            expires_at=datetime.utcnow() + timedelta(minutes=30)))
        s.flush()
        lines += ["", "Reply Y to accept, N to decline "
                      "(no reply in 30 min counts as accepted)."]
    lines += ["", _serial_footer(t.id)]
    return chat_id_for_phone(assignee.phone), "\n".join(lines)


def _task_channel(s, t: Task) -> str:
    """Where updates about this task are announced: its group when
    group-posted, otherwise the assignee's DM - one channel, never both."""
    from .waha import chat_id_for_phone
    if t.post_to_group_id and t.group and t.group.active:
        return t.group.chat_id
    return chat_id_for_phone(t.assignee.phone)


def _waiting_notice(s, t: Task, sender: Member,
                    waited: Member) -> tuple[str, str]:
    """The one message telling someone a task is now waiting on them -
    posted in the task's group if it has one, else DM'd."""
    from .waha import chat_id_for_phone
    txt = (f"{waited.name} - {sender.name} is waiting on you for task "
           f"#{t.id}: {t.title}\nReason: {t.blocker_reason}\n\n"
           f"Reply:  {t.id} unblock  - when your part is done, or if "
           "there's no block on your side.")
    if t.post_to_group_id and t.group and t.group.active:
        return t.group.chat_id, txt
    return chat_id_for_phone(waited.phone), txt


def _handle_acceptance(s, sender: Member, draft: dict, accepted: bool,
                       raw: str) -> Reply:
    """Y/N answer to a 'New task from …' acceptance dialogue. Declining
    returns the task to the person who created it (or an admin if the
    creator is gone) - work never dies silently and never stays with
    someone who refused it."""
    from .waha import chat_id_for_phone
    t = s.get(Task, draft.get("task_id"))
    if t is None or t.status in ("done", "cancelled"):
        return Reply(text="That task no longer exists or is already closed.")
    if accepted:
        s.add(StatusEvent(task_id=t.id, actor_id=sender.id,
                          from_status=t.status, to_status=t.status,
                          channel="whatsapp", raw_text=raw,
                          note="accepted by assignee"))
        return Reply(text=f"Accepted - task #{t.id} is on your list.\n\n"
                          + _serial_footer(t.id), react=True)
    # declined -> back to the initiator
    owner = t.creator if (t.creator and t.creator.active) else None
    if owner is None or owner.id == sender.id:
        owner = (s.query(Member)
                  .filter(Member.role == "admin", Member.active.is_(True),
                          Member.id != sender.id).first())
    if owner is None:   # nobody to return it to - keep it, tell the admins
        s.add(StatusEvent(task_id=t.id, actor_id=sender.id,
                          from_status=t.status, to_status=t.status,
                          channel="whatsapp", raw_text=raw,
                          note="DECLINED by assignee (no one to return to)"))
        return Reply(text=f"Noted - you declined task #{t.id}, but there is "
                          "no one to return it to, so it stays on your list.",
                     alert_admin=f"{sender.name} DECLINED task #{t.id}: "
                                 f"{t.title} - no active creator to return "
                                 "it to.")
    t.assignee_id = owner.id
    s.add(StatusEvent(task_id=t.id, actor_id=sender.id,
                      from_status=t.status, to_status=t.status,
                      channel="whatsapp", raw_text=raw,
                      note=f"declined by {sender.name} - returned to "
                           f"{owner.name}"))
    txt = (f"{sender.name} declined task #{t.id}: {t.title} - it's back on "
           f"your list.\n\n" + _serial_footer(t.id))
    return Reply(text=f"Noted - task #{t.id} goes back to {owner.name}.",
                 extra_sends=[(chat_id_for_phone(owner.phone), txt)])


def _created_reply(s, t: Task, sender: Member, assignee: Member) -> Reply:
    """Receipt for the creator - always says what happens next, and how to
    reply (fixes the dead-end 'Created task #N' message)."""
    base = (f"Created task #{t.id}: {t.title} -> {assignee.name}"
            + (f", due {t.due_date:%a %d %b}" if t.due_date else ""))
    if assignee.id == sender.id:
        return Reply(text=base + "\n\n" + _serial_footer(t.id))
    if t.post_to_group_id:
        return Reply(text=base + "\nIt will appear in that group's daily list.")
    extra = notify_assignee(s, t, sender)
    if extra:
        return Reply(text=base + f"\n{assignee.name} has been asked to "
                                 "accept it.\n\n"
                                 f"You created it, so you can also:  "
                                 f"{t.id} done  |  {t.id} cancel",
                     extra_sends=[extra])
    return Reply(text=base)


def _find_member_by_ref(s, ref: str) -> Member | None:
    """Resolve an @mention: a typed name (@Ravi) or a native WhatsApp mention,
    which arrives as @<digits> (phone number or anonymous LID)."""
    if ref.isdigit():
        from .engine import member_by_phone
        m = member_by_phone(s, ref)
        if m:
            return m
        from .waha import lid_to_phone
        phone = lid_to_phone(ref)
        return member_by_phone(s, phone) if phone else None
    return _find_member_by_name(s, ref)


def _find_member_by_name(s, name: str) -> Member | None:
    name = name.lower()
    members = s.query(Member).filter(Member.active.is_(True)).all()
    exact = [m for m in members if m.name.lower() == name]
    if exact:
        return exact[0]
    prefix = [m for m in members if m.name.lower().startswith(name)]
    return prefix[0] if len(prefix) == 1 else None


def _task_body(t: Task) -> str:
    """Task line without any leading number."""
    pr = {"high": "[HIGH] ", "low": "[low] "}.get(t.priority, "")
    due = f" - due {t.due_date.strftime('%a %d %b')}" if t.due_date else ""
    if t.status == "blocked":
        return (f"[!] {pr}{t.title} - BLOCKED {t.blocked_days}d: "
                f"{t.blocker_reason}")
    mark = "(in progress) " if t.status == "in_progress" else ""
    return f"{pr}{mark}{t.title}{due}"


def _apply_verb(s, sender: Member, task: Task, verb: str, rest: str,
                raw: str) -> Reply:
    verb_norm = re.sub(r"[\s-]", "", verb.lower())
    try:
        if verb_norm == "done":
            change_status(s, task, sender, "done",
                          channel="whatsapp", raw_text=raw)
            extra = []
            if sender.id != task.assignee_id:    # creator/admin closed it
                extra.append((_task_channel(s, task),
                              f"{sender.name} closed task #{task.id}: "
                              f"{task.title} - nothing more needed from you, "
                              f"{task.assignee.name}."))
            return Reply(react=True, extra_sends=extra)
        if verb_norm in ("cancel", "cancelled"):
            change_status(s, task, sender, "cancelled",
                          note=rest.strip(), channel="whatsapp", raw_text=raw)
            extra = []
            if sender.id != task.assignee_id:
                why = f" ({rest.strip()})" if rest.strip() else ""
                extra.append((_task_channel(s, task),
                              f"{sender.name} cancelled task #{task.id}: "
                              f"{task.title}{why} - it's off your list, "
                              f"{task.assignee.name}."))
            return Reply(react=True, extra_sends=extra)
        if verb_norm in ("inprogress", "wip"):
            change_status(s, task, sender, "in_progress",
                          channel="whatsapp", raw_text=raw)
            return Reply(react=True)
        if verb_norm == "reopen":
            change_status(s, task, sender, "open", note="reopened",
                          channel="whatsapp", raw_text=raw)
            return Reply(react=True)
        if verb_norm in ("block", "blocker", "blocked"):
            if not rest.strip():
                return Reply(text="Please include the reason: "
                                  "block <what you're stuck on>")
            reason = rest.strip()
            change_status(s, task, sender, "blocked", note=reason,
                          channel="whatsapp", raw_text=raw)
            alert = (f"[!] Blocker on task #{task.id} '{task.title}'\n"
                     f"By: {sender.name}\nReason: {reason}")
            # "block waiting on @Priya" -> hand the block to that person
            extra = []
            mref = re.search(r"@(\w+)", reason)
            waited = _find_member_by_ref(s, mref.group(1)) if mref else None
            if waited and waited.active and waited.id != sender.id:
                task.waiting_on_id = waited.id
                extra.append(_waiting_notice(s, task, sender, waited))
                alert += f"\nWaiting on: {waited.name} (they can reply " \
                         f"'{task.id} unblock')"
            return Reply(react=True, alert_admin=alert, extra_sends=extra)
        if verb_norm == "unblock":
            if task.status != "blocked":
                return Reply(text=f"Task #{task.id} isn't blocked.")
            waited_id = task.waiting_on_id
            change_status(s, task, sender, "in_progress",
                          note=("unblocked: " + rest.strip()) if rest.strip()
                               else "unblocked",
                          channel="whatsapp", raw_text=raw)
            extra = []
            if sender.id != task.assignee_id:      # tell the owner it's back
                note = f" ({rest.strip()})" if rest.strip() else ""
                txt = (f"{sender.name} cleared the block on task "
                       f"#{task.id}: {task.title}{note} - back to you, "
                       f"{task.assignee.name}.\n\n" + _serial_footer(task.id))
                extra.append((_task_channel(s, task), txt))
            _ = waited_id   # link cleared inside change_status
            return Reply(react=True, extra_sends=extra)
    except PermissionError_ as e:
        return Reply(text=str(e))
    except InvalidTransition as e:
        return Reply(text=str(e))
    return Reply(text=HELP_TEXT)


def _tasks_in_quote(s, sender: Member, quoted: str,
                    group_id: int | None = None) -> list[Task]:
    """Task references found in a quoted bot message: leading '1.' digest
    numbers and '#12' serials. Returns unique resolved tasks."""
    nums: list[int] = []
    nums += [int(n) for n in re.findall(r"(?m)^\s*(?:\[!\]\s*)?(\d+)\.\s", quoted)]
    nums += [int(n) for n in re.findall(r"#(\d+)\b", quoted)]
    found: dict[int, Task] = {}
    for n in nums:
        t = resolve_ref(s, sender, n, group_id)
        if t:
            found[t.id] = t
    return list(found.values())


def _parse_add(s, body: str, sender: Member) -> tuple[dict | None, str | None]:
    text = body.strip()
    priority = "medium"
    for token, val in (("!high", "high"), ("!medium", "medium"),
                       ("!med", "medium"), ("!low", "low")):
        if token in text.lower():
            priority = val
            text = re.sub(re.escape(token), "", text, flags=re.IGNORECASE)
    assignee = sender
    m = re.search(r"@([A-Za-z][\w.]*|\d{6,20})", text)
    if m:
        found = _find_member_by_ref(s, m.group(1))
        if not found:
            return None, (f"I don't recognise '@{m.group(1)}' as a team member. "
                          "Use their registered name (e.g. @Ravi) or make sure "
                          "they are registered.")
        assignee = found
        text = text.replace(m.group(0), "")
    due = None
    words = text.split()
    if words:
        d = parse_date_word(words[-1])
        if d:
            due = d
            words = words[:-1]
    title = " ".join(words).strip(" -,")
    if not title:
        return None, "I need a task title, e.g. /add Buy cement @Ravi fri"
    return {"title": title, "assignee_id": assignee.id,
            "assignee_name": assignee.name, "priority": priority,
            "due": due.isoformat() if due else None}, None


def handle_message(s, sender: Member, body: str, admin: Member | None,
                   is_group: bool = False, quoted: str = "",
                   group_id: int | None = None) -> Reply:
    """Core dispatcher. Caller supplies a DB session and resolved sender."""
    body = (body or "").strip()
    if not body:
        return Reply()

    # ---- pending Y/N confirmation (an /add draft, or task acceptance) ----
    pending = (s.query(PendingConfirm)
                .filter(PendingConfirm.member_id == sender.id).first())
    if pending:
        if pending.expires_at < datetime.utcnow():
            s.delete(pending)
        elif RE_YES.match(body) or RE_NO.match(body):
            draft = json.loads(pending.draft_json)
            s.delete(pending)
            accepted = bool(RE_YES.match(body))
            if draft.get("kind") == "accept":
                return _handle_acceptance(s, sender, draft, accepted, body)
            if not accepted:
                return Reply(text="Cancelled - nothing created.")
            assignee = s.get(Member, draft["assignee_id"])
            t = create_task(
                s, title=draft["title"], assignee=assignee, creator=sender,
                priority=draft["priority"],
                due_date=date.fromisoformat(draft["due"]) if draft["due"] else None,
                post_to_group_id=draft.get("group_id"),
                channel="whatsapp", raw_text=body)
            return _created_reply(s, t, sender, assignee)

    # ---- numbered status update: "1 done", "12. block stuck on X" ----
    m = RE_STATUS.match(body)
    if m:
        num, verb, rest = int(m.group(1)), m.group(2), m.group(3).strip()
        task = resolve_ref(s, sender, num, group_id)
        if task is None:
            return Reply(text=f"There is no task {num}. "
                              "Send /mytasks to see yours.")
        return _apply_verb(s, sender, task, verb, rest, body)

    # ---- bare status update: "done", "block waiting on quote" ----
    m = RE_BARE.match(body)
    if m:
        verb, rest = m.group(1), m.group(2).strip()
        # 1) quoted (swipe) reply naming exactly one task wins
        if quoted:
            qtasks = _tasks_in_quote(s, sender, quoted, group_id)
            if len(qtasks) == 1:
                return _apply_verb(s, sender, qtasks[0], verb, rest, body)
            if len(qtasks) > 1:
                return Reply(text="That message lists several tasks - reply "
                                  "with the number, e.g. '1 done'.")
        # 2) exactly one open task: no number needed
        mine = open_tasks_for(s, sender)
        if len(mine) == 1:
            return _apply_verb(s, sender, mine[0], verb, rest, body)
        if len(mine) == 0:
            return Reply(text="You have no open tasks.", unmatched=True)
        # 3) ambiguous - ask for the number (suppressed in group/personal
        #    contexts, where bare words are usually just conversation)
        return Reply(text=f"You have {len(mine)} open tasks - add the number, "
                          "e.g. '1 done'. Send /mytasks to see them.",
                     unmatched=True)

    # ---- /add ----
    m = RE_ADD.match(body)
    if m:
        draft, err = _parse_add(s, m.group(1), sender)
        if err:
            return Reply(text=err)
        if group_id is not None:
            draft["group_id"] = group_id   # created in a group -> posts there
        s.query(PendingConfirm).filter(
            PendingConfirm.member_id == sender.id).delete()
        s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                             expires_at=datetime.utcnow() + timedelta(minutes=10)))
        s.flush()
        due_txt = (f", due {date.fromisoformat(draft['due']):%a %d %b}"
                   if draft["due"] else "")
        pr_txt = f", {draft['priority']} priority" if draft["priority"] != "medium" else ""
        return Reply(text=f"Create task: \"{draft['title']}\" -> "
                          f"{draft['assignee_name']}{due_txt}{pr_txt}?\n"
                          "Reply Y to confirm, N to cancel.")

    # ---- queries ----
    low = body.lower()
    if low.startswith("/mytasks"):
        tasks = open_tasks_for(s, sender)
        if not tasks:
            return Reply(text="You have no open tasks. Enjoy it.")
        save_digest_refs(s, sender, tasks)
        lines = [f"{i}. {_task_body(t)}" for i, t in enumerate(tasks, 1)]
        return Reply(text="*Your open tasks:*\n" + "\n".join(lines) +
                          "\n\nReply:  1 done  |  1 in progress  |  1 block <reason>")
    if low.startswith("/list"):
        q = s.query(Task).filter(Task.status.in_(("open", "in_progress", "blocked")))
        if sender.role != "admin":
            q = q.filter(Task.assignee_id == sender.id)
        tasks = sort_tasks(q.all())
        if not tasks:
            return Reply(text="No open tasks.")
        lines = [f"#{t.id} {_task_body(t)} ({t.assignee.name})" for t in tasks]
        return Reply(text="*Open tasks:*\n" + "\n".join(lines))
    if low.startswith("/help"):
        return Reply(text=HELP_TEXT)

    # ---- unmatched: ordinary conversation, not a command ----
    return Reply(text="I didn't understand that. Send /help for the command list.",
                 unmatched=True)

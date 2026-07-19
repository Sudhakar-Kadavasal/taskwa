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
import logging
import re
from datetime import date, datetime, timedelta

from .engine import (InvalidTransition, PermissionError_, change_status,
                     create_task, open_tasks_for, resolve_ref,
                     save_digest_refs, sort_tasks)
from .models import Group, Member, PendingConfirm, StatusEvent, Task

log = logging.getLogger("commands")

HELP_TEXT = (
    "*Task bot - commands*\n"
    "/add <title> @Name [#group] [!high|!low] [today|fri|25/07]\n"
    "   #group posts + announces it in that group\n"
    "/mytasks - your open tasks\n"
    "/myadd - open tasks you created for others\n"
    "/board - your task board as an image\n"
    "/list - open tasks you can see\n"
    "/help - this message\n"
    "\n"
    "*Names with a space - dot it, or quote it*\n"
    "@Ravi.Shankar   - a dot stands for the space\n"
    "@\"Ravi Shankar\"   - quotes work too\n"
    "#site.b or #\"Site B\"   - same for group names\n"
    "@Ravi alone is fine when it matches one person; if it\n"
    "matches two, the bot lists them and you reply 1 or 2.\n"
    "\n"
    "*Task updates* - 1 is your digest number\n"
    "1 done - close task 1\n"
    "1 in progress - mark started\n"
    "1 block <reason> - report a blocker (alerts admin)\n"
    "1 block waiting on @Ravi.Shankar - hand the block over\n"
    "1 unblock - release a block that waits on you\n"
    "1 reopen - undo a mistaken 'done'\n"
    "1 cancel - cancel a task you created (creator/admin only)\n"
    "Y / N - accept a new task, or decline it back to its creator\n"
    "Just 'done' works if you have a single open task,\n"
    "or swipe-reply on a task message and type 'done'."
)

ADMIN_HELP = (
    "\n\n*Admin (DM the bot only)*\n"
    "/nudge <HH:MM> [mon,wed,fri|daily] [@Name] [#group] <message>\n"
    "   - schedule a plain message (Nudger)\n"
    "/nudge <n> <time/days/@/#> - reschedule nudge n\n"
    "/nudge on|off|delete <n>\n"
    "/nudges - list all nudges\n"
    "/adduser <number> <name> - register a member\n"
    "/rename <@who> <new name> - change the name the team sees\n"
    "/members - list registered members\n"
    "/board preview [@Name #group ...] - rehearse boards to yourself\n"
    "   (no names = every active member/group with tasks; all sent to you)\n"
    "e.g. /nudge 07:30 tue @Ravi.Shankar What is the status\n"
    "     /nudge 730 tue @\"Ravi Shankar\" What is the status\n"
    "Time: 07:30  7:30  730  0730  7.30  7:30am  730pm  7am all work.\n"
    "(A bare '3' is a nudge number, not 3 o'clock - write 3pm or 15:00.)"
)

VERB = r"(done|reopen|in\s*-?\s*progress|inprogress|wip|block(?:er|ed)?|unblock|cancel(?:led)?)"
RE_STATUS = re.compile(rf"^\s*#?(\d+)[.):]?\s+{VERB}\b\s*(.*)$",
                       re.IGNORECASE | re.DOTALL)
RE_BARE = re.compile(rf"^\s*{VERB}\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
RE_ADD = re.compile(r"^\s*/add\s+(.+)$", re.IGNORECASE | re.DOTALL)
RE_YES = re.compile(r"^\s*(y|yes)\s*$", re.IGNORECASE)
RE_NO = re.compile(r"^\s*(n|no)\s*$", re.IGNORECASE)
# answer to a "which one?" list - a BARE number and nothing else, so that
# "2 done" keeps meaning "task 2, done" even while a pick is pending
RE_BARE_NUM = re.compile(r"^\s*(\d{1,2})[.)]?\s*$")

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
    (e.g. notifying an assignee) - each still vetted by the send allowlist.
    image_sends: (chat_id, png_bytes, caption) images to dispatch - each goes
    through waha.send_image, so the same allowlist/cap/throttle applies."""
    def __init__(self, text: str | None = None, react: bool = False,
                 alert_admin: str | None = None, unmatched: bool = False,
                 extra_sends: list | None = None, ambiguity=None,
                 image_sends: list | None = None):
        self.text = text
        self.react = react
        self.alert_admin = alert_admin
        self.unmatched = unmatched
        self.extra_sends = extra_sends or []
        self.image_sends = image_sends or []
        # set when a tag inside a status reply ('3 block waiting on @Ravi')
        # matched several people - the dispatcher turns it into the question
        self.ambiguity = ambiguity


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


def _created_reply(s, t: Task, sender: Member, assignee: Member,
                   announce: bool = False) -> Reply:
    """Receipt for the creator - always says what happens next, and how to
    reply (fixes the dead-end 'Created task #N' message). announce=True
    (tag-created group tasks) posts one immediate notice in the group so
    the creator instantly sees it reached the right place."""
    base = (f"Created task #{t.id}: {t.title} -> {assignee.name}"
            + (f", due {t.due_date:%a %d %b}" if t.due_date else ""))
    if announce and t.post_to_group_id and t.group and t.group.active:
        due = f" - due {t.due_date:%a %d %b}" if t.due_date else ""
        pr = " [HIGH]" if t.priority == "high" else ""
        note = (f"New task for {assignee.name}: {t.title}{due}{pr}\n\n"
                + _serial_footer(t.id))
        extra = [(t.group.chat_id, note)]
        own = ("\n\n" + _serial_footer(t.id) if assignee.id == sender.id else
               f"\n\nYou created it, so you can also:  "
               f"{t.id} done  |  {t.id} cancel")
        return Reply(text=base + f"\nAnnounced in {t.group.name}." + own,
                     extra_sends=extra)
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


# Quoted @names / #groups: @"Ravi Shankar" -> @Ravi.Shankar
# Any quote character opens, any quote character closes: phone keyboards curl
# quotes, and they get curled the WRONG way often enough (a pasted or
# space-preceded quote comes out as ” not “) that insisting on a matched pair
# would fail silently on real messages. Treat them all as one class.
QUOTES = "\"'`“”‘’«»"
RE_QUOTED_REF = re.compile(
    rf"([@#])\s*[{QUOTES}]\s*([^{QUOTES}]+?)\s*[{QUOTES}]")


def _dequote_refs(text: str) -> str:
    """Normalise the quoted form to the dotted form, so the rest of the parser
    keeps seeing one token: @"Ravi Shankar" / @“Ravi Shankar” -> @Ravi.Shankar,
    #"Site B Construction" -> #Site.B.Construction. Straight and curly quotes
    both work - phone keyboards curl them automatically. Quotes anywhere else
    in the message (a task title, a nudge body) are left untouched."""
    return RE_QUOTED_REF.sub(
        lambda m: m.group(1) + re.sub(r"\s+", ".", m.group(2).strip()), text)


def _match_group(s, token: str):
    """Resolve a #token to a registered active group by case-insensitive
    substring; dots stand in for spaces (#site.b -> 'site b').
    Returns (group, None) or (None, error_text). Never guesses on ambiguity."""
    from .models import Group
    needle = token.lstrip("#").replace(".", " ").strip().lower()
    if not needle:
        return None, "Group tag is empty - use e.g. #site"
    groups = s.query(Group).filter(Group.active.is_(True)).all()
    hits = [g for g in groups if needle in g.name.lower()]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, (f"No registered group matches '#{token.lstrip('#')}'. "
                      "Registered groups: "
                      + (", ".join(g.name for g in groups) or "none") + ".")
    return None, (f"'#{token.lstrip('#')}' matches several groups: "
                  + ", ".join(g.name for g in hits)
                  + ". Be more specific - dot it (#site.b) or quote it "
                    "(#\"Site B\").")


def _resolve_group_run(s, words: list[str], i: int):
    """words[i] starts with '#'. Same greedy rule as @names: absorb the
    following plain words so an unquoted, undotted group name works
    ('#De Leadership team'). The LONGEST run that matches exactly one group
    wins. Returns (group|None, next_index, error|None) - on failure the error
    is the one the single token alone would have produced, so an ambiguous
    '#site' still says 'matches several groups'."""
    best_g, best_j = None, i + 1
    j = i + 1
    parts = [words[i].lstrip("#").strip(",;:")]
    while True:
        g, _err = _match_group(s, ".".join(parts))
        if g:
            best_g, best_j = g, j
        if (j >= len(words) or len(parts) >= MAX_NAME_WORDS
                or _is_option_token(words[j])):
            break
        parts.append(words[j].strip(",;:"))
        j += 1
    if best_g:
        return best_g, best_j, None
    _g, err = _match_group(s, words[i])
    return None, i + 1, err


def _creator_in_group(sender: Member, chat_id: str):
    """True / False / None(=unverifiable: hidden participants exist and the
    sender wasn't among the resolvable ones)."""
    from .waha import group_member_phones
    phones, all_resolved = group_member_phones(chat_id)
    if sender.phone in phones:
        return True
    return False if all_resolved else None


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
    """Resolve a typed name. A dot stands in for a space (@Ravi.Shankar ->
    'ravi shankar'), matching the #group.tag convention. Exact match wins;
    otherwise a UNIQUE prefix match (@Ravi -> Ravi Shankar)."""
    name = name.replace(".", " ").strip().lower()
    name = re.sub(r"\s+", " ", name)
    if not name:
        return None
    members = s.query(Member).filter(Member.active.is_(True)).all()
    exact = [m for m in members if m.name.lower() == name]
    if exact:
        return exact[0]
    prefix = [m for m in members if m.name.lower().startswith(name)]
    return prefix[0] if len(prefix) == 1 else None


# How many words a member name may span when we greedily join tokens
# ('@Ravi shankar' typed without the dot).
MAX_NAME_WORDS = 4

# --- disambiguation ------------------------------------------------------
# When a tag matches more than one person (or nobody, but something close),
# the bot must never guess: it lists the candidates and asks for a number.
FUZZY_CUTOFF = 0.72     # tighten if typo-rescue starts offering junk
MAX_CANDIDATES = 5


class Ambiguity:
    """A tag that could mean several people/groups (or nobody, but something
    close). Returned in the error slot of the parsers; the dispatcher turns it
    into the numbered question. Never resolved by guessing."""
    def __init__(self, token: str, kind: str, candidates: list, how: str):
        self.token = token          # exactly as typed, e.g. '@Ravi'
        self.kind = kind            # 'member' | 'group'
        self.candidates = candidates
        self.how = how              # 'prefix' | 'fuzzy'


def _norm_ref(ref: str) -> str:
    return re.sub(r"\s+", " ", str(ref or "").replace(".", " ")).strip().lower()


def member_candidates(s, ref: str) -> tuple[list, str]:
    """Who could '@ref' mean? Returns (candidates, how).

    how = 'exact'  - one unambiguous hit (len 1)
          'prefix' - several names start with what was typed
          'fuzzy'  - nothing matched, but these are close (a typo)
          'none'   - nothing at all

    Never decides between candidates: that is the caller's job, via the user."""
    import difflib
    name = _norm_ref(ref)
    if not name:
        return [], "none"
    members = s.query(Member).filter(Member.active.is_(True)).all()
    exact = [m for m in members if m.name.lower() == name]
    if exact:
        return exact[:1], "exact"
    prefix = [m for m in members if m.name.lower().startswith(name)]
    if len(prefix) == 1:
        return prefix, "exact"
    if prefix:
        return prefix[:MAX_CANDIDATES], "prefix"
    # nothing starts with it - is it a typo? '@Rvai' -> Ravi Shankar.
    # Also catch a middle/last name being used on its own ('@Shankar').
    inside = [m for m in members if name in m.name.lower()]
    if len(inside) == 1:
        return inside, "exact"
    if inside:
        return inside[:MAX_CANDIDATES], "prefix"
    by_name = {m.name.lower(): m for m in members}
    close = difflib.get_close_matches(name, list(by_name), n=MAX_CANDIDATES,
                                      cutoff=FUZZY_CUTOFF)
    # a typo in the FIRST word is the common case ('@Rvai Shankar')
    first_words = {}
    for m in members:
        first_words.setdefault(m.name.split()[0].lower(), []).append(m)
    close_first = difflib.get_close_matches(name.split()[0], list(first_words),
                                            n=MAX_CANDIDATES,
                                            cutoff=FUZZY_CUTOFF)
    out, seen = [], set()
    for key in close:
        m = by_name[key]
        if m.id not in seen:
            out.append(m); seen.add(m.id)
    for key in close_first:
        for m in first_words[key]:
            if m.id not in seen:
                out.append(m); seen.add(m.id)
    return (out[:MAX_CANDIDATES], "fuzzy") if out else ([], "none")


def group_candidates(s, ref: str) -> tuple[list, str]:
    """Same, for a #tag. Substring match, as _match_group has always done."""
    from .models import Group
    name = _norm_ref(ref)
    groups = s.query(Group).filter(Group.active.is_(True)).all()
    if not name:
        return [], "none"
    hits = [g for g in groups if name in g.name.lower()]
    if len(hits) == 1:
        return hits, "exact"
    if hits:
        return hits[:MAX_CANDIDATES], "prefix"
    import difflib
    by_name = {g.name.lower(): g for g in groups}
    close = difflib.get_close_matches(name, list(by_name), n=MAX_CANDIDATES,
                                      cutoff=FUZZY_CUTOFF)
    out = [by_name[k] for k in close]
    return (out, "fuzzy") if out else ([], "none")


def _member_problem(s, token: str):
    """An @token didn't resolve. Ambiguity (ask which one) or a plain error."""
    cands, how = member_candidates(s, token.lstrip("@"))
    if how in ("prefix", "fuzzy") and len(cands) > 1:
        return Ambiguity(token, "member", cands, how)
    if how == "fuzzy" and len(cands) == 1:
        return Ambiguity(token, "member", cands, how)   # "did you mean X?"
    return (f"I don't recognise '{token}' as a team member. If the name has a "
            "space, dot it (@Ravi.Shankar) or quote it (@\"Ravi Shankar\"). "
            "Send /members to see the list.")


def _group_problem(s, token: str):
    """Same for a #tag."""
    cands, how = group_candidates(s, token.lstrip("#"))
    if how in ("prefix", "fuzzy") and cands:
        return Ambiguity(token, "group", cands, how)
    from .models import Group
    groups = s.query(Group).filter(Group.active.is_(True)).all()
    return (f"No registered group matches '{token}'. Registered groups: "
            + (", ".join(g.name for g in groups) or "none") + ".")


def _pick_reply(s, sender: Member, raw_body: str, token: str,
                candidates: list, how: str, kind: str) -> Reply:
    """Park the command and ask which one. The user answers with a bare number;
    handle_message then rewrites the ORIGINAL command with the chosen
    member/group spelled out unambiguously and re-runs it - so every command
    keeps its normal parsing, confirmation and permission path."""
    lead = (f"'{token}' matches {len(candidates)} "
            + ("people" if kind == "member" else "groups") + ":"
            if how == "prefix" else
            f"I don't have anyone called '{token.lstrip('@#')}'. Did you mean:"
            if kind == "member" else
            f"No group matches '{token.lstrip('#')}'. Did you mean:")
    lines = [lead]
    for n, c in enumerate(candidates, 1):
        # last 4 digits: enough to tell two people apart, not a number dump
        detail = f"  (...{c.phone[-4:]})" if kind == "member" else ""
        lines.append(f"  {n}. {c.name}{detail}")
    lines.append("")
    lines.append("Reply with the number. Anything else cancels this and is "
                 "read as a new message.")
    draft = {"kind": "pick", "what": kind, "raw": raw_body, "token": token,
             "ids": [c.id for c in candidates]}
    s.query(PendingConfirm).filter(
        PendingConfirm.member_id == sender.id).delete()
    s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                         expires_at=datetime.utcnow() + timedelta(minutes=10)))
    s.flush()
    return Reply(text="\n".join(lines))


def _is_option_token(w: str) -> bool:
    """A token that belongs to the schedule/option grammar, never to a name."""
    return (_parse_time_token(w) is not None or _parse_day_token(w) is not None
            or w.startswith("@") or w.startswith("#") or w.startswith("!"))


def _resolve_member_run(s, words: list[str], i: int):
    """words[i] starts with '@'. Resolve it, greedily absorbing the following
    plain words so an unquoted spaced name works too ('@Ravi shankar').
    Longest run that resolves wins. Returns (member|None, next_index)."""
    ref = words[i].lstrip("@").strip(",;:")
    if not ref:
        return None, i + 1
    best_m, best_j = None, i + 1
    j = i + 1
    parts = [ref]
    while True:
        m = _find_member_by_ref(s, " ".join(parts)) if len(parts) == 1 \
            else _find_member_by_name(s, " ".join(parts))
        if m:
            best_m, best_j = m, j
        if (j >= len(words) or len(parts) >= MAX_NAME_WORDS
                or _is_option_token(words[j])):
            break
        parts.append(words[j].strip(",;:"))
        j += 1
    return best_m, best_j


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
            # "block waiting on @Priya" -> hand the block to that person.
            # Names may be dotted (@Ravi.Shankar), quoted (normalised upstream)
            # or spaced (@Ravi Shankar - joined greedily). Resolved BEFORE the
            # status change: if the name is ambiguous we ask which one, and the
            # block must not already be recorded when the command re-runs.
            rwords = reason.split()
            at = next((k for k, w in enumerate(rwords)
                       if re.match(r"^@([A-Za-z][\w.]*|\d{6,20})", w)), None)
            waited = _resolve_member_run(s, rwords, at)[0] if at is not None \
                else None
            if at is not None and waited is None:
                prob = _member_problem(s, rwords[at])
                if isinstance(prob, Ambiguity):
                    return Reply(ambiguity=prob)
            change_status(s, task, sender, "blocked", note=reason,
                          channel="whatsapp", raw_text=raw)
            alert = (f"[!] Blocker on task #{task.id} '{task.title}'\n"
                     f"By: {sender.name}\nReason: {reason}")
            extra = []
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


def _parse_add(s, body: str, sender: Member):
    """Returns (draft, error). The error may be an Ambiguity - the caller turns
    that into the numbered "which one?" question."""
    text = body.strip()
    priority = "medium"
    for token, val in (("!high", "high"), ("!medium", "medium"),
                       ("!med", "medium"), ("!low", "low")):
        if token in text.lower():
            priority = val
            text = re.sub(re.escape(token), "", text, flags=re.IGNORECASE)
    words = text.split()
    # optional #group tag: post the task to that group (DM-created tasks)
    tag_group = None
    gi = next((k for k, w in enumerate(words) if w.startswith("#")), None)
    if gi is not None:
        tag_group, gnxt, gerr = _resolve_group_run(s, words, gi)
        if gerr:
            return None, _group_problem(s, words[gi])
        words = words[:gi] + words[gnxt:]
    assignee = sender
    at = next((k for k, w in enumerate(words)
               if re.match(r"^@([A-Za-z][\w.]*|\d{6,20})", w)), None)
    if at is not None:
        found, nxt = _resolve_member_run(s, words, at)
        if not found:
            return None, _member_problem(s, words[at])
        assignee = found
        words = words[:at] + words[nxt:]
    due = None
    if words:
        d = parse_date_word(words[-1])
        if d:
            due = d
            words = words[:-1]
    title = " ".join(words).strip(" -,")
    if not title:
        return None, "I need a task title, e.g. /add Buy cement @Ravi fri"
    draft = {"title": title, "assignee_id": assignee.id,
             "assignee_name": assignee.name, "priority": priority,
             "due": due.isoformat() if due else None}
    if tag_group is not None:
        draft["group_id"] = tag_group.id
        draft["group_name"] = tag_group.name
        draft["group_via_tag"] = True    # membership checked at Y-time
    return draft, None


# ---------------- admin commands (DM only): /nudge /nudges /adduser -------
DAY_ALIASES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
               "sat": 5, "sun": 6}

# Times, the way people actually type them on a phone. Separator may be a
# colon, a dot or nothing; am/pm optional (and may arrive as its own token,
# see _join_ampm). A BARE 1-2 digit number is deliberately NOT a time: it
# would collide with the nudge id in '/nudge 3 08:15'. Write '7am' or '07:00'.
RE_AMPM = re.compile(r"^([ap])\.?m\.?$", re.IGNORECASE)


def _parse_time_token(tok: str) -> str | None:
    """Any reasonable spelling of a clock time -> 'HH:MM'. None if it isn't
    one. Accepts 07:30 7:30 7.30 0730 730 7:30am 730pm 7am (case-free)."""
    t = tok.strip().lower().rstrip(",;")
    m = re.match(r"^(?:(\d{1,2})[:.](\d{2})|(\d{3,4})|(\d{1,2}))"
                 r"\s*(a\.?m\.?|p\.?m\.?)?$", t)
    if not m:
        return None
    ampm = (m.group(5) or "").replace(".", "")
    if m.group(1) is not None:                       # 7:30 / 7.30
        hh, mm = int(m.group(1)), int(m.group(2))
    elif m.group(3) is not None:                     # 730 / 0730
        digits = m.group(3)
        hh, mm = int(digits[:-2]), int(digits[-2:])
    else:                                            # bare 1-2 digits
        if not ampm:
            return None      # '3' is a nudge id, not a time. '3pm' is a time.
        hh, mm = int(m.group(4)), 0
    if ampm:
        if not 1 <= hh <= 12:
            return None
        hh = (hh % 12) + (12 if ampm.startswith("p") else 0)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _join_ampm(words: list[str]) -> list[str]:
    """'7:30 pm' arrives as two tokens - glue the am/pm back on."""
    out: list[str] = []
    for w in words:
        if out and RE_AMPM.match(w) and re.match(r"^\d{1,4}([:.]\d{2})?$",
                                                 out[-1]):
            out[-1] = out[-1] + w
        else:
            out.append(w)
    return out


def _parse_day_token(tok: str):
    """'mon,wed,fri' -> [0,2,4]; 'daily' -> []; else None."""
    if tok.lower() == "daily":
        return []
    parts = tok.lower().split(",")
    if all(p[:3] in DAY_ALIASES for p in parts if p):
        return sorted({DAY_ALIASES[p[:3]] for p in parts if p})
    return None


def _parse_schedule_tokens(s, words):
    """Consume leading option tokens (a time, day lists, @members, #groups).
    Returns (dict, remaining_words, error|None)."""
    out = {"send_time": "", "days": None, "member_ids": [], "group_ids": [],
           "recipient_names": []}
    words = _join_ampm(words)
    i = 0
    while i < len(words):
        w = words[i]
        hhmm = _parse_time_token(w)
        if hhmm:
            out["send_time"] = hhmm
            i += 1
            continue
        days = _parse_day_token(w)
        if days is not None:
            out["days"] = days
            i += 1
            continue
        if w.startswith("@") and len(w) > 1:
            m, nxt = _resolve_member_run(s, words, i)
            if not m:
                return None, None, _member_problem(s, w)
            out["member_ids"].append(m.id)
            out["recipient_names"].append(m.name)
            i = nxt
            continue
        if w.startswith("#") and len(w) > 1:
            g, nxt, gerr = _resolve_group_run(s, words, i)
            if gerr:
                return None, None, _group_problem(s, w)
            out["group_ids"].append(g.id)
            out["recipient_names"].append(g.name)
            i = nxt
            continue
        break
    return out, words[i:], None


def _nudge_summary(s, b) -> str:
    import json as _j
    mids, gids = _j.loads(b.member_ids or "[]"), _j.loads(b.group_ids or "[]")
    names = ([m.name for m in s.query(Member).filter(Member.id.in_(mids))]
             if mids else []) + \
            ([g.name for g in s.query(Group).filter(Group.id.in_(gids))]
             if gids else [])
    days = _j.loads(b.days or "[]")
    from .broadcasts import DAY_NAMES
    sched = ("manual only" if not b.send_time else
             f"{b.send_time} ({b.tz}) "
             + ("every day" if not days or len(days) == 7
                else ",".join(DAY_NAMES[d] for d in days)))
    state = "active" if b.active else "PAUSED"
    return f"{sched} -> {', '.join(names) or 'nobody'} [{state}]"


def _handle_nudge_cmd(s, sender: Member, rest: str, raw: str = "") -> Reply:
    """/nudge …  - create, reschedule, on/off, delete. `raw` is the original
    message, kept so an ambiguous @name can park it and re-run it on the pick."""
    from .models import Broadcast
    words = _join_ampm(rest.split())   # before the id check: '7 am' is a time
    if not words:
        return Reply(text="Usage:\n/nudge [HH:MM] [mon,wed,fri|daily] "
                          "[@Name…] [#group…] <message>\n"
                          "/nudge <n> <new time/days/recipients>\n"
                          "/nudge on|off|delete <n>\n/nudges - list")
    # --- on / off / delete <id> ---
    if words[0].lower() in ("on", "off", "delete") and len(words) == 2 \
            and words[1].isdigit():
        b = s.get(Broadcast, int(words[1]))
        if b is None:
            return Reply(text=f"There is no nudge {words[1]}. Send /nudges.")
        act = words[0].lower()
        if act == "delete":
            s.query(PendingConfirm).filter(
                PendingConfirm.member_id == sender.id).delete()
            s.add(PendingConfirm(member_id=sender.id,
                  draft_json=json.dumps({"kind": "nudge_delete", "id": b.id}),
                  expires_at=datetime.utcnow() + timedelta(minutes=10)))
            s.flush()
            return Reply(text=f"Delete nudge {b.id} \"{b.name}\"? "
                              "Reply Y to confirm, N to cancel.")
        b.active = (act == "on")
        _reload_nudge_jobs()
        return Reply(text=f"Nudge {b.id} \"{b.name}\" is now "
                          + ("active." if b.active else "paused."))
    # --- reschedule: /nudge <id> <tokens> ---
    # A leading number is a nudge id... unless it's really a time. '730' and
    # '0730' are times; '3' is an id. An existing nudge with that id always
    # wins, so /nudge 3 08:15 keeps working.
    if words[0].isdigit() and not (s.get(Broadcast, int(words[0])) is None
                                   and _parse_time_token(words[0])):
        b = s.get(Broadcast, int(words[0]))
        if b is None:
            return Reply(text=f"There is no nudge {words[0]}. Send /nudges.")
        opts, remaining, err = _parse_schedule_tokens(s, words[1:])
        if isinstance(err, Ambiguity):
            return _pick_reply(s, sender, raw, err.token, err.candidates,
                               err.how, err.kind)
        if err:
            return Reply(text=err)
        if remaining:
            return Reply(text="To change the text, delete and recreate the "
                              "nudge (or use the dashboard). I can change "
                              "time, days and recipients: e.g.  /nudge "
                              f"{b.id} 08:00 tue,thu @Ravi #site")
        changed = []
        if opts["send_time"]:
            b.send_time = opts["send_time"]; changed.append("time")
        if opts["days"] is not None:
            b.days = json.dumps(opts["days"]); changed.append("days")
        if opts["member_ids"] or opts["group_ids"]:
            b.member_ids = json.dumps(opts["member_ids"])
            b.group_ids = json.dumps(opts["group_ids"])
            changed.append("recipients")
        if not changed:
            return Reply(text="Nothing to change - give a time, days or "
                              "recipients.")
        _reload_nudge_jobs()
        return Reply(text=f"Nudge {b.id} updated ({', '.join(changed)}):\n"
                          + _nudge_summary(s, b))
    # --- create ---
    opts, remaining, err = _parse_schedule_tokens(s, words)
    if isinstance(err, Ambiguity):
        return _pick_reply(s, sender, raw, err.token, err.candidates,
                           err.how, err.kind)
    if err:
        return Reply(text=err)
    message = " ".join(remaining).strip()
    if not message:
        return Reply(text="The nudge needs a message, e.g.\n"
                          "/nudge 07:30 mon,fri #site Good morning team")
    if not opts["member_ids"] and not opts["group_ids"]:
        return Reply(text="Who is it for? Add @Name members and/or a "
                          "#group.")
    if not opts["send_time"]:
        return Reply(text="When should it go out? I need a time, e.g.\n"
                          "/nudge 07:30 tue @Ravi.Shankar " + message[:30]
                          + "\nAny of these work: 07:30  7:30  730  0730  "
                            "7.30  7:30am  730pm  7am\n"
                            "Days are optional - no days means every day.")
    draft = {"kind": "nudge", "message": message,
             "member_ids": opts["member_ids"], "group_ids": opts["group_ids"],
             "days": opts["days"] or [], "send_time": opts["send_time"],
             "recipient_names": opts["recipient_names"]}
    s.query(PendingConfirm).filter(
        PendingConfirm.member_id == sender.id).delete()
    s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                         expires_at=datetime.utcnow() + timedelta(minutes=10)))
    s.flush()
    from .broadcasts import DAY_NAMES
    sched = ("manual only (fire it from the dashboard)" if not opts["send_time"]
             else opts["send_time"] + " "
             + ("every day" if not draft["days"] or len(draft["days"]) == 7
                else ",".join(DAY_NAMES[d] for d in draft["days"])))
    return Reply(text=f"Create nudge: \"{message}\"\n"
                      f"-> {', '.join(opts['recipient_names'])}, {sched}\n"
                      "Reply Y to confirm, N to cancel.")


def _reload_nudge_jobs():
    try:
        from .scheduler import reload_broadcast_jobs
        reload_broadcast_jobs()
    except Exception:   # scheduler not running (tests) - jobs load on boot
        pass


def _confirm_nudge(s, sender: Member, draft: dict, accepted: bool) -> Reply:
    if not accepted:
        return Reply(text="Cancelled - no nudge created.")
    from .db import get_setting
    from .models import Broadcast
    b = Broadcast(name=draft["message"][:40],
                  message=draft["message"],
                  member_ids=json.dumps(draft["member_ids"]),
                  group_ids=json.dumps(draft["group_ids"]),
                  days=json.dumps(draft["days"]),
                  send_time=draft["send_time"],
                  tz=get_setting(s, "timezone") or "UTC",
                  active=True)
    s.add(b)
    s.flush()
    _reload_nudge_jobs()
    return Reply(text=f"Nudge {b.id} created:\n" + _nudge_summary(s, b)
                      + "\nManage with /nudges.")


def _confirm_nudge_delete(s, draft: dict, accepted: bool) -> Reply:
    from .models import Broadcast
    if not accepted:
        return Reply(text="Kept - nothing deleted.")
    b = s.get(Broadcast, draft.get("id"))
    if b is None:
        return Reply(text="That nudge is already gone.")
    name = b.name
    s.delete(b)
    s.flush()
    _reload_nudge_jobs()
    return Reply(text=f"Deleted nudge \"{name}\".")


def _handle_rename_cmd(s, sender: Member, rest: str, raw: str = "") -> Reply:
    """/rename <@who|number> <new name> - change the name the team sees.

    The target is ONE token on purpose (@Ravi, @Ravi.Shankar, @"Ravi Shankar"
    - normalised to the dotted form upstream - or the phone number). Greedy
    multi-word matching would fight the new name that follows it: in
    '/rename @Ravi Ravi Shankar' there is no way to tell where the target ends
    and the new name begins."""
    from .engine import check_rename, clean_member_name
    words = rest.split()
    if len(words) < 2:
        return Reply(text="Usage: /rename <@who> <new name>\n"
                          "e.g.  /rename @Ravi Ravi Shankar\n"
                          "      /rename @Ravi.Shankar Ravi S Kumar\n"
                          "      /rename 971501234567 Ravi Shankar\n"
                          "The name is what the team sees in group "
                          "announcements and digests. /members lists everyone.")
    ref = words[0].lstrip("@")
    target = _find_member_by_ref(s, ref)
    if target is None:
        prob = _member_problem(s, words[0])
        if isinstance(prob, Ambiguity):
            return _pick_reply(s, sender, raw, prob.token, prob.candidates,
                               prob.how, prob.kind)
        return Reply(text=prob)
    new_name = clean_member_name(" ".join(words[1:]))
    # validated BEFORE the Y/N prompt, so a duplicate is refused straight away
    ok, err = check_rename(s, target, new_name)
    if not ok:
        return Reply(text=err)
    if new_name == target.name:
        return Reply(text=f"{target.name} is already called that.")
    draft = {"kind": "rename", "member_id": target.id,
             "old_name": target.name, "new_name": new_name}
    s.query(PendingConfirm).filter(
        PendingConfirm.member_id == sender.id).delete()
    s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                         expires_at=datetime.utcnow() + timedelta(minutes=10)))
    s.flush()
    return Reply(text=f"Rename \"{draft['old_name']}\" to "
                      f"\"{draft['new_name']}\"?\nThis is the name the team "
                      "sees in group announcements, digests and alerts - and "
                      f"how they address them (@{draft['new_name'].split()[0]})"
                      ".\nReply Y to confirm, N to cancel.")


def _confirm_rename(s, draft: dict, accepted: bool) -> Reply:
    from .engine import rename_member
    if not accepted:
        return Reply(text="Cancelled - name unchanged.")
    m = s.get(Member, draft.get("member_id"))
    if m is None:
        return Reply(text="That member is gone.")
    ok, msg = rename_member(s, m, draft["new_name"])
    return Reply(text=msg)


def _handle_adduser_cmd(s, sender: Member, rest: str) -> Reply:
    # the number may be written with spaces/+/dashes: consume phone-like
    # tokens until the first word containing letters (= start of the name)
    words = rest.split()
    i, phone = 0, ""
    while i < len(words) and re.fullmatch(r"[+\d()\-]+", words[i]):
        phone += "".join(ch for ch in words[i] if ch.isdigit())
        i += 1
    name = " ".join(words[i:]).strip()
    if not phone or not (8 <= len(phone) <= 15) or not name:
        return Reply(text="Usage: /adduser <number with country code> <name>"
                          "\ne.g.  /adduser 971501234567 Ravi Kumar")
    existing = s.query(Member).filter(Member.phone == phone).first()
    if existing and existing.active:
        return Reply(text=f"{phone} is already registered as "
                          f"{existing.name}.")
    draft = {"kind": "adduser", "phone": phone, "name": name[:60],
             "reactivate": bool(existing)}
    s.query(PendingConfirm).filter(
        PendingConfirm.member_id == sender.id).delete()
    s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                         expires_at=datetime.utcnow() + timedelta(minutes=10)))
    s.flush()
    verb = "Re-activate" if existing else "Add"
    return Reply(text=f"{verb} member: {draft['name']} - {phone} (role: "
                      "member)?\nCheck the number carefully. "
                      "Reply Y to confirm, N to cancel.")


def _confirm_adduser(s, draft: dict, accepted: bool) -> Reply:
    if not accepted:
        return Reply(text="Cancelled - nobody added.")
    existing = s.query(Member).filter(
        Member.phone == draft["phone"]).first()
    if existing:
        existing.active = True
        # The stored name is kept: it is the addressing key (@Ravi.Shankar) and
        # what the team sees in group announcements. Re-adding someone must not
        # silently overwrite a name that was curated on the dashboard. Rename
        # there if it needs changing.
        kept = "" if existing.name == draft["name"] else \
            f"\nName kept as \"{existing.name}\" (rename on the dashboard)."
        return Reply(text=f"Re-activated {existing.name} ({existing.phone}). "
                          "They can use commands right away." + kept)
    m = Member(name=draft["name"], phone=draft["phone"], role="member")
    s.add(m)
    s.flush()
    return Reply(text=f"Added {m.name} ({m.phone}) as a member. They can "
                      "use commands right away; digests start once they "
                      "have tasks. Promote to admin from the dashboard "
                      "if needed.")


def _verb_reply(s, sender: Member, body: str, r: Reply) -> Reply:
    """A status reply whose @name was ambiguous asks which one instead. The
    status change has NOT been applied - the whole command re-runs on the pick."""
    if r.ambiguity is not None:
        a = r.ambiguity
        return _pick_reply(s, sender, body, a.token, a.candidates, a.how,
                           a.kind)
    return r


def _board_sub(open_tasks: list) -> str:
    """The little header line under a board: open + blocked counts."""
    blocked = sum(1 for t in open_tasks if t.status == "blocked")
    return f"{len(open_tasks)} open · {blocked} blocked"


def _recent_done_for(s, member: Member) -> list:
    """Tasks this member completed in the last 7 days, newest first."""
    week = datetime.utcnow() - timedelta(days=7)
    return (s.query(Task)
             .filter(Task.assignee_id == member.id, Task.status == "done",
                     Task.completed_at.isnot(None), Task.completed_at >= week)
             .order_by(Task.completed_at.desc()).all())


def _group_open_tasks(s, group) -> list:
    """Open/in-progress/blocked tasks posted to a group, in board order."""
    rows = (s.query(Task)
             .filter(Task.post_to_group_id == group.id,
                     Task.status.in_(("open", "in_progress", "blocked")))
             .all())
    return sort_tasks(rows)


def _handle_my_board(s, sender: Member) -> Reply:
    """/board (alias /myboard) - render the sender's own board and send it to
    their own DM. No text reply, so typing /board in a group posts nothing to
    the group - the image lands privately."""
    from .board_render import render_member_board
    tasks = open_tasks_for(s, sender)
    done = _recent_done_for(s, sender)
    png = render_member_board(sender.name, _board_sub(tasks), tasks, done)
    chat = f"{sender.phone}@c.us"
    return Reply(text="", image_sends=[(chat, png, "Your board")])


def _handle_board_preview(s, sender: Member, arg: str) -> Reply:
    """Admin-only rehearsal: render the chosen (or all active) member/group
    boards and send EVERY image to the admin's own DM - never to the person
    the board is about. A private dry-run of what a team-wide push would look
    like, with zero risk to anyone else. Uses the shared @name/#group
    resolvers so it matches /add and /nudge exactly."""
    from .board_render import render_member_board, render_group_board
    admin_chat = f"{sender.phone}@c.us"
    members, groups, unresolved = [], [], []

    arg = arg.strip()
    if not arg:
        members = s.query(Member).filter(Member.active.is_(True)).all()
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        skip_empty = True
    else:
        words = arg.split()
        i = 0
        while i < len(words):
            w = words[i]
            if w.startswith("@"):
                m, i = _resolve_member_run(s, words, i)
                (members if m else unresolved).append(m or words[i - 1])
            elif w.startswith("#"):
                g, nxt, _err = _resolve_group_run(s, words, i)
                (groups if g else unresolved).append(g or words[i])
                i = nxt
            else:
                unresolved.append(w)
                i += 1
        skip_empty = False   # a name asked for explicitly renders even if empty

    unresolved = [u for u in unresolved if isinstance(u, str)]
    if unresolved:
        return Reply(text="Couldn't resolve: " + ", ".join(unresolved)
                          + ".\nUse @Name / #group (dot or quote spaces). "
                            "/members lists everyone.")

    sends = []
    for m in members:
        tasks = open_tasks_for(s, m)
        done = _recent_done_for(s, m)
        if skip_empty and not tasks and not done:
            continue
        png = render_member_board(m.name, _board_sub(tasks), tasks, done)
        sends.append((admin_chat, png, f"Preview · {m.name}"))
    for g in groups:
        gtasks = _group_open_tasks(s, g)
        if skip_empty and not gtasks:
            continue
        png = render_group_board(g.name, _board_sub(gtasks), gtasks)
        sends.append((admin_chat, png, f"Preview · {g.name} (group)"))

    if not sends:
        return Reply(text="Nothing to preview - no active member or group has "
                          "any tasks right now.")
    n = len(sends)
    return Reply(text=f"Previewing {n} board{'s' if n != 1 else ''} to you "
                      "only (nobody else gets these).",
                 image_sends=sends)


def _apply_pick(s, sender: Member, draft: dict, chosen_id: int,
                admin, is_group, quoted, group_id) -> Reply:
    """The user picked a number. Rewrite the ORIGINAL command with that person
    (or group) spelled out unambiguously, and run it again through the normal
    dispatcher - so the command keeps its usual parsing, confirmation and
    permission checks, and a second ambiguous tag in the same command simply
    asks again."""
    if draft["what"] == "member":
        chosen = s.get(Member, chosen_id)
        if chosen is None or not chosen.active:
            return Reply(text="That person is no longer registered.")
        replacement = "@" + chosen.phone          # never ambiguous
    else:
        chosen = s.get(Group, chosen_id)
        if chosen is None or not chosen.active:
            return Reply(text="That group is no longer registered.")
        replacement = "#" + chosen.name.replace(" ", ".")
    rewritten = draft["raw"].replace(draft["token"], replacement, 1)
    log.info("pick: %r -> %r", draft["raw"], rewritten)
    return handle_message(s, sender, rewritten, admin, is_group=is_group,
                          quoted=quoted, group_id=group_id)


def handle_message(s, sender: Member, body: str, admin: Member | None,
                   is_group: bool = False, quoted: str = "",
                   group_id: int | None = None) -> Reply:
    """Core dispatcher. Caller supplies a DB session and resolved sender."""
    body = (body or "").strip()
    if not body:
        return Reply()
    # @"Ravi Shankar" / #"Site B" -> the dotted form the parsers expect.
    # Done once, here, so every command path accepts both spellings.
    body = _dequote_refs(body)

    # ---- pending Y/N confirmation (an /add draft, or task acceptance) ----
    pending = (s.query(PendingConfirm)
                .filter(PendingConfirm.member_id == sender.id).first())
    if pending:
        if pending.expires_at < datetime.utcnow():
            s.delete(pending)
        elif json.loads(pending.draft_json).get("kind") == "pick":
            # "which Ravi?" - a BARE number answers it. Anything else (even
            # '2 done') is a normal message: the pick is dropped, not guessed.
            draft = json.loads(pending.draft_json)
            s.delete(pending)
            s.flush()
            if RE_BARE_NUM.match(body):
                n = int(body.strip())
                ids = draft["ids"]
                if not 1 <= n <= len(ids):
                    return Reply(text=f"There's no {n} on that list. Send the "
                                      "command again.")
                return _apply_pick(s, sender, draft, ids[n - 1], admin,
                                   is_group, quoted, group_id)
            # fall through: re-parse this message from scratch
        elif RE_YES.match(body) or RE_NO.match(body):
            draft = json.loads(pending.draft_json)
            s.delete(pending)
            accepted = bool(RE_YES.match(body))
            if draft.get("kind") == "accept":
                return _handle_acceptance(s, sender, draft, accepted, body)
            if draft.get("kind") == "nudge":
                return _confirm_nudge(s, sender, draft, accepted)
            if draft.get("kind") == "nudge_delete":
                return _confirm_nudge_delete(s, draft, accepted)
            if draft.get("kind") == "rename":
                return _confirm_rename(s, draft, accepted)
            if draft.get("kind") == "adduser":
                return _confirm_adduser(s, draft, accepted)
            if not accepted:
                return Reply(text="Cancelled - nothing created.")
            # tag-targeted group task: the creator must be in that group
            if draft.get("group_via_tag") and sender.role != "admin":
                g = s.get(Group, draft["group_id"])
                ok = _creator_in_group(sender, g.chat_id) if g else False
                if ok is not True:
                    why = ("I couldn't verify that group's member list "
                           "(hidden numbers) - ask an admin to create it, "
                           "or make the bot's number a group admin and try "
                           "again.") if ok is None else \
                          "you don't appear to be a member of that group."
                    return Reply(text="Not created - "
                                      f"{g.name if g else 'group'}: {why}")
            assignee = s.get(Member, draft["assignee_id"])
            t = create_task(
                s, title=draft["title"], assignee=assignee, creator=sender,
                priority=draft["priority"],
                due_date=date.fromisoformat(draft["due"]) if draft["due"] else None,
                post_to_group_id=draft.get("group_id"),
                channel="whatsapp", raw_text=body)
            return _created_reply(s, t, sender, assignee,
                                  announce=bool(draft.get("group_via_tag")))

    # ---- numbered status update: "1 done", "12. block stuck on X" ----
    m = RE_STATUS.match(body)
    if m:
        num, verb, rest = int(m.group(1)), m.group(2), m.group(3).strip()
        task = resolve_ref(s, sender, num, group_id)
        if task is None:
            return Reply(text=f"There is no task {num}. "
                              "Send /mytasks to see yours.")
        return _verb_reply(s, sender, body,
                          _apply_verb(s, sender, task, verb, rest, body))

    # ---- bare status update: "done", "block waiting on quote" ----
    m = RE_BARE.match(body)
    if m:
        verb, rest = m.group(1), m.group(2).strip()
        # 1) quoted (swipe) reply naming exactly one task wins
        if quoted:
            qtasks = _tasks_in_quote(s, sender, quoted, group_id)
            if len(qtasks) == 1:
                return _verb_reply(s, sender, body, _apply_verb(
                    s, sender, qtasks[0], verb, rest, body))
            if len(qtasks) > 1:
                return Reply(text="That message lists several tasks - reply "
                                  "with the number, e.g. '1 done'.")
        # 2) exactly one open task: no number needed
        mine = open_tasks_for(s, sender)
        if len(mine) == 1:
            return _verb_reply(s, sender, body, _apply_verb(
                s, sender, mine[0], verb, rest, body))
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
        if isinstance(err, Ambiguity):
            return _pick_reply(s, sender, body, err.token, err.candidates,
                               err.how, err.kind)
        if err:
            return Reply(text=err)
        if group_id is not None:           # created in a group -> posts there
            draft["group_id"] = group_id   # (context beats any #tag)
            draft.pop("group_via_tag", None)
            draft.pop("group_name", None)
        s.query(PendingConfirm).filter(
            PendingConfirm.member_id == sender.id).delete()
        s.add(PendingConfirm(member_id=sender.id, draft_json=json.dumps(draft),
                             expires_at=datetime.utcnow() + timedelta(minutes=10)))
        s.flush()
        due_txt = (f", due {date.fromisoformat(draft['due']):%a %d %b}"
                   if draft["due"] else "")
        pr_txt = f", {draft['priority']} priority" if draft["priority"] != "medium" else ""
        grp_txt = (f", announced in {draft['group_name']}"
                   if draft.get("group_via_tag") else "")
        return Reply(text=f"Create task: \"{draft['title']}\" -> "
                          f"{draft['assignee_name']}{due_txt}{pr_txt}{grp_txt}?\n"
                          "Reply Y to confirm, N to cancel.")

    # ---- queries ----
    low = body.lower()

    # ---- admin commands: DM only, admin only ----
    if (low.startswith("/nudge") or low.startswith("/adduser")
            or low.startswith("/members") or low.startswith("/rename")):
        if is_group:
            return Reply(unmatched=True)   # never discussed in groups
        if sender.role != "admin":
            return Reply(text="That's an admin command.")
        if low.startswith("/nudges"):
            from .models import Broadcast
            rows = s.query(Broadcast).order_by(Broadcast.id).all()
            if not rows:
                return Reply(text="No nudges yet. Create one:\n/nudge 07:30 "
                                  "mon,fri #site Good morning team")
            lines = [f"{b.id}. \"{b.name}\"\n   " + _nudge_summary(s, b)
                     for b in rows]
            return Reply(text="*Nudges:*\n" + "\n".join(lines)
                              + "\n\n/nudge on|off|delete <n> - manage\n"
                                "/nudge <n> <time/days/@/#> - reschedule")
        if low.startswith("/nudge"):
            return _handle_nudge_cmd(s, sender, body[6:].strip(), raw=body)
        if low.startswith("/adduser"):
            return _handle_adduser_cmd(s, sender, body[8:].strip())
        if low.startswith("/rename"):
            return _handle_rename_cmd(s, sender, body[7:].strip(), raw=body)
        # /members
        members = (s.query(Member).order_by(Member.name).all())
        lines = [f"- {m.name} ({m.phone})"
                 + (" - admin" if m.role == "admin" else "")
                 + ("" if m.active else " [inactive]") for m in members]
        return Reply(text="*Members:*\n" + "\n".join(lines)
                          + "\n\n/rename <@who> <new name> - change the name "
                            "the team sees\n/adduser <number> <name> - add "
                            "someone")

    # ---- /board  (and admin-only /board preview) ----
    mb = re.match(r"^/(board|myboard)\b\s*(.*)$", body, re.IGNORECASE | re.DOTALL)
    if mb:
        rest = mb.group(2).strip()
        if rest.lower().startswith("preview"):
            if is_group:
                return Reply(unmatched=True)   # never rehearsed in groups
            if sender.role != "admin":
                return Reply(text="That's an admin command.")
            return _handle_board_preview(s, sender, rest[len("preview"):].strip())
        return _handle_my_board(s, sender)

    # ---- /myadd: open tasks I created ----
    if low.startswith("/myadd"):
        rows = (s.query(Task)
                 .filter(Task.creator_id == sender.id,
                         Task.status.in_(("open", "in_progress", "blocked")))
                 .all())
        rows = [t for t in sort_tasks(rows) if t.assignee_id != sender.id]
        if not rows:
            return Reply(text="No open tasks created by you for others.")
        lines = []
        for t in rows:
            due = f", due {t.due_date:%a %d %b}" if t.due_date else ""
            st_ = (f"BLOCKED {t.blocked_days}d: {t.blocker_reason}"
                   if t.status == "blocked" else t.status.replace("_", " "))
            lines.append(f"#{t.id} {t.title} -> {t.assignee.name} "
                         f"({st_}{due})")
        n = rows[0].id
        return Reply(text="*Tasks you created (open):*\n" + "\n".join(lines)
                          + f"\n\nReply:  {n} done  |  {n} cancel <reason>")
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
        return Reply(text=HELP_TEXT
                     + (ADMIN_HELP if sender.role == "admin" and not is_group
                        else ""))

    # ---- unmatched: ordinary conversation, not a command ----
    return Reply(text="I didn't understand that. Send /help for the command list.",
                 unmatched=True)

"""Broadcasts: scheduled plain messages, sent verbatim.

No headers, footers or numbering - the message text is exactly what arrives.
Pacing between recipients is deliberately slow (20-45 s) and all batches go
through the global send lock, so simultaneous broadcasts/digests queue
instead of bursting - ban-risk hygiene on a personal number.
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import get_setting, session_scope
from .models import Broadcast, Group, Member
from .waha import chat_id_for_phone, paced_send

log = logging.getLogger("broadcasts")

BCAST_MIN_GAP = 20   # seconds between recipients of a broadcast
BCAST_MAX_GAP = 45

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CRON_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def days_to_cron(days: list[int]) -> str:
    """[0, 2, 4] -> 'mon,wed,fri'. Empty/complete list -> every day ('*')."""
    days = sorted({d for d in days if 0 <= d <= 6})
    if not days or len(days) == 7:
        return "*"
    return ",".join(CRON_DAYS[d] for d in days)


def render_message(text: str, tzname: str = "UTC") -> str:
    """Replace {date} and {day} placeholders using the configured timezone."""
    try:
        now = datetime.now(ZoneInfo(tzname))
    except Exception:
        now = datetime.now()
    return (text.replace("{date}", now.strftime("%d %B %Y"))
                .replace("{day}", now.strftime("%A")))


def recipients_for(s, broadcast: Broadcast) -> list[str]:
    """Chat ids for a broadcast's members + groups (active ones only)."""
    out = []
    try:
        mids = json.loads(broadcast.member_ids or "[]")
        gids = json.loads(broadcast.group_ids or "[]")
    except ValueError:
        return []
    for mid in mids:
        m = s.get(Member, mid)
        if m and m.active:
            out.append(chat_id_for_phone(m.phone))
    for gid in gids:
        g = s.get(Group, gid)
        if g and g.active:
            out.append(g.chat_id)
    return out


def send_broadcast(broadcast_id: int):
    """Send one broadcast to all its recipients. Called by the scheduler or
    the dashboard's Send-now (as a background job)."""
    with session_scope() as s:
        b = s.get(Broadcast, broadcast_id)
        if b is None or not b.active:
            return
        tzname = get_setting(s, "timezone") or "UTC"
        text = render_message(b.message, tzname)
        targets = recipients_for(s, b)
        name = b.name
    if not targets:
        log.info("broadcast '%s': no active recipients, nothing sent", name)
        return
    log.info("broadcast '%s': sending to %d recipient(s)", name, len(targets))
    paced_send([(t, text) for t in targets],
               min_gap=BCAST_MIN_GAP, max_gap=BCAST_MAX_GAP)
    with session_scope() as s:
        b = s.get(Broadcast, broadcast_id)
        if b:
            b.last_sent = datetime.utcnow()

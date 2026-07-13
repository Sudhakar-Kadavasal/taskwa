"""Broadcasts: scheduled plain messages, sent verbatim.

No headers, footers or numbering - the message text is exactly what arrives.
Pacing between recipients is deliberately slow (20-45 s) and all batches go
through the global send lock, so simultaneous broadcasts/digests queue
instead of bursting - ban-risk hygiene on a personal number.
"""
import json
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import get_setting, session_scope
from .models import Broadcast, Group, Member
from .waha import chat_id_for_phone, gap_settings, paced_send

log = logging.getLogger("broadcasts")

BCAST_MIN_GAP = 20   # seconds between recipients of a broadcast
BCAST_MAX_GAP = 45

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CRON_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Shown at the top of the timezone dropdown; the full IANA list follows.
COMMON_TZS = [
    "Asia/Dubai", "Asia/Kolkata", "Asia/Riyadh", "Asia/Qatar", "Asia/Bahrain",
    "Asia/Kuwait", "Asia/Muscat", "Asia/Karachi", "Asia/Dhaka", "Asia/Colombo",
    "Asia/Singapore", "Asia/Hong_Kong", "Asia/Bangkok", "Asia/Jakarta",
    "Asia/Manila", "Asia/Tokyo", "Asia/Shanghai", "Europe/London",
    "Europe/Paris", "Europe/Berlin", "Europe/Zurich", "Europe/Istanbul",
    "Europe/Moscow", "Africa/Cairo", "Africa/Nairobi", "Africa/Johannesburg",
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Toronto", "America/Sao_Paulo",
    "Australia/Perth", "Australia/Sydney", "Pacific/Auckland", "UTC",
]


def valid_tz(name: str) -> bool:
    """True when `name` is a real IANA timezone."""
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def broadcast_tzname(b: Broadcast, fallback: str) -> str:
    """The timezone a broadcast runs in: its own pinned tz, else the
    dashboard setting, else UTC - never silently the container clock."""
    for cand in ((b.tz or "").strip(), (fallback or "").strip(), "UTC"):
        if valid_tz(cand):
            return cand
    return "UTC"


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
        tzname = broadcast_tzname(b, get_setting(s, "timezone"))
        text = render_message(b.message, tzname)
        targets = recipients_for(s, b)
        name = b.name
    if not targets:
        log.info("broadcast '%s': no active recipients, nothing sent", name)
        return
    # A nudge is the same text to many people - the most spam-shaped thing this
    # bot does. Shuffled order, and gaps at least as wide as a digest's.
    random.shuffle(targets)
    with session_scope() as s:
        lo, hi = gap_settings(s)
    if lo or hi:                       # 0/0 means dry-run: send back to back
        lo, hi = max(lo, BCAST_MIN_GAP), max(hi, BCAST_MAX_GAP)
    log.info("broadcast '%s': %d recipient(s), %g-%g s apart",
             name, len(targets), lo, hi)
    paced_send([(t, text) for t in targets], min_gap=lo, max_gap=hi)
    with session_scope() as s:
        b = s.get(Broadcast, broadcast_id)
        if b:
            b.last_sent = datetime.utcnow()

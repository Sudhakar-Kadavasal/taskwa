"""Thin client for the WAHA WhatsApp gateway (https://waha.devlike.pro).

All outbound traffic passes through send_text(), which honours dry-run mode,
logs every message, and enforces the hourly cap.
"""
import base64
import logging
import random
import time
from datetime import datetime, timedelta

import httpx

from .config import env
from .db import get_setting, session_scope
from .models import Group, Member, MessageLog

log = logging.getLogger("waha")


def _headers():
    h = {"Content-Type": "application/json"}
    if env.waha_api_key:
        h["X-Api-Key"] = env.waha_api_key
    return h


def _client():
    return httpx.Client(base_url=env.waha_url, headers=_headers(), timeout=30)


def chat_id_for_phone(phone: str) -> str:
    return f"{phone}@c.us"


# ---------------- session ----------------
def session_status() -> str:
    """Returns WAHA session status: WORKING, SCAN_QR_CODE, STARTING, STOPPED,
    FAILED... Every live check also refreshes the cached status that the
    dashboard banner reads, so all pages agree immediately."""
    try:
        with _client() as c:
            r = c.get(f"/api/sessions/{env.waha_session}")
            if r.status_code == 404:
                status = "NOT_STARTED"
            else:
                r.raise_for_status()
                status = r.json().get("status", "UNKNOWN")
    except Exception as e:  # gateway unreachable
        log.warning("session_status failed: %s", e)
        status = "UNREACHABLE"
    try:
        from .db import set_setting
        with session_scope() as s:
            set_setting(s, "gateway_status", status)
            set_setting(s, "gateway_status_at",
                        datetime.utcnow().isoformat(timespec="seconds"))
    except Exception:
        pass  # never let cache-writing break a status check
    return status


def start_session():
    with _client() as c:
        # newer WAHA
        r = c.post(f"/api/sessions/{env.waha_session}/start")
        if r.status_code < 300:
            return True
        # older WAHA
        r = c.post("/api/sessions/start", json={"name": env.waha_session})
        return r.status_code < 300


def qr_png() -> bytes | None:
    try:
        with _client() as c:
            r = c.get(f"/api/{env.waha_session}/auth/qr",
                      params={"format": "image"},
                      headers={**_headers(), "Accept": "image/png"})
            if r.status_code < 300:
                return r.content
    except Exception as e:
        log.warning("qr fetch failed: %s", e)
    return None


_me_cache: dict = {"id": None}


def me_chat_id() -> str | None:
    """The bot account's own chat id (e.g. 9715xxxx@c.us). Cached after first
    success. Needed in personal-number mode to recognise the owner's
    'Message Yourself' chat."""
    if _me_cache["id"]:
        return _me_cache["id"]
    try:
        with _client() as c:
            r = c.get(f"/api/sessions/{env.waha_session}")
            if r.status_code < 300:
                me = (r.json() or {}).get("me") or {}
                mid = me.get("id")
                if isinstance(mid, dict):
                    mid = mid.get("_serialized")
                if mid:
                    # strip device suffix like '9715...:12@c.us'
                    user = str(mid).split("@")[0].split(":")[0]
                    _me_cache["id"] = f"{user}@c.us"
    except Exception as e:
        log.warning("me_chat_id failed: %s", e)
    return _me_cache["id"]


_lid_cache: dict = {}


def lid_to_phone(lid: str) -> str | None:
    """Resolve a WhatsApp Linked ID (anonymous group participant id) to the
    real phone number via WAHA. Cached per process. Returns digits or None.
    Note: WAHA populates this mapping when groups are fetched (list_groups)."""
    lid = str(lid).split("@")[0]
    if lid in _lid_cache:
        return _lid_cache[lid]
    try:
        with _client() as c:
            r = c.get(f"/api/{env.waha_session}/lids/{lid}")
            if r.status_code < 300:
                pn = str((r.json() or {}).get("pn") or "")
                digits = "".join(ch for ch in pn.split("@")[0] if ch.isdigit())
                if digits:
                    _lid_cache[lid] = digits
                    return digits
    except Exception as e:
        log.warning("lid lookup failed for %s: %s", lid, e)
    return None


def list_groups() -> list[dict]:
    """All groups the bot's number belongs to: [{'chat_id':…, 'name':…}].
    Tries the dedicated groups endpoint, falls back to the chats list."""
    def _norm(items):
        out = []
        for g in items:
            if not isinstance(g, dict):
                continue
            gid = g.get("id")
            if isinstance(gid, dict):
                gid = gid.get("_serialized") or ""
            gid = str(gid or "")
            if not gid.endswith("@g.us"):
                continue
            name = (g.get("name") or g.get("subject")
                    or (g.get("groupMetadata") or {}).get("subject") or gid)
            out.append({"chat_id": gid, "name": str(name)})
        return out

    try:
        with httpx.Client(base_url=env.waha_url, headers=_headers(),
                          timeout=120) as c:
            r = c.get(f"/api/{env.waha_session}/groups")
            if r.status_code < 300 and isinstance(r.json(), list):
                return _norm(r.json())
            r = c.get(f"/api/{env.waha_session}/chats")
            if r.status_code < 300 and isinstance(r.json(), list):
                return _norm(r.json())
            log.warning("group detect failed: HTTP %s %s",
                        r.status_code, r.text[:200])
    except Exception as e:
        log.warning("group detect failed: %s", e)
    return []


def group_member_phones(chat_id: str) -> tuple[set, bool]:
    """Lightweight membership lookup: (set of resolved phone digits,
    all_resolved). No per-contact name fetches - fast enough to run inside
    a Y-confirmation. all_resolved=False means privacy-hidden participants
    exist, so absence from the set is NOT proof of absence from the group."""
    parts = _raw_participants(chat_id)
    phones = {p["phone"] for p in parts if p["phone"]}
    return phones, bool(parts) and len(phones) == len(parts)


def _raw_participants(chat_id: str) -> list[dict]:
    """Participant ids of a group, phones resolved where possible."""
    items = None
    try:
        with httpx.Client(base_url=env.waha_url, headers=_headers(),
                          timeout=120) as c:
            r = c.get(f"/api/{env.waha_session}/groups/{chat_id}/participants")
            if r.status_code < 300 and isinstance(r.json(), list):
                items = r.json()
            else:
                r = c.get(f"/api/{env.waha_session}/groups/{chat_id}")
                g = r.json() if r.status_code < 300 else {}
                items = (g.get("participants")
                         or (g.get("groupMetadata") or {}).get("participants")
                         or [])
    except Exception as e:
        log.warning("participants fetch failed for %s: %s", chat_id, e)
        return []
    out = []
    for pt in items or []:
        pid = pt.get("id") if isinstance(pt, dict) else pt
        if isinstance(pid, dict):
            pid = pid.get("_serialized") or ""
        pid = str(pid or "")
        user = pid.split("@")[0]
        phone, lid = "", ""
        if pid.endswith("@lid"):
            lid = user
            phone = lid_to_phone(user) or ""
        elif pid.endswith("@c.us"):
            phone = "".join(ch for ch in user if ch.isdigit())
        else:
            continue
        out.append({"phone": phone, "lid": lid, "name": "",
                    "resolved": bool(phone)})
    return out


def group_participants(chat_id: str) -> list[dict]:
    """Participants of a group, best-effort across WAHA versions:
    [{'phone': digits or '', 'lid': str, 'name': str, 'resolved': bool}]"""
    out = _raw_participants(chat_id)

    # names, best-effort (contact name, else the person's own pushname)
    try:
        with _client() as c:
            for pt in out[:60]:
                if not pt["phone"]:
                    continue
                r = c.get("/api/contacts",
                          params={"contactId": f"{pt['phone']}@c.us",
                                  "session": env.waha_session})
                if r.status_code < 300 and isinstance(r.json(), dict):
                    d = r.json()
                    pt["name"] = str(d.get("name") or d.get("pushname") or "")
    except Exception as e:
        log.info("participant name lookup skipped: %s", e)
    return out


# ---------------- outbound ----------------
def _hourly_count(s) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=1)
    return (s.query(MessageLog)
             .filter(MessageLog.status == "sent", MessageLog.created_at >= cutoff)
             .count())


def _allowed_recipient(s, chat_id: str) -> bool:
    """Hard allowlist: only active registered members and active registered
    groups may EVER receive a message. Everything else is refused here,
    regardless of which code path asked for the send."""
    if chat_id.endswith("@c.us"):
        phone = chat_id.split("@")[0]
        return (s.query(Member)
                 .filter(Member.phone == phone, Member.active.is_(True))
                 .count() > 0)
    if chat_id.endswith("@g.us"):
        return (s.query(Group)
                 .filter(Group.chat_id == chat_id, Group.active.is_(True))
                 .count() > 0)
    return False


def canonical_chat_id(chat_id: str) -> str:
    """Privacy-enabled WhatsApp accounts appear as anonymous …@lid addresses
    even in DMs. Rewrite to the member's canonical phone@c.us so the
    allowlist can vet them; an unresolvable lid passes through unchanged
    (and is then refused by the allowlist - never sent blind)."""
    if chat_id.endswith("@lid"):
        digits = lid_to_phone(chat_id)   # cached: inbound already resolved it
        if digits:
            return f"{digits}@c.us"
    return chat_id


def send_text(chat_id: str, text: str) -> bool:
    """Send a message (or log it in dry-run). Returns True on success.
    Refuses any recipient that is not a registered member or group."""
    chat_id = canonical_chat_id(chat_id)
    with session_scope() as s:
        if not _allowed_recipient(s, chat_id):
            s.add(MessageLog(chat_id=chat_id, text=text, status="blocked",
                             detail="recipient not a registered member/group - send refused"))
            log.warning("BLOCKED send to unregistered recipient %s", chat_id)
            return False
        if get_setting(s, "dry_run"):
            s.add(MessageLog(chat_id=chat_id, text=text, status="dryrun"))
            log.info("[DRY-RUN] -> %s: %s", chat_id, text[:80])
            return True
        cap = int(get_setting(s, "hourly_cap") or 60)
        if _hourly_count(s) >= cap:
            s.add(MessageLog(chat_id=chat_id, text=text, status="failed",
                             detail="hourly cap reached"))
            log.warning("hourly cap reached; message to %s not sent", chat_id)
            return False
    _throttle()     # never two messages within a few seconds of each other
    try:
        with _client() as c:
            r = c.post("/api/sendText", json={
                "session": env.waha_session, "chatId": chat_id, "text": text})
            ok = r.status_code < 300
            detail = "" if ok else f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        ok, detail = False, str(e)
    with session_scope() as s:
        s.add(MessageLog(chat_id=chat_id, text=text,
                         status="sent" if ok else "failed", detail=detail))
    if not ok:
        log.error("send failed -> %s: %s", chat_id, detail)
    return ok


def send_image(chat_id: str, png: bytes, caption: str = "") -> bool:
    """Send a PNG image (or log it in dry-run). Returns True on success.

    Mirrors send_text guard-for-guard - canonical_chat_id -> allowlist ->
    dry-run -> hourly cap -> throttle - so an image can NEVER reach anyone a
    text message could not, and every send is still logged and rate-limited.
    Endpoint/payload verified against WAHA 2026.7.1 (WEBJS/CORE): POST
    /api/sendImage with file.data as base64 (the engine atob()s it)."""
    chat_id = canonical_chat_id(chat_id)
    with session_scope() as s:
        if not _allowed_recipient(s, chat_id):
            s.add(MessageLog(chat_id=chat_id, text="[image]", status="blocked",
                             detail="recipient not a registered member/group - send refused"))
            log.warning("BLOCKED image send to unregistered recipient %s", chat_id)
            return False
        if get_setting(s, "dry_run"):
            s.add(MessageLog(chat_id=chat_id, text=f"[image] {caption}".strip(),
                             status="dryrun"))
            log.info("[DRY-RUN] image -> %s: %s", chat_id, caption[:80])
            return True
        cap = int(get_setting(s, "hourly_cap") or 60)
        if _hourly_count(s) >= cap:
            s.add(MessageLog(chat_id=chat_id, text="[image]", status="failed",
                             detail="hourly cap reached"))
            log.warning("hourly cap reached; image to %s not sent", chat_id)
            return False
    _throttle()     # never two messages within a few seconds of each other
    b64 = base64.b64encode(png).decode()
    try:
        with _client() as c:
            r = c.post("/api/sendImage", json={
                "session": env.waha_session, "chatId": chat_id,
                "file": {"mimetype": "image/png", "filename": "board.png",
                         "data": b64},
                "caption": caption})
            ok = r.status_code < 300
            detail = "" if ok else f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        ok, detail = False, str(e)
    with session_scope() as s:
        s.add(MessageLog(chat_id=chat_id, text=f"[image] {caption}".strip(),
                         status="sent" if ok else "failed", detail=detail))
    if not ok:
        log.error("image send failed -> %s: %s", chat_id, detail)
    return ok


def send_reaction(message_id: str, reaction: str = "\U0001F44D") -> bool:
    """React to a message (used as a silent acknowledgment). No-op in dry-run."""
    with session_scope() as s:
        if get_setting(s, "dry_run"):
            log.info("[DRY-RUN] reaction %s -> %s", reaction, message_id)
            return True
    try:
        with _client() as c:
            r = c.put("/api/reaction", json={
                "session": env.waha_session,
                "messageId": message_id,
                "reaction": reaction})
            return r.status_code < 300
    except Exception as e:
        log.warning("reaction failed: %s", e)
        return False


def plan_gaps(n: int, min_gap: float, max_gap: float,
              rnd: random.Random | None = None) -> list[float]:
    """The n-1 gaps between n messages: each a fresh random value in
    [min_gap, max_gap]. Pure and testable - no sleeping.

    A gap rule rather than a fixed window on purpose: a window would silently
    compress the spacing as the team grows (30 people in 15 minutes = 30 s
    apart), which is exactly backwards - a bigger fan-out is the riskier one.
    Constant gaps mean a bigger run simply takes longer."""
    rnd = rnd or random
    if n <= 1:
        return []
    lo, hi = min(min_gap, max_gap), max(min_gap, max_gap)
    return [rnd.uniform(lo, hi) for _ in range(n - 1)]


def gap_settings(s) -> tuple[float, float]:
    """(min, max) seconds between two messages of a run. Dry-run rehearsals
    get no gaps at all - they must finish now, not in ten minutes."""
    if get_setting(s, "dry_run"):
        return 0.0, 0.0
    lo = float(get_setting(s, "min_gap_seconds") or 15)
    hi = float(get_setting(s, "max_gap_seconds") or 30)
    return min(lo, hi), max(lo, hi)


# --- global send throttle -------------------------------------------------
# THE ban-risk primitive. Every outbound message - digest, nudge, admin alert,
# an interactive reply from the webhook - passes through send_text, so the
# floor is enforced here rather than in each caller. Two messages can never
# leave within MIN_INTERVAL seconds of each other, no matter which code path
# asked. A lone reply waits ~0s (nothing was sent recently); a burst is
# stretched out automatically.
MIN_INTERVAL = 3.0      # seconds, hard floor between ANY two sends
MAX_INTERVAL = 8.0      # upper end of the randomised floor
_throttle_lock = None
_last_send_at = [0.0]   # list, so the closure can rebind without `global`


def _get_throttle_lock():
    global _throttle_lock
    if _throttle_lock is None:
        import threading
        _throttle_lock = threading.Lock()
    return _throttle_lock


def _throttle():
    """Block until MIN_INTERVAL..MAX_INTERVAL seconds have passed since the
    last send anywhere in the process."""
    with _get_throttle_lock():
        need = random.uniform(MIN_INTERVAL, MAX_INTERVAL)
        wait = need - (time.monotonic() - _last_send_at[0])
        if wait > 0:
            time.sleep(wait)
        _last_send_at[0] = time.monotonic()


def paced_send(messages: list[tuple[str, str]], min_gap: float = 15,
               max_gap: float = 30):
    """Send a batch, one message every min_gap..max_gap seconds.

    Deliberately NOT holding a lock for the whole batch: a long digest run
    would otherwise queue an urgent blocker alert behind it. Batches may
    interleave; the throttle inside send_text still guarantees that no two
    messages leave together."""
    gaps = plan_gaps(len(messages), min_gap, max_gap)
    for i, (chat_id, text) in enumerate(messages):
        send_text(chat_id, text)
        if i < len(messages) - 1:
            # send_text's throttle already spent a few seconds of the gap
            time.sleep(max(0.0, gaps[i] - MIN_INTERVAL))

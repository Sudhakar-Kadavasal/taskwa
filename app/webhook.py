"""Inbound webhook from the WAHA gateway.

Reply policy:
- Unregistered senders: always silent (logged only).
- Unmatched (non-command) messages: silent in groups always; silent in DMs
  when personal-number mode is on. The bot never intrudes on human chat.
- Recognised commands always get their normal handling (ack / error reply).
- fromMe events: ignored normally. In personal-number mode, the owner's
  'Message Yourself' chat is treated as inbound so the owner can reply to
  their own digests; the owner's outgoing messages to OTHER chats are never
  processed.
- The app never calls WAHA's mark-as-read API: nothing is ever marked read.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from .commands import handle_message
from .config import env
from .db import get_setting, session_scope
from .digest import alert_admins
from .engine import member_by_phone
from .models import Group, Member, ProcessedMessage
from .waha import lid_to_phone, list_groups, me_chat_id, send_reaction, send_text

log = logging.getLogger("webhook")
router = APIRouter()


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    if request.query_params.get("token") != env.webhook_secret:
        return JSONResponse({"error": "bad token"}, status_code=403)
    data = await request.json()
    if data.get("event") not in ("message", "message.any"):
        return {"ok": True}
    payload = data.get("payload") or {}
    msg_id = str(payload.get("id") or "")
    chat = str(payload.get("from") or "")
    body = payload.get("body") or ""
    # In group chats 'from' is the group id and 'participant' is the sender.
    sender_addr = str(payload.get("participant") or chat)
    # quoted (swipe) reply, if any - WAHA exposes it as replyTo or _data.quotedMsg
    rt = payload.get("replyTo") or {}
    quoted = rt.get("body") if isinstance(rt, dict) else ""
    if not quoted:
        quoted = (((payload.get("_data") or {}).get("quotedMsg") or {})
                  .get("body") or "")
    phone = sender_addr.split("@")[0]
    is_group = chat.endswith("@g.us")
    log.info("webhook: chat=%s fromMe=%s group=%s sender=%s body=%r",
             chat, bool(payload.get("fromMe")), is_group, sender_addr, body[:40])

    # Newer WhatsApp accounts appear in groups as anonymous Linked IDs
    # (…@lid) instead of phone numbers - resolve via the gateway.
    if sender_addr.endswith("@lid") and not payload.get("fromMe"):
        mapped = lid_to_phone(sender_addr)
        if mapped:
            phone = mapped
            log.info("lid %s resolved to %s", sender_addr, phone)
        else:
            log.warning("unresolved lid %s - warming group mapping for next time",
                        sender_addr)
            background.add_task(list_groups)
            return {"ok": True}

    with session_scope() as s:
        personal = bool(get_setting(s, "personal_mode"))
        ack_mode = get_setting(s, "ack_mode")

        if payload.get("fromMe"):
            if not personal:
                return {"ok": True}
            # Personal mode: the owner's own messages count as inbound in the
            # "Message Yourself" chat and in REGISTERED groups (checked just
            # below). Outgoing messages to any other chat are the owner's
            # private conversations - never processed.
            me = me_chat_id()
            if not me:
                log.warning("fromMe dropped: could not resolve own chat id")
                return {"ok": True}
            if chat == me:
                phone = me.split("@")[0]
                is_group = False
            elif is_group:
                phone = me.split("@")[0]   # owner speaking in a group
            else:
                log.info("fromMe dropped: private chat %s (me=%s)", chat, me)
                return {"ok": True}

        # groups: only registered, active groups are listened to at all
        group_id = None
        if is_group:
            g = (s.query(Group)
                  .filter(Group.chat_id == chat, Group.active.is_(True))
                  .first())
            if g is None:
                log.info("ignored message in unregistered group %s", chat)
                return {"ok": True}
            group_id = g.id

        # idempotency (FR-20)
        if msg_id:
            if s.get(ProcessedMessage, msg_id):
                return {"ok": True}
            s.add(ProcessedMessage(message_id=msg_id))

        sender = member_by_phone(s, phone)
        if sender is None:
            log.info("silently ignored message from unregistered %s (group=%s)",
                     phone, is_group)
            return {"ok": True}

        # media / non-text: only hint in a DM on a dedicated bot number
        if not body.strip():
            if not is_group and not personal:
                background.add_task(
                    send_text, chat,
                    "I can only read text messages. Send /help for commands.")
            return {"ok": True}

        admin = (s.query(Member)
                  .filter(Member.role == "admin", Member.active.is_(True))
                  .first())
        reply = handle_message(s, sender, body, admin,
                               is_group=is_group, quoted=quoted,
                               group_id=group_id)

    # Non-command chatter: stay out of the conversation.
    suppress_text = reply.unmatched and (is_group or personal)

    if reply.react and msg_id and ack_mode == "reaction":
        background.add_task(send_reaction, msg_id)
    elif reply.react and ack_mode == "reply":
        background.add_task(send_text, chat, "Noted.")
    if reply.text and not suppress_text:
        background.add_task(send_text, chat, reply.text)
    if reply.alert_admin:
        background.add_task(alert_admins, reply.alert_admin)
    return {"ok": True}

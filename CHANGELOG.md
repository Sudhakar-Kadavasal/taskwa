# Changelog

## v1.3.1 — 2026-07-11

- Cold-boot catch-up: if the machine was fully powered off at a scheduled
  digest time, the missed digest is sent ~2 minutes after startup, provided
  the slot is less than 6 hours old. Guarded by the last-send record, so an
  already-delivered digest is never repeated. (Sleep/wake catch-up within the
  same window already worked; this extends it to full shutdowns.)

## v1.3.0 — 2026-07-10

- /add sent inside a registered group now auto-flags the task to post to that
  group's digest, and native WhatsApp @-mentions (which arrive as @<number>)
  resolve to registered members - typed @Name still works.

- LID support: group participants on newer WhatsApp accounts arrive as
  anonymous Linked IDs (…@lid) instead of phone numbers; these are now
  resolved to real numbers via the gateway (cached), and the mapping is
  auto-warmed whenever the session reaches WORKING.

- Group digests now use the same numbered format and reply footer as personal
  digests (1., 2., 3. + "Reply: 1 done | ..."); numbers resolve against that
  group's own digest, so replying in the group just works.
- Tasks posted to a group are no longer repeated in the assignee's personal
  DM digest — each task is announced exactly once. /mytasks still shows all.
- Personal-number mode: gateway now subscribes to message.any so the owner's
  own replies (self-chat and registered groups) are actually delivered —
  previously they never reached the app.

## v1.2.0 — 2026-07-10

- Digests now show simple numbers (1., 2., 3.) per member instead of #serials;
  replies use those numbers: `1 done`, `1 block <reason>`. Serials still work.
- `block` accepted as alias of `blocker`; `1. done` and `1) done` also parse.
- Bare `done` / `block <reason>` applies automatically when the member has
  exactly one open task.
- Quoted (swipe) replies: replying "done" on a bot message that names one task
  resolves the task from the quote. Quoting a multi-task digest asks for the
  number.
- With several open tasks, a bare "done" gets a which-one prompt on dedicated
  bot numbers; stays silent in groups and personal mode to avoid false hits on
  conversation.

## v1.1.0 — 2026-07-10

- **Personal number mode**: run the bot on the owner's own WhatsApp number.
  Non-command messages are ignored silently everywhere, the owner's outgoing
  messages are never processed, and the owner replies to digests in the
  "Message Yourself" chat.
- Group chatter fix: unmatched messages in groups no longer trigger a help
  reply (previously any group conversation did).
- Unregistered senders are now ignored fully silently (no rejection message).
- "Detect my groups" button on the Groups page — one-click group registration,
  replaces the manual chat-ID lookup.
- ARM (Apple Silicon / Raspberry Pi) gateway support via `WAHA_TAG=arm`.
- **Outbound allowlist guard**: sends to anyone who is not an active registered
  member or group are refused at the gateway-client layer and logged as
  `blocked`. Messages in unregistered groups are ignored entirely.

## v1.0.0 — 2026-07-10

Initial release.

- Daily WhatsApp digest per member (one message, priority-sorted), configurable
  send times and timezone
- Optional per-task group posting for public accountability
- Status protocol over WhatsApp: `12 done`, `12 in progress`,
  `12 blocker <reason>`, `12 reopen` — reaction acknowledgments,
  assignee/admin permission guard, immutable audit trail
- Structured task creation: `/add <title> @Name [!high|!low] [fri|25/07]`
  with Y/N confirmation; `/mytasks`, `/list`, `/help`
- Blocker replies alert all admins immediately; blocked tasks shown with
  reason and age in every digest
- Admin dashboard: setup wizard, QR pairing, task board, members, groups,
  settings, health page with outbound message log
- Password reset via WhatsApp code (CLI fallback)
- Nightly SQLite backups (14 kept), 30-day archive-then-purge of completed
  tasks, CSV exports
- Dry-run mode (default on), hourly send cap, human-like send pacing
- Docker Compose packaging with WAHA gateway; optional Caddy (HTTPS) and
  Ollama (future v2 AI) profiles

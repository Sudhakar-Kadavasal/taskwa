# Changelog

## v1.6.4 — 2026-07-13

- **Admin commands over WhatsApp (DM the bot only, Y/N confirmed, no AI —
  fixed grammar):** `/nudge [HH:MM] [days] [@Name] [#group] <message>`
  creates a nudge from the phone; `/nudges` lists them; `/nudge <n> <time/
  days/recipients>` reschedules (text changes = delete & recreate);
  `/nudge on|off <n>` pauses/resumes instantly; `/nudge delete <n>` asks
  Y/N. `/adduser <number> <name>` registers a member (always role member —
  promotion stays dashboard-only; re-adding an inactive number reactivates
  it); `/members` lists everyone. Non-admins are refused; groups get
  silence.
- **`/add` gains a `#group` tag** (DM-created tasks): `#site` matches a
  registered group by unique substring (dots = spaces), the task posts to
  that group, and on Y the bot announces it there — "New task for Ravi: …"
  with reply numbers — so the creator immediately sees it reached the right
  place. The creator must be a member of that group (verified against the
  live participant list; admins exempt; unverifiable = refused, never
  guessed).
- **`/myadd`** — every open task you created for others, with status,
  block age and your close/cancel powers. **`/help` is now role-aware**:
  members see member commands; admins DM'ing the bot get the admin set too.
- **Members page: change a member's role** with a per-row dropdown (saves on
  selection). Promotion to admin remains dashboard-only by design, and the
  last active admin cannot be demoted — promote a successor first.
- **Broadcasts is now the Nudger** (dashboard nav, page and labels renamed;
  routes and internals unchanged): plain messages, sent exactly as typed —
  no numbering, no reply footer: polite nudging without seeming like an
  assigned task.
- **User Manual: new administrator walkthrough** — the Tasks page
  (one-click Done/Cancel, Set-with-note, edit, create, exports) documented
  page by page, plus a **Troubleshooting — restart cookbook** section:
  restarting the gateway/app/stack/Docker, fixing 'docker: command not
  found' after an engine switch, verifying the autostart is armed, and
  reading the logs. Installation Guide gained the same cookbook and
  autostart checks in its troubleshooting section. Manual is now 7 pages.

## v1.6.3 — 2026-07-11

- **Assignees are now notified the moment a task is created for them**
  (via /add or the dashboard): "New task from Sk: … Reply Y to accept,
  N to decline (no reply in 30 min counts as accepted)", plus reply
  instructions using the task's serial number. **Silence auto-accepts
  after 30 minutes** — recorded in the audit trail as "auto-accepted",
  distinct from an explicit Y.
- **Hotfix (found in live testing): a stale expired confirmation row
  crashed task creation** with a UNIQUE-constraint error, rolling back the
  task and sending nothing — and the crash made the gateway re-deliver the
  message every few seconds (retry storm). Stale rows are now replaced,
  and the webhook acknowledges even on internal errors so a bug can never
  trigger gateway retries again.
  Accepting is recorded in the audit trail; **declining returns the task
  to the person who created it** (or an admin if the creator is gone) —
  work never dies silently. The initiator gets one DM; no duplicate admin
  alert. Group-posted tasks skip the DM (their group's daily digest
  announces them).
- **Dashboard: one-click Done / Cancel buttons** on every open task row
  (Cancel asks for confirmation), alongside the existing status dropdown.
  Failed status changes now show a red banner explaining why, instead of
  silently doing nothing. Dashboard done/cancel also notifies the assignee
  (one message, group or DM — admins closing their own tasks are not
  messaged).
- **Creators can close or cancel their own tasks**: whoever created a task
  can send "7 done" or "7 cancel <reason>" (new verb) even if it's assigned
  to someone else — the assignee gets one notice that it's off their list.
  Creators get exactly these two powers, nothing else; cancelling is
  reserved for the creator and admins (an assignee's way out is declining,
  not killing the task later). The dashboard already allowed both for the
  admin. The /add receipt now reminds creators: "You created it, so you can
  also: 7 done | 7 cancel".
- **Blocks can now wait on a person**: "3 block waiting on @Priya" hands
  the block to Priya — she gets one message (in the task's group if it has
  one, else a DM) with "Reply: 3 unblock — when your part is done, or if
  there's no block on your side." Her "3 unblock" flips the task back to
  in-progress and tells the assignee it's back on them. She can release
  the block but cannot close someone else's task. Digests show "BLOCKED
  2d, waiting on Priya", and her own digest gains a "Waiting on you"
  section for non-group tasks (group ones live in the group digest —
  never both).
- **Fix: the "Created task #N" receipt was a dead end.** It now ends with
  "Reply: N done | N in progress | N block <reason>" when you assign to
  yourself, or tells you the assignee has been asked to accept / that the
  task will appear in the group's daily list.
- **Fix: members on privacy-enabled WhatsApp accounts never received
  replies.** Their DMs arrive from an anonymous …@lid address; inbound
  commands were understood (v1.5 lid resolution) but the reply went back to
  the raw @lid id, which the outbound allowlist refused ("blocked" in the
  message log). Recipient ids are now canonicalised to phone@c.us at the
  send_text choke point, so registered members get replies regardless of
  addressing — while lids that resolve to strangers (or don't resolve)
  remain blocked. /add, Y/N confirms and all commands now work for every
  registered member, not just those with classic @c.us addressing.

## v1.6.2 — 2026-07-11

- **Per-broadcast time zone**: each broadcast now has its own timezone
  dropdown next to the send time (common zones first, full IANA list below),
  defaulting to the dashboard timezone and **pinned at save time** — changing
  the dashboard timezone later never silently moves an existing broadcast.
  {date}/{day} placeholders render in the broadcast's own zone. Existing
  broadcasts are stamped with the dashboard timezone on first startup.
- **Fix**: saving the Settings page reloaded only digest jobs — broadcast
  schedules kept the old timezone until a restart. Both now reload.
- **Fix**: an invalid timezone no longer silently falls back to the container
  clock (UTC); resolution is broadcast tz → dashboard tz → explicit UTC,
  with a logged error for bad schedules.

## v1.6.1 — 2026-07-11

- Unattended operation: one-command autostart installers for macOS
  (LaunchAgent), Windows (Scheduled Task) and Linux (systemd) that start
  Docker, wait for the engine, and bring the stack up at every login/boot —
  including the "containers were stopped when Docker last quit" case that
  restart policies alone don't cover. New docs/UNATTENDED.md explains the
  full restart chain (auto power-on, auto-login, Docker, containers).

## v1.6.0 — 2026-07-11

- **Broadcasts**: send your own plain WhatsApp messages to chosen members and
  groups — verbatim text, no numbering, headers or reply footers. Each
  broadcast has its own send time and days of the week (or manual-only with a
  Send-now button), an active/paused switch, and {date} / {day} placeholders.
- Ban-risk pacing hardened: broadcast recipients are spaced 20–45 s apart,
  and a global send lock serialises simultaneous batches (broadcast + digest
  at the same minute queue instead of bursting).
- Missed broadcasts are deliberately NOT sent late — a "good morning" at 3 PM
  is worse than none. (Task digests keep their 6-hour catch-up.)

## v1.5.0 — 2026-07-11

- **Import members from a group**: Members page can now pull any registered
  group's participant list from the gateway — tick the teammates, edit their
  names (mentions match on these), pick roles, import. Deduplicates against
  existing members; anonymous-ID participants are resolved to real numbers
  where WhatsApp allows; hidden numbers are flagged with the fix (save as
  contact or make the bot a group admin). Importing never messages anyone.

## v1.4.0 — 2026-07-11

- Brand finalised as **TaskWA**; official Mint Ledger document set and flyer
  shipped in docs/.
- Dashboard restyled to the Mint Ledger theme (mint paper, emerald primary,
  cream/amber notices) to match the brand.
- docs/AI-INSTALL-PROMPT.txt: a paste-ready prompt that turns any AI
  assistant into a step-by-step installation guide, as referenced on the
  flyer.

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

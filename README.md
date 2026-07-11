# TaskWA — task reminders over WhatsApp

A self-hosted daily task reminder system for small teams, run entirely over
WhatsApp. Every morning it DMs each team member one digest of their open tasks.
They reply with a serial number and a keyword — the system updates itself.

```
Good morning, Ravi - 3 open tasks today:

  1. [HIGH] Send Q2 invoice to Alpha LLC  - due Fri 17 Jul
  2. Buy cement for Site B  - due today
  [!] 3. Fix generator - BLOCKED 3d: waiting on supplier quote

Reply:  1 done  |  1 in progress  |  1 block <reason>
```

**Zero per-message cost. Zero per-token cost. Your hardware, your data.**

> **Honest notice:** this project uses an *unofficial* WhatsApp gateway
> ([WAHA](https://waha.devlike.pro)). Numbers can be banned. **Use a dedicated SIM/number, never your
> personal one.** The official Meta API is not used because it cannot send to
> groups and charges per message.

## What you need

- A **dedicated WhatsApp number** (fresh SIM/eSIM) and a phone to scan a QR once
- **Docker** ([Docker Desktop](https://docs.docker.com/get-docker/) on
  Windows/macOS, Docker Engine on Linux)
- An always-on machine (spare PC, home server, office desktop) — or a small
  VPS (see `docs/VPS.md`)

Windows note: Docker Desktop needs WSL2 and hardware virtualization enabled.
Laptop note: disable sleep, or the 08:00 digest never leaves the lid.

## Install (about 15 minutes)

```bash
git clone https://github.com/sudhakar-kadavasal/taskwa.git
cd taskwa
cp .env.example .env        # then edit .env: set the two secrets
docker compose up -d
```

Open **http://localhost:3000** — the setup wizard walks you through:

1. Set the admin password
2. Scan the QR with the dedicated number's phone (WhatsApp → Linked devices)
3. Set timezone and daily send time(s)
4. Add team members (name + WhatsApp number), yourself as **admin**
5. Send a test message, finish

The system starts in **dry-run mode**: every message is logged on the Health
page instead of being sent. Flip it off in Settings when you're ready.

## Commands your team uses

| Send | Effect |
|---|---|
| `1 done` | close task 1 from your digest (bot reacts 👍) |
| `1 in progress` | mark started |
| `1 block waiting on quote` | blocked + reason; admin alerted instantly |
| `1 reopen` | undo a mistaken done |
| `done` / `block <reason>` | no number needed if you have one open task, or swipe-reply on a task message |
| `/add Buy cement @Ravi fri !high` | create a task (bot asks Y/N to confirm) |
| `/mytasks` | your open tasks, on demand |
| `/list` | all open tasks (admins see everyone's) |
| `/help` | command reference |

Only the assignee or an admin can change a task's status. Serial numbers are
global and never reused.

## Groups

Add the bot's number to a WhatsApp group, click "Detect my groups" on the
Groups page, then flag any task "post to group". Group tasks appear in one
daily group summary — numbered like personal digests, with the same reply
footer — and are not repeated in the assignee's DM. Replies in the group
(`1 done`) resolve against the group's own numbers; only the assignee or an
admin can update a task.

## Using your personal number instead of a dedicated SIM

Not recommended, but supported. Turn on **Personal number mode** in Settings.
The bot then never interferes with your normal WhatsApp life:

- Anything that isn't a recognised command gets **no reply at all** — no help
  hints, no "I can only read text" — in DMs and groups alike.
- Your outgoing personal messages are never processed.
- Nothing is ever marked as read (true in both modes — the app never calls the
  read-receipt API).
- Your own daily digest arrives in your **"Message Yourself"** chat, and you
  reply to it there (`12 done` works as usual).

**Understand the trade-off:** the gateway ToS risk now applies to your
personal account. A ban would cost you your own WhatsApp, not a spare SIM.

## Operations

- **Health page** — gateway session status, re-pair QR, outbound message log.
  A dropped session shows a red banner on every page; optional e-mail /
  healthchecks.io alerts via `.env`.
- **Backups** — nightly SQLite snapshot to `./backups` (14 kept). Completed
  tasks are archived to `backups/archive.csv` and purged after 30 days
  (configurable).
- **Password reset** — "Forgot password" sends a 6-digit code to the admin's
  WhatsApp. If the gateway itself is down:
  `docker compose exec app python -m app.cli reset-password`
- **Upgrade** — `git pull && docker compose up -d --build`
- **Test digests any time** — Health → "Run digests now" (respects dry-run).

## Roadmap

- **v1.1** — recurring tasks, overdue escalation, weekly admin summary, quiet hours
- **v2.0** — AI task creation from free-text WhatsApp messages via a local LLM
  (Ollama profile is already in `docker-compose.yml`), optional cloud API key

## More documentation

| Document | For |
|---|---|
| `INSTALL.txt` | Copy-paste installation, every platform |
| `docs/TaskWA-Installation-Guide.pdf` | Illustrated step-by-step install |
| `docs/TaskWA-User-Manual.pdf` | Team members (2 pages) + administrators |
| `docs/TaskWA-Command-Card.pdf` | One-page cheat sheet — pin it in the group |
| `docs/TROUBLESHOOTING.md` | Known issues and fixes |
| `docs/UPGRADE.md` · `docs/BACKUP.md` | Upgrades, backups, restore, uninstall |
| `docs/SECURITY.md` · `docs/VPS.md` | Security model, VPS deployment |

## License

MIT — see `LICENSE`.

# Security notes

## Outbound guarantee
Every outgoing message passes through a single choke point that enforces a
hard allowlist: only **active registered members** (their exact numbers) and
**active registered groups** can ever receive anything. Any other recipient is
refused before reaching the gateway and logged as `blocked` on the Health
page. Inbound is equally strict: unregistered senders and unregistered groups
are ignored silently. The one inherent exception: a message posted to a
registered group is visible to everyone in that group, member or not - that
is what registering a group means.

## Model
- The dashboard is bound to `127.0.0.1` by default — reachable only from the
  host machine. Nothing is exposed to the internet unless you enable Caddy.
- Team member identity = WhatsApp phone number. Only registered, active
  numbers are processed; only the assignee or an admin can change a task.
- The gateway calls the app webhook with a shared secret (`WEBHOOK_SECRET`).
- Admin sessions are signed cookies (12 h expiry). Passwords are bcrypt-hashed.
- Password reset codes go to admin WhatsApp numbers, are single-use, and expire
  in 10 minutes. CLI reset exists as the offline fallback.

## Your responsibilities
- Change **both** secrets in `.env` before first run.
- Set `WAHA_API_KEY` so the gateway API (port 3001) isn't open on the host.
- The SQLite database contains names, phone numbers and task content —
  personal data. `./data` and `./backups` are on your disk; protect the machine.
- On a VPS, **never** expose port 8000/3000 directly — use the Caddy profile
  (HTTPS) and a firewall. See `docs/VPS.md`.
- Team members should be told they're being messaged by an automated system.

## Out of scope (v1)
- Multi-admin accounts with separate logins (single admin password).
- End-to-end encrypted storage. WhatsApp transport is E2E; the local DB is not
  encrypted at rest.

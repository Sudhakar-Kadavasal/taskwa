# Troubleshooting

## "no matching manifest for linux/arm64" on `docker compose up`
You're on an ARM machine (Apple Silicon Mac, Raspberry Pi). WAHA's `latest`
image is amd64-only. Add `WAHA_TAG=arm` to your `.env`, then re-run
`docker compose up -d`.

## The QR code never appears
- Wait ~20 s after `docker compose up -d`; WAHA is slow to boot the first time.
- Click "Start / restart session" on the setup or Health page, wait 10 s, refresh.
- Check gateway logs: `docker compose logs waha --tail 50`

## Session says FAILED or STOPPED
Usually just a crashed gateway engine — the WhatsApp pairing on disk is still
valid. On the Health page click **Restart gateway session** — it restarts the
WhatsApp session with no QR, tasks and history untouched, and fixes most
FAILED/STOPPED cases and stuck sends. Recovery is deliberately **manual** (a
click, never automatic), because repeatedly restarting a personal number is
itself a ban signal. If the button doesn't recover it, restart the container:
`docker compose restart waha`.

## Session says SCAN_QR_CODE (or a QR appears after a restart)
WhatsApp logged the linked device out — a restart cannot fix this, only a fresh
scan can. Health page → **Re-pair (new QR)** → scan with the dedicated number's
phone (WhatsApp → Linked devices). A QR appearing right after you pressed
*Restart (no re-pair)* is the tell that this — not a crash — is what happened.
Tasks and history are unaffected.

If you are re-scanning every few days the number keeps getting logged out
(not crashing). Usual causes: the phone went offline too long, the bot's number
is open in WhatsApp Web/Desktop on another device, or the host is low on memory
and the WEBJS engine (headless Chromium) is being killed. Keep the phone online,
keep the number off other WhatsApp Web sessions, and on an 8 GB machine watch
`docker stats waha` during a failure.

## Messages aren't arriving
1. Is **dry-run** on? (yellow banner, Settings page). Dry-run logs instead of sending.
2. Health page: is the session `WORKING`?
3. Message log on the Health page: `failed` rows show the exact gateway error.
4. Hourly cap reached? Raise it in Settings if you have a bigger team.

## Replies from the team do nothing
- Is the sender **registered** (Members page) with the exact number they message
  from (country code, digits only)?
- Unregistered numbers are ignored **silently** — by design, the bot never
  reveals itself to numbers the admin hasn't registered. Attempts appear in
  `docker compose logs app` as "silently ignored".
- Check `docker compose logs app --tail 50` for webhook activity. If there is
  none, the gateway webhook URL/secret may not match your `.env`
  (`WEBHOOK_SECRET`). Re-run `docker compose up -d` after changing `.env`.

## "Detect my groups" finds nothing
- The gateway session must be `WORKING` (Health page).
- The bot's number must already be **added to the group** by a group admin.
- Newly joined groups can take a minute to appear; retry once.

## Locked out of the dashboard
- "Forgot password" on the login page sends a code to the admin's WhatsApp.
- Gateway also down? `docker compose exec app python -m app.cli reset-password`

## Laptop hosts: digests stop when the lid closes
- macOS: System Settings → Battery → prevent sleeping when plugged in
  (or `sudo pmset -c sleep 0 disablesleep 1`).
- Windows: Power settings → never sleep when plugged in; set Docker Desktop to
  start at login.
- A digest missed by less than 6 hours is sent when the machine wakes.

## Health alert emails never arrive
The gateway-down and re-pair alerts only send if SMTP is configured in `.env`
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL`). Without those, the
status still shows on the Health page but nothing is emailed. `HEALTHCHECKS_URL`
is a separate, optional dead-man's-switch ping for WORKING.

## Sending feels slow
By design. Every message passes a 3–8 s throttle, runs of messages are spaced
15–30 s apart, and scheduled starts carry ±6 min of jitter — deliberate pacing
so the unofficial gateway doesn't trip WhatsApp's spam heuristics. A 12-person
digest taking 4–6 minutes is normal, not a fault. Urgent blocker alerts skip
the gap.

## The number got banned
The accepted risk of unofficial gateways. Your data is intact. Get a new SIM,
update nothing in the app, pair the new number via the QR flow, and consider
lowering send volume (Settings → hourly cap).

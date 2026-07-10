# Troubleshooting

## "no matching manifest for linux/arm64" on `docker compose up`
You're on an ARM machine (Apple Silicon Mac, Raspberry Pi). WAHA's `latest`
image is amd64-only. Add `WAHA_TAG=arm` to your `.env`, then re-run
`docker compose up -d`.

## The QR code never appears
- Wait ~20 s after `docker compose up -d`; WAHA is slow to boot the first time.
- Click "Start / restart session" on the setup or Health page, wait 10 s, refresh.
- Check gateway logs: `docker compose logs waha --tail 50`

## Session says SCAN_QR_CODE / STOPPED / FAILED
The WhatsApp pairing dropped. Health page → Start session → scan the QR again
with the dedicated number's phone. Tasks and history are unaffected.

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

## The number got banned
The accepted risk of unofficial gateways. Your data is intact. Get a new SIM,
update nothing in the app, pair the new number via the QR flow, and consider
lowering send volume (Settings → hourly cap).

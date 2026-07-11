# Running unattended — surviving restarts automatically

Reminders only go out while the host is on, Docker is running, and the
containers are up. After a reboot or power cut that chain has four links,
and any broken link looks like "TaskWA isn't restarting":

| # | Link | Fix |
|---|------|-----|
| 1 | The machine powers back on | macOS: `sudo pmset -a autorestart 1`. PCs: enable "Restore on AC power" in BIOS/UEFI. Servers/Pis: usually automatic. |
| 2 | A user session starts (desktop OSes) | Enable automatic login (macOS: System Settings → Users & Groups; Windows: `netplwiz`). Note: with FileVault/BitLocker a password is still required at cold boot — accept that, don't disable disk encryption. |
| 3 | Docker starts | Docker Desktop → Settings → General → *Start when you sign in*. Linux: `systemctl enable docker`. |
| 4 | The containers come up | `restart: unless-stopped` restarts them **unless they were stopped when Docker last quit** (e.g. after a `docker compose down`). The autostart scripts below repair this every time. |

## One-command setup (link 4, plus starting Docker itself)

From the repo folder:

**macOS** — installs a LaunchAgent that runs at every login:
```bash
./scripts/autostart-macos.sh          # --uninstall to remove
```

**Windows** — registers a Scheduled Task at logon:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1
# add -Uninstall to remove
```

**Linux (servers, Raspberry Pi)** — installs a systemd service; no login
needed at all:
```bash
sudo ./scripts/autostart-linux.sh     # --uninstall to remove
```

Each script auto-detects the repo folder it lives in, waits up to five
minutes for the Docker engine, then runs `docker compose up -d` — which is
idempotent: if everything is already running it does nothing.

## Verify the whole chain

Reboot the machine, touch nothing, wait three minutes, then open
`http://localhost:3000/health` — the session should be `WORKING`.
macOS log if it isn't: `/tmp/taskwa-autostart.log`.

## What the app itself already handles

- Task digests missed by **less than 6 hours** are sent on startup.
- Missed **broadcasts are skipped** deliberately — a scheduled "good
  morning" should not arrive mid-afternoon.
- The WhatsApp pairing survives restarts (it lives in `data/waha/`).

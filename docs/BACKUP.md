# Backups & restore

## What happens automatically

- **Nightly database snapshot** at 02:30 (server time) to `./backups/`,
  named `tasks-YYYYMMDD-HHMMSS.db`. The 14 most recent are kept.
- **Archive ledger**: completed/cancelled tasks older than the retention
  period (Settings, default 30 days) are appended to `backups/archive.csv`
  before being purged from the live database. History is never lost.

## Restoring

```bash
cd taskwa
docker compose stop app
cp backups/tasks-20260710-023000.db data/tasks.db     # pick your snapshot
docker compose start app
```

That restores tasks, members, groups, settings and history to the moment of
the snapshot. The WhatsApp pairing is separate (in `data/waha/`) and is not
affected by a database restore.

## Off-machine copies (recommended)

The `backups/` folder is on the same disk as everything else. Copy it
somewhere else periodically — a cloud-synced folder or another machine:

```bash
rsync -a backups/ ~/Dropbox/taskwa-backups/     # example
```

## What to back up before risky changes

`data/tasks.db` (the database) and `.env` (your secrets). The `data/waha/`
session store is replaceable — a QR re-scan recreates it.

## Uninstalling

```bash
docker compose down
```

Keep `data/` and `backups/` if you might return; delete the folder to remove
everything. Finally, remove the linked device on the bot phone:
WhatsApp → Settings → Linked devices.

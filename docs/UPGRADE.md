# Upgrading TaskWA

## Standard upgrade

```bash
cd taskwa                       # your install folder
docker compose exec app python -m app.cli send-digests   # optional: flush today first
cp data/tasks.db backups/pre-upgrade-tasks.db             # belt and braces
git pull
docker compose up -d --build
```

Database schema changes are applied automatically on start (new tables are
created as needed). Tasks, members, settings and the WhatsApp pairing all
survive an upgrade.

## Version pinning

Releases are tagged (`v1.3.0`, …). To stay on a known version instead of
tracking main:

```bash
git fetch --tags
git checkout v1.3.0
docker compose up -d --build
```

## After upgrading

1. Dashboard → Health: session `WORKING`, no red banner.
2. `docker compose logs app --tail 20` — no errors on boot.
3. Health → *Run digests now* with dry-run ON if you want a rehearsal.

## Rolling back

```bash
git checkout <previous-tag>
docker compose up -d --build
```

If a newer version changed the database in a way the old code dislikes,
restore the pre-upgrade snapshot (see `BACKUP.md`).

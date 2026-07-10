# Running on a VPS

Use this when you can't keep a machine at home always-on. A 1–2 vCPU / 2 GB
RAM VPS (~$5–10/month) is plenty for the app + gateway. Do **not** run the
Ollama profile on small VPSes; for v2 AI parsing use a cloud API key instead.

## Steps

1. Create the VPS (Ubuntu 22.04+), point a DNS A record at it
   (e.g. `tasks.yourdomain.com`).
2. Install Docker: `curl -fsSL https://get.docker.com | sh`
3. Clone the repo, `cp .env.example .env`, set the secrets.
4. Edit `Caddyfile`: replace `tasks.example.com` with your domain.
5. Start with HTTPS: `docker compose --profile caddy up -d`
6. Firewall: allow 22, 80, 443 only.
   ```bash
   ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable
   ```
7. Browse to `https://tasks.yourdomain.com` — the setup wizard takes over.
   Caddy provisions the TLS certificate automatically.

## Notes
- Ports 3000/3001 stay bound to localhost on the VPS; only Caddy is public.
- Your team's task data now lives on rented hardware — that's the trade-off.
- Backups land in `./backups` on the VPS; copy them off-machine periodically
  (`scp` or a cron rsync).

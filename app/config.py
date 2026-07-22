"""Environment configuration. Everything else lives in the DB settings table."""
import logging

from pydantic_settings import BaseSettings

log = logging.getLogger("config")

# The three WAHA engines TaskWA documents and supports. WAHA itself also
# accepts WPP, but TaskWA doesn't test against it, so it's deliberately not
# in this set.
KNOWN_WAHA_ENGINES = {"WEBJS", "NOWEB", "GOWS"}


class Env(BaseSettings):
    # Paths
    data_dir: str = "/data"
    backup_dir: str = "/backups"

    # WAHA gateway
    waha_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_session: str = "default"

    # Which WAHA engine the gateway container is configured to run
    # (WEBJS/NOWEB/GOWS). This is a config-at-setup choice, not a live
    # toggle — see .env.example for the full picker and
    # TROUBLESHOOTING.md > "Switching WhatsApp engines" to change it.
    # TaskWA only DISPLAYS this value (read-only, on the Health page); it
    # never calls WAHA to change engines itself.
    waha_engine: str = "WEBJS"

    # Shared secret the gateway must present on webhook calls (?token=...)
    webhook_secret: str = "change-me"

    # Cookie signing secret
    app_secret: str = "change-me-too"

    # Optional SMTP for health alerts
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    alert_email: str = ""

    # Optional healthchecks.io ping URL
    healthchecks_url: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


env = Env()

if env.waha_engine.upper() not in KNOWN_WAHA_ENGINES:
    log.warning(
        "WAHA_ENGINE=%r is not one of %s — the Health page will still show "
        "this value, but it may not match what the waha container is "
        "actually running. Check .env against .env.example.",
        env.waha_engine, sorted(KNOWN_WAHA_ENGINES))

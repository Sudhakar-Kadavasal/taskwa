"""Environment configuration. Everything else lives in the DB settings table."""
from pydantic_settings import BaseSettings


class Env(BaseSettings):
    # Paths
    data_dir: str = "/data"
    backup_dir: str = "/backups"

    # WAHA gateway
    waha_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_session: str = "default"

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

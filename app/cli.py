"""Admin CLI. Usage:
    docker compose exec app python -m app.cli reset-password
    docker compose exec app python -m app.cli send-digests
"""
import getpass
import sys

from .db import engine, session_scope, get_setting, set_setting, DEFAULTS
from .models import Base


def _init():
    Base.metadata.create_all(engine)
    with session_scope() as s:
        for k, v in DEFAULTS.items():
            if get_setting(s, k) is None:
                set_setting(s, k, v)


def main():
    _init()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "reset-password":
        pw = getpass.getpass("New admin password (8+ chars): ")
        if len(pw) < 8:
            print("Too short.")
            sys.exit(1)
        from .security import set_password
        set_password(pw)
        print("Password updated.")
    elif cmd == "send-digests":
        from .digest import send_daily_digests
        send_daily_digests()
        print("Digest run complete (check dry-run setting).")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

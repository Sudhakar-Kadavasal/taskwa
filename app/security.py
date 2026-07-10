"""Admin auth: password hashing, signed-cookie sessions, WhatsApp reset codes."""
import secrets
from datetime import datetime, timedelta

from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.hash import bcrypt

from .config import env
from .db import get_setting, session_scope, set_setting
from .models import Member, ResetCode
from .waha import chat_id_for_phone, send_text

_serializer = URLSafeTimedSerializer(env.app_secret, salt="session")
COOKIE = "wtm_session"
MAX_AGE = 60 * 60 * 12  # 12 h


def hash_password(pw: str) -> str:
    return bcrypt.hash(pw)


def verify_password(pw: str) -> bool:
    with session_scope() as s:
        h = get_setting(s, "admin_password_hash")
    return bool(h) and bcrypt.verify(pw, h)


def set_password(pw: str):
    with session_scope() as s:
        set_setting(s, "admin_password_hash", hash_password(pw))


def make_cookie() -> str:
    return _serializer.dumps({"role": "admin"})


def check_cookie(value: str | None) -> bool:
    if not value:
        return False
    try:
        _serializer.loads(value, max_age=MAX_AGE)
        return True
    except BadSignature:
        return False


# ---------------- WhatsApp reset code ----------------
def send_reset_code() -> bool:
    """Sends a 6-digit code to every active admin's WhatsApp. 10-min validity."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    with session_scope() as s:
        s.query(ResetCode).delete()
        s.add(ResetCode(code_hash=bcrypt.hash(code),
                        expires_at=datetime.utcnow() + timedelta(minutes=10)))
        admins = (s.query(Member)
                   .filter(Member.role == "admin", Member.active.is_(True)).all())
        phones = [a.phone for a in admins]
    if not phones:
        return False
    ok = False
    for p in phones:
        ok = send_text(chat_id_for_phone(p),
                       f"TaskWa password reset code: {code}\n"
                       "Valid for 10 minutes. Ignore if you didn't request it.") or ok
    return ok


def verify_reset_code(code: str) -> bool:
    with session_scope() as s:
        row = s.query(ResetCode).first()
        if not row or row.expires_at < datetime.utcnow():
            return False
        if bcrypt.verify(code.strip(), row.code_hash):
            s.delete(row)
            return True
    return False

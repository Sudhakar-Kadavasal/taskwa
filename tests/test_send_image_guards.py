"""send_image must obey the SAME outbound guards as send_text: an image can
never reach anyone a text message could not (allowlist), it honours dry-run,
the hourly cap and the throttle, and it logs every attempt. The real-send
path is exercised with a fake WAHA client so we can assert the payload shape
against the endpoint verified on the live gateway (WAHA 2026.7.1)."""
import base64
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BACKUP_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import waha
from app.db import engine, SessionLocal, session_scope, set_setting
from app.models import Base, Member, Group, MessageLog
from app.waha import send_image

PNG = b"\x89PNG\r\n\x1a\n-fake-image-bytes-"


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_scope() as s:
        set_setting(s, "dry_run", True)
        s.add(Member(name="Sk", phone="971500000001", role="admin"))
        s.add(Group(name="Team", chat_id="120363001@g.us"))
        s.add(Member(name="Ex", phone="971500000009", role="member",
                     active=False))


def _last(chat_id):
    s = SessionLocal()
    row = (s.query(MessageLog).filter(MessageLog.chat_id == chat_id)
            .order_by(MessageLog.id.desc()).first())
    s.close()
    return row


# ---------------- allowlist parity with send_text ----------------
def test_member_receives_dryrun():
    assert send_image("971500000001@c.us", PNG, "your board") is True
    row = _last("971500000001@c.us")
    assert row.status == "dryrun" and "[image]" in row.text


def test_registered_group_receives_dryrun():
    assert send_image("120363001@g.us", PNG) is True
    assert _last("120363001@g.us").status == "dryrun"


def test_stranger_blocked():
    assert send_image("971599999999@c.us", PNG) is False
    assert _last("971599999999@c.us").status == "blocked"


def test_unregistered_group_blocked():
    assert send_image("120363999@g.us", PNG) is False
    assert _last("120363999@g.us").status == "blocked"


def test_deactivated_member_blocked():
    assert send_image("971500000009@c.us", PNG) is False
    assert _last("971500000009@c.us").status == "blocked"


def test_lid_resolves_and_passes_allowlist():
    """A …@lid recipient is canonicalised to phone@c.us before the allowlist,
    exactly like send_text."""
    waha._lid_cache["249902722478108"] = "971500000001"   # registered (Sk)
    assert send_image("249902722478108@lid", PNG) is True
    assert _last("971500000001@c.us").status == "dryrun"


def test_unresolvable_lid_blocked():
    waha._lid_cache["666777888999000"] = None
    assert send_image("666777888999000@lid", PNG) is False
    assert _last("666777888999000@lid").status == "blocked"


# ---------------- real-send path (fake WAHA client) ----------------
class _FakeResp:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Captures the POST instead of hitting the network."""
    calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, path, json=None):
        _FakeClient.calls.append((path, json))
        return _FakeResp(201)


def _install_fake(monkeypatch, status=201, text=""):
    _FakeClient.calls = []

    class C(_FakeClient):
        def post(self, path, json=None):
            _FakeClient.calls.append((path, json))
            return _FakeResp(status, text)

    monkeypatch.setattr(waha, "_client", lambda: C())
    monkeypatch.setattr(waha, "_throttle", lambda: None)  # no real sleeping


def test_real_send_payload_shape(monkeypatch):
    """Non-dry-run: assert endpoint + payload match the verified WAHA shape and
    that the image round-trips as base64."""
    with session_scope() as s:
        set_setting(s, "dry_run", False)
    _install_fake(monkeypatch)
    try:
        assert send_image("971500000001@c.us", PNG, "hello") is True
        path, body = _FakeClient.calls[-1]
        assert path == "/api/sendImage"
        assert body["chatId"] == "971500000001@c.us"
        assert body["caption"] == "hello"
        f = body["file"]
        assert f["mimetype"] == "image/png" and f["filename"] == "board.png"
        assert base64.b64decode(f["data"]) == PNG   # round-trips
        assert _last("971500000001@c.us").status == "sent"
    finally:
        with session_scope() as s:
            set_setting(s, "dry_run", True)


def test_real_send_http_error_logged_failed(monkeypatch):
    with session_scope() as s:
        set_setting(s, "dry_run", False)
    _install_fake(monkeypatch, status=500, text="boom")
    try:
        assert send_image("971500000001@c.us", PNG) is False
        assert _last("971500000001@c.us").status == "failed"
    finally:
        with session_scope() as s:
            set_setting(s, "dry_run", True)


def test_hourly_cap_blocks_image(monkeypatch):
    """With dry-run off and the cap reached, the image is refused BEFORE any
    network call - same as send_text. (cap of 0 is treated as "use default"
    by the `... or 60` fallback, so a real cap test seeds a sent log and
    caps at 1.)"""
    with session_scope() as s:
        set_setting(s, "dry_run", False)
        set_setting(s, "hourly_cap", 1)
        s.add(MessageLog(chat_id="971500000001@c.us", text="x", status="sent"))
    _install_fake(monkeypatch)
    try:
        assert send_image("971500000001@c.us", PNG) is False
        assert _last("971500000001@c.us").status == "failed"
        assert _FakeClient.calls == []   # never reached the gateway
    finally:
        with session_scope() as s:
            set_setting(s, "dry_run", True)
            set_setting(s, "hourly_cap", 60)

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

from .db import engine, session_scope, get_setting, set_setting, DEFAULTS
from .models import Base
from .ui import router as ui_router
from .webhook import router as webhook_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="TaskWA", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(
    directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(webhook_router)
app.include_router(ui_router)


def _migrate():
    """Tiny additive migrations for existing SQLite databases.
    create_all() only creates missing tables - it never adds columns."""
    from sqlalchemy import text
    with engine.begin() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(broadcasts)"))]
        if cols and "tz" not in cols:
            c.execute(text(
                "ALTER TABLE broadcasts ADD COLUMN tz VARCHAR(64) DEFAULT ''"))
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(tasks)"))]
        if cols and "waiting_on_id" not in cols:
            c.execute(text(
                "ALTER TABLE tasks ADD COLUMN waiting_on_id INTEGER"))


def _stamp_broadcast_tz():
    """Pin the dashboard timezone onto any broadcast that has none, so
    pre-v1.6.2 rows keep firing at the same wall-clock time forever."""
    from .models import Broadcast
    with session_scope() as s:
        tzname = get_setting(s, "timezone") or "UTC"
        for b in s.query(Broadcast).filter(
                (Broadcast.tz.is_(None)) | (Broadcast.tz == "")).all():
            b.tz = tzname


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    _migrate()
    with session_scope() as s:
        for k, v in DEFAULTS.items():
            if get_setting(s, k) is None:
                set_setting(s, k, v)
    _stamp_broadcast_tz()
    from .scheduler import start
    start()


@app.get("/ping")
def ping():
    return {"ok": True}

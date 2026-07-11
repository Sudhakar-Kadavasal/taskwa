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


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with session_scope() as s:
        for k, v in DEFAULTS.items():
            if get_setting(s, k) is None:
                set_setting(s, k, v)
    from .scheduler import start
    start()


@app.get("/ping")
def ping():
    return {"ok": True}

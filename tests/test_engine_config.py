"""WhatsApp engine config-at-setup (v1.7.3).

WAHA_ENGINE is a documented .env value, not something TaskWA ever changes on
WAHA's behalf - these tests only cover the app's side: the default, the
"is this a value we recognise" guard, and that KNOWN_WAHA_ENGINES matches
what .env.example actually documents (WEBJS/NOWEB/GOWS - not WPP)."""
import importlib
import logging
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["BACKUP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config as config_module


def _reload_config():
    """app.config builds its `env` singleton at import time, so changing
    WAHA_ENGINE requires a reload to see it take effect."""
    return importlib.reload(config_module)


def test_default_engine_is_webjs(monkeypatch):
    monkeypatch.delenv("WAHA_ENGINE", raising=False)
    mod = _reload_config()
    assert mod.env.waha_engine == "WEBJS"
    _reload_config()   # leave the module in its normal state for other tests


def test_known_engines_are_exactly_the_documented_three():
    assert config_module.KNOWN_WAHA_ENGINES == {"WEBJS", "NOWEB", "GOWS"}


def test_unrecognised_engine_value_logs_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("WAHA_ENGINE", "BOGUS")
    with caplog.at_level(logging.WARNING, logger="config"):
        mod = _reload_config()
    assert mod.env.waha_engine == "BOGUS"   # still surfaced, just flagged
    assert any("BOGUS" in r.message for r in caplog.records)
    monkeypatch.delenv("WAHA_ENGINE", raising=False)
    _reload_config()


def test_known_engine_values_are_silent(monkeypatch, caplog):
    for value in ("WEBJS", "NOWEB", "GOWS"):
        monkeypatch.setenv("WAHA_ENGINE", value)
        with caplog.at_level(logging.WARNING, logger="config"):
            caplog.clear()
            mod = _reload_config()
        assert mod.env.waha_engine == value
        assert not caplog.records
    monkeypatch.delenv("WAHA_ENGINE", raising=False)
    _reload_config()

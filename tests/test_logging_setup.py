"""Logging wird nur von den Programmen eingerichtet, nicht beim Import (Commit 11)."""

import logging
import runpy
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import flask
import pytest

import bot_listener
import common
import price_tracker

ROOT = Path(__file__).resolve().parent.parent


# ---------- Import hat keine Nebenwirkungen ----------

@pytest.mark.parametrize("module", ["price_tracker", "app", "bot_listener", "manage_games", "common"])
def test_importing_a_module_does_not_configure_logging(module):
    """In einem frischen Python-Prozess: Nach dem Import darf kein Log-Handler existieren."""
    result = subprocess.run(
        [sys.executable, "-c",
            f"import {module}, logging; print(len(logging.getLogger().handlers))"],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == "0", result.stderr


# ---------- setup_logging ----------

@pytest.fixture
def isolated_logging(tmp_path, monkeypatch):
    root = logging.getLogger()
    handlers_before, level_before = list(root.handlers), root.level
    monkeypatch.setattr(price_tracker, "LOG_FILE", tmp_path / "tracker.log")
    monkeypatch.setattr(price_tracker, "_logging_ready", False)
    yield tmp_path / "tracker.log"
    for handler in list(root.handlers):
        if handler not in handlers_before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level_before)


def new_handlers(before):
    return [h for h in logging.getLogger().handlers if h not in before]


def test_setup_logging_writes_utf8_lines_to_the_log_file(isolated_logging):
    price_tracker.setup_logging()
    logging.getLogger("price_tracker").info("Preis 9,99 € – Änderung")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = isolated_logging.read_text(encoding="utf-8")
    assert "[INFO] Preis 9,99 € – Änderung" in text


def test_setup_logging_adds_file_and_console_handler_once(isolated_logging):
    before = list(logging.getLogger().handlers)
    price_tracker.setup_logging()
    price_tracker.setup_logging()              # zweiter Aufruf ändert nichts
    added = new_handlers(before)
    assert len(added) == 2
    assert sum(isinstance(h, RotatingFileHandler) for h in added) == 1


def test_log_file_rotates_at_one_megabyte_and_keeps_three_backups(isolated_logging):
    before = list(logging.getLogger().handlers)
    price_tracker.setup_logging()
    file_handler = next(h for h in new_handlers(before) if isinstance(h, RotatingFileHandler))
    assert file_handler.maxBytes == 1_000_000 and file_handler.backupCount == 3


def test_setup_logging_enables_info_level(isolated_logging):
    logging.getLogger().setLevel(logging.WARNING)
    price_tracker.setup_logging()
    assert logging.getLogger().level == logging.INFO


# ---------- Einstiegspunkte rufen setup_logging auf ----------

def test_price_tracker_main_sets_up_logging_before_running(monkeypatch):
    order = []
    monkeypatch.setattr(price_tracker, "setup_logging", lambda: order.append("logging"))
    monkeypatch.setattr(price_tracker, "run", lambda: order.append("run"))
    price_tracker.main()
    assert order == ["logging", "run"]


def test_price_tracker_main_logs_and_reraises_unexpected_errors(monkeypatch, caplog):
    monkeypatch.setattr(price_tracker, "setup_logging", lambda: None)

    def broken():
        raise RuntimeError("kaputt")
    monkeypatch.setattr(price_tracker, "run", broken)
    with pytest.raises(RuntimeError):
        price_tracker.main()
    assert "Unerwarteter Fehler" in caplog.text


def test_web_app_script_sets_up_logging_and_binds_to_localhost_only(monkeypatch):
    order = []
    monkeypatch.setattr(price_tracker, "setup_logging", lambda: order.append("logging"))
    monkeypatch.setattr(flask.Flask, "run", lambda self, *a, **k: order.append(("run", k)))
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
    assert order == ["logging", ("run", {"host": "127.0.0.1"})]


def test_bot_main_sets_up_both_logs(monkeypatch):
    calls = []

    class Stop(Exception):
        pass

    def stop(*args, **kwargs):
        raise Stop
    monkeypatch.setattr(common, "load_config", lambda: ("tok", "1"))
    monkeypatch.setattr(bot_listener, "setup_logging", lambda: calls.append("bot.log"))
    monkeypatch.setattr(price_tracker, "setup_logging", lambda: calls.append("tracker.log"))
    monkeypatch.setattr(bot_listener, "skip_pending_updates", lambda token: None)
    monkeypatch.setattr(common, "send_telegram", lambda *a: None)
    monkeypatch.setattr(bot_listener, "poll_once", stop)

    with pytest.raises(Stop):
        bot_listener.main()
    assert calls == ["bot.log", "tracker.log"]
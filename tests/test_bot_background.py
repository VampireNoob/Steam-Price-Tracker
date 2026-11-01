"""/check läuft im Hintergrund (Commit 4): Der Bot bleibt ansprechbar."""

import logging
import threading

import pytest

import bot_listener
import common
import price_tracker


@pytest.fixture(autouse=True)
def fresh_lock(monkeypatch):
    monkeypatch.setattr(bot_listener, "_check_lock", threading.Lock())


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: messages.append(text))
    return messages


def test_check_returns_immediately_while_the_check_is_still_running(sent, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_run():
        started.set()
        release.wait(timeout=5)
    monkeypatch.setattr(price_tracker, "run", slow_run)

    thread = bot_listener.handle_check("tok", "1")

    assert started.wait(timeout=5)
    assert thread.is_alive()                         # Check läuft noch ...
    assert sent == ["Preis-Check läuft ..."]         # ... und handle_check ist schon zurück
    release.set()
    thread.join(timeout=5)
    assert sent == ["Preis-Check läuft ...", "Preis-Check abgeschlossen."]


def test_bot_answers_other_commands_while_check_is_running(sent, monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(price_tracker, "run", lambda: (started.set(), release.wait(timeout=5)))

    thread = bot_listener.handle_check("tok", "1")
    started.wait(timeout=5)

    bot_listener.process_message("tok", "1", {"chat": {"id": 1}, "text": "/help"})
    assert any("Verfügbare Befehle" in m for m in sent)      # Bot antwortet währenddessen

    release.set()
    thread.join(timeout=5)


def test_second_check_is_rejected_while_one_is_running(sent, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_run():
        calls.append(1)
        started.set()
        release.wait(timeout=5)
    monkeypatch.setattr(price_tracker, "run", slow_run)

    first = bot_listener.handle_check("tok", "1")
    started.wait(timeout=5)
    second = bot_listener.handle_check("tok", "1")

    assert second is None
    assert "Ein Preis-Check läuft bereits." in sent
    release.set()
    first.join(timeout=5)
    assert calls == [1]                               # run() nur einmal gestartet


def test_new_check_is_possible_after_the_previous_one_finished(sent, monkeypatch):
    monkeypatch.setattr(price_tracker, "run", lambda: None)
    bot_listener.handle_check("tok", "1").join(timeout=5)
    second = bot_listener.handle_check("tok", "1")
    assert second is not None
    second.join(timeout=5)
    assert sent.count("Preis-Check abgeschlossen.") == 2


def test_failing_check_reports_error_and_releases_lock(sent, monkeypatch, caplog):
    def broken_run():
        raise RuntimeError("Steam kaputt")
    monkeypatch.setattr(price_tracker, "run", broken_run)

    bot_listener.handle_check("tok", "1").join(timeout=5)

    assert "⚠️ Preis-Check fehlgeschlagen, Details stehen in bot.log." in sent
    assert "Steam kaputt" not in " ".join(sent)               # keine Details an den Chat
    assert "Preis-Check im Hintergrund fehlgeschlagen" in caplog.text
    assert "RuntimeError" in caplog.text                       # Traceback im Log
    assert bot_listener._check_lock.acquire(blocking=False)   # Sperre ist frei


def test_system_exit_in_check_does_not_leave_lock_blocked(sent, monkeypatch):
    def exiting_run():
        raise SystemExit("Konfiguration fehlt")
    monkeypatch.setattr(price_tracker, "run", exiting_run)

    bot_listener.handle_check("tok", "1").join(timeout=5)

    assert any("fehlgeschlagen" in m for m in sent)
    assert bot_listener._check_lock.acquire(blocking=False)


def test_lock_is_released_if_starting_the_check_fails(monkeypatch):
    def broken_send(token, chat, text):
        raise OSError("send kaputt")
    monkeypatch.setattr(common, "send_telegram", broken_send)

    with pytest.raises(OSError):
        bot_listener.handle_check("tok", "1")
    assert bot_listener._check_lock.acquire(blocking=False)   # nicht dauerhaft gesperrt


def test_check_command_via_process_message_starts_background_check(sent, monkeypatch):
    done = threading.Event()
    monkeypatch.setattr(price_tracker, "run", lambda: done.set())
    bot_listener.process_message("tok", "1", {"chat": {"id": 1}, "text": "/check"})
    assert done.wait(timeout=5)
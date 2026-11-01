"""Das Bot-Log (bot.log): Einrichtung, Fehler und fremde Chats werden protokolliert."""

import logging

import pytest

import bot_listener
import common


@pytest.fixture
def bot_env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    return {"sent": sent}


def test_setup_logging_writes_to_bot_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_listener, "LOG_FILE", tmp_path / "bot.log")
    handler = bot_listener.setup_logging()
    try:
        bot_listener.log.info("Testeintrag")
        handler.flush()
        text = (tmp_path / "bot.log").read_text(encoding="utf-8")
        assert "Testeintrag" in text and "[INFO]" in text
    finally:
        bot_listener.log.removeHandler(handler)
        handler.close()
        bot_listener.log.propagate = True    # sonst sehen spätere Tests nichts per caplog


def test_foreign_chat_is_ignored_and_logged(bot_env, caplog):
    caplog.set_level(logging.INFO)
    bot_listener.process_message("tok", "111", {"chat": {"id": 999}, "text": "/list"})
    assert bot_env["sent"] == []                      # keine Antwort an Fremde
    assert "fremdem Chat" in caplog.text and "999" in caplog.text


def test_own_chat_command_is_logged_without_arguments(bot_env, caplog):
    caplog.set_level(logging.INFO)
    bot_listener.process_message("tok", "111", {"chat": {"id": 111}, "text": "/help"})
    assert any("Verfügbare Befehle" in m for m in bot_env["sent"])
    assert "Befehl empfangen: /help" in caplog.text


def test_search_terms_do_not_end_up_in_the_log(bot_env, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(common, "search_steam_games", lambda term: [])
    bot_listener.process_message("tok", "111", {"chat": {"id": 111}, "text": "/add Geheimes Spiel"})
    assert "Befehl empfangen: /add" in caplog.text
    assert "Geheimes" not in caplog.text
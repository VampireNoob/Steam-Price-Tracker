"""End-to-End-Tests für price_tracker.run(): Preisänderungs-Logik inkl. Telegram-Meldung."""

import json

import pytest

import common
import price_tracker


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolierte Umgebung: eigene games.json/prices.db, Fake-Telegram, Fake-Steam."""
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda token, chat, text: sent.append(text))

    prices = {}  # appid -> dict wie von fetch_price geliefert
    monkeypatch.setattr(price_tracker, "fetch_price", lambda appid: prices.get(appid))

    (tmp_path / "games.json").write_text(
        json.dumps([{"name": "Testspiel", "appid": 1}]), encoding="utf-8"
    )
    return {"sent": sent, "prices": prices}


def price(cents, discount=0):
    return {"price_cents": cents, "initial_cents": cents, "discount_percent": discount, "currency": "EUR"}


def test_first_run_stores_baseline_without_notification(env):
    env["prices"][1] = price(5999)
    price_tracker.run()
    assert env["sent"] == []


def test_unchanged_price_sends_nothing(env):
    env["prices"][1] = price(5999)
    price_tracker.run()
    price_tracker.run()
    assert env["sent"] == []


def test_price_drop_sends_message_with_discount(env):
    env["prices"][1] = price(5999)
    price_tracker.run()
    env["prices"][1] = price(2999, discount=50)
    price_tracker.run()

    assert len(env["sent"]) == 1
    message = env["sent"][0]
    assert "Testspiel" in message
    assert "gefallen" in message
    assert "59,99 €" in message and "29,99 €" in message
    assert "-50%" in message


def test_price_increase_is_reported_without_discount_line(env):
    env["prices"][1] = price(1999)
    price_tracker.run()
    env["prices"][1] = price(2999)
    price_tracker.run()

    message = env["sent"][0]
    assert "gestiegen" in message
    assert "Rabatt" not in message


def test_game_without_price_data_is_skipped_not_crashing(env):
    # fetch_price liefert None (z.B. Bundle mit kaputtem Datenformat)
    price_tracker.run()
    assert env["sent"] == []


def test_multiple_changes_are_sent_as_one_message(env, tmp_path):
    (tmp_path / "games.json").write_text(
        json.dumps([{"name": "A", "appid": 1}, {"name": "B", "appid": 2}]), encoding="utf-8"
    )
    env["prices"][1] = price(1000)
    env["prices"][2] = price(2000)
    price_tracker.run()
    env["prices"][1] = price(500, 50)
    env["prices"][2] = price(1000, 50)
    price_tracker.run()

    assert len(env["sent"]) == 1
    assert "A" in env["sent"][0] and "B" in env["sent"][0]
"""Der Bot überlebt Fehler (Commit 2): defekte Updates, kaputte Telegram-Antworten."""

import logging

import pytest
import requests

import bot_listener
import common
import price_tracker


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: messages.append(text))
    return messages


def update(update_id, text="/help", chat_id=111):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


# ---------- process_updates ----------

def test_error_in_one_update_does_not_stop_the_others(sent, monkeypatch, caplog):
    calls = []

    def fake_process(token, allowed, message):
        calls.append(message["text"])
        if message["text"] == "boom":
            raise RuntimeError("kaputt")
    monkeypatch.setattr(bot_listener, "process_message", fake_process)

    new_offset = bot_listener.process_updates(
        "tok", "111", [update(1, "a"), update(2, "boom"), update(3, "c")])

    assert calls == ["a", "boom", "c"]          # das dritte wurde trotzdem verarbeitet
    assert new_offset == 4
    assert "Fehler beim Verarbeiten eines Updates" in caplog.text
    assert "RuntimeError" in caplog.text        # Traceback steht im Log


def test_owner_is_told_about_the_error_without_details(sent, monkeypatch):
    def fake_process(token, allowed, message):
        raise RuntimeError("geheimes-detail")
    monkeypatch.setattr(bot_listener, "process_message", fake_process)

    bot_listener.process_updates("tok", "111", [update(1)])
    assert sent == ["⚠️ Interner Fehler, Details stehen in bot.log."]
    assert "geheimes-detail" not in sent[0]


def test_failing_update_still_advances_offset(sent, monkeypatch):
    """Sonst würde Telegram dasselbe kaputte Update endlos neu liefern."""
    def fake_process(token, allowed, message):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(bot_listener, "process_message", fake_process)
    assert bot_listener.process_updates("tok", "111", [update(41)], offset=None) == 42


def test_update_without_id_is_survived(sent):
    assert bot_listener.process_updates("tok", "111", [{"message": {}}, update(5)], offset=1) == 6


def test_empty_update_list_keeps_offset(sent):
    assert bot_listener.process_updates("tok", "111", [], offset=7) == 7
    assert bot_listener.process_updates("tok", "111", [], offset=None) is None


def test_failure_while_reporting_the_error_is_survived(monkeypatch):
    def fake_process(token, allowed, message):
        raise RuntimeError("kaputt")

    def broken_send(token, chat, text):
        raise OSError("auch das noch")
    monkeypatch.setattr(bot_listener, "process_message", fake_process)
    monkeypatch.setattr(common, "send_telegram", broken_send)
    assert bot_listener.process_updates("tok", "111", [update(1), update(2)]) == 3


def test_normal_updates_are_still_processed(sent):
    bot_listener.process_updates("tok", "111", [update(1, "/help")])
    assert any("Verfügbare Befehle" in m for m in sent)


# ---------- get_updates mit kaputten Antworten ----------

class FakeResponse:
    def __init__(self, payload=None, html=False):
        self._payload, self._html = payload, html

    def raise_for_status(self):
        pass

    def json(self):
        if self._html:
            r = requests.Response()
            r._content = b"<html>Bad Gateway</html>"
            r.status_code = 200
            return r.json()
        return self._payload


@pytest.mark.parametrize("response", [
    FakeResponse(html=True),
    FakeResponse(payload=[]),
    FakeResponse(payload=None),
    FakeResponse(payload={"result": "kein Liste"}),
    FakeResponse(payload={"ok": True}),
])
def test_get_updates_survives_malformed_responses(monkeypatch, response):
    monkeypatch.setattr(bot_listener.requests, "get", lambda *a, **k: response)
    assert bot_listener.get_updates("tok") is None      # None = Fehler, nicht "nichts Neues"


def test_get_updates_returns_the_updates_list(monkeypatch):
    payload = {"ok": True, "result": [{"update_id": 1}]}
    monkeypatch.setattr(bot_listener.requests, "get", lambda *a, **k: FakeResponse(payload))
    assert bot_listener.get_updates("tok") == [{"update_id": 1}]


# ---------- Einfacher ValueError von json() (ältere requests-Versionen) ----------

class ValueErrorResponse:
    def raise_for_status(self):
        pass

    def json(self):
        raise ValueError("kein JSON")


def test_plain_value_error_from_json_is_survived(monkeypatch):
    """Aktuelle requests-Versionen werfen einen RequestException-Fehler, ältere (und
    andere JSON-Bibliotheken) ein einfaches ValueError. Beides darf nichts beenden."""
    response = ValueErrorResponse()
    # bot_listener, price_tracker und common benutzen dasselbe requests-Modul
    monkeypatch.setattr(bot_listener.requests, "get", lambda *a, **k: response)

    assert bot_listener.get_updates("tok") is None
    assert price_tracker.fetch_price(1) is None
    assert common.search_steam_games("x") == []
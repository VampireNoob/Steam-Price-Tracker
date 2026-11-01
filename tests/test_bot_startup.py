"""Beim Start werden Nachrichten aus der Offline-Zeit verworfen (Commit 5)."""

import logging

import pytest

import bot_listener
import common


# ---------- skip_pending_updates ----------

def fake_updates(monkeypatch, result, calls=None):
    def fake(token, offset=None, timeout=25):
        if calls is not None:
            calls.append({"offset": offset, "timeout": timeout})
        return result
    monkeypatch.setattr(bot_listener, "get_updates", fake)


def test_skip_returns_offset_after_the_last_pending_update(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    fake_updates(monkeypatch, [{"update_id": 10, "message": {"text": "/remove 2"}}])
    assert bot_listener.skip_pending_updates("tok") == 11
    assert "verworfen" in caplog.text and "10" in caplog.text


def test_skip_asks_telegram_for_the_last_update_only_and_does_not_wait(monkeypatch):
    calls = []
    fake_updates(monkeypatch, [], calls)
    bot_listener.skip_pending_updates("tok")
    assert calls == [{"offset": -1, "timeout": 0}]    # kein 25-Sekunden-Long-Polling beim Start


def test_skip_returns_none_when_nothing_is_pending(monkeypatch):
    fake_updates(monkeypatch, [])
    assert bot_listener.skip_pending_updates("tok") is None


def test_skip_returns_none_when_telegram_is_unreachable(monkeypatch):
    fake_updates(monkeypatch, None)
    assert bot_listener.skip_pending_updates("tok") is None


@pytest.mark.parametrize("bad_result", [[{}], [{"update_id": "x"}], ["kein dict"], [None]])
def test_skip_survives_malformed_updates(monkeypatch, bad_result):
    fake_updates(monkeypatch, bad_result)
    assert bot_listener.skip_pending_updates("tok") is None


# ---------- get_updates reicht den timeout durch ----------

class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": []}


def test_get_updates_passes_timeout_to_telegram_and_requests(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["params"], seen["timeout"] = params, timeout
        return FakeResponse()
    monkeypatch.setattr(bot_listener.requests, "get", fake_get)

    bot_listener.get_updates("tok", offset=-1, timeout=0)
    assert seen["params"] == {"timeout": 0, "offset": -1}
    assert seen["timeout"] == 10

    bot_listener.get_updates("tok")                       # Standard: Long Polling
    assert seen["params"] == {"timeout": 25} and seen["timeout"] == 35


# ---------- main(): Startmeldung und offset ----------

class StopLoop(Exception):
    pass


@pytest.fixture
def started(monkeypatch):
    """Lässt main() bis zur ersten Schleifenrunde laufen und hält dann an."""
    info = {"messages": [], "offset": "nicht erreicht"}
    monkeypatch.setattr(common, "load_config", lambda: ("tok", "1"))
    monkeypatch.setattr(bot_listener, "setup_logging", lambda: None)
    monkeypatch.setattr(bot_listener.price_tracker, "setup_logging", lambda: None)
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: info["messages"].append(text))

    def stop(token, chat_id, offset, failures, sleep=None):
        info["offset"] = offset
        raise StopLoop
    monkeypatch.setattr(bot_listener, "poll_once", stop)
    return info


def test_main_reports_discarded_messages_and_continues_after_them(started, monkeypatch):
    fake_updates(monkeypatch, [{"update_id": 10}])
    with pytest.raises(StopLoop):
        bot_listener.main()
    assert started["offset"] == 11
    assert started["messages"] == [
        "🤖 Bot-Steuerung ist jetzt aktiv. /help für Befehle.\n"
        "Nachrichten aus der Offline-Zeit wurden verworfen."]


def test_main_without_pending_messages_sends_the_plain_startup_message(started, monkeypatch):
    fake_updates(monkeypatch, [])
    with pytest.raises(StopLoop):
        bot_listener.main()
    assert started["offset"] is None
    assert started["messages"] == ["🤖 Bot-Steuerung ist jetzt aktiv. /help für Befehle."]
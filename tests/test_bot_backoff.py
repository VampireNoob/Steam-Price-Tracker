"""Der Bot wartet zwischen Fehlversuchen (Commit 3), statt im Dauerlauf anzufragen."""

import logging

import pytest

import bot_listener


@pytest.mark.parametrize("failures, expected", [
    (1, 5), (2, 10), (3, 20), (4, 40), (5, 60), (6, 60), (50, 60),
])
def test_retry_delay_grows_and_is_capped(failures, expected):
    assert bot_listener.retry_delay(failures) == expected


@pytest.fixture
def offline(monkeypatch):
    """Telegram ist nicht erreichbar: get_updates meldet None."""
    monkeypatch.setattr(bot_listener, "get_updates", lambda token, offset=None: None)


def test_failure_waits_and_keeps_offset(offline, monkeypatch):
    slept = []
    monkeypatch.setattr(bot_listener, "process_updates",
                        lambda *a, **k: pytest.fail("darf bei Fehler nicht verarbeiten"))

    offset, failures = bot_listener.poll_once("tok", "1", 42, 0, sleep=slept.append)

    assert (offset, failures) == (42, 1)
    assert slept == [5]


def test_repeated_failures_wait_longer_each_time(offline):
    slept = []
    offset, failures = None, 0
    for _ in range(7):
        offset, failures = bot_listener.poll_once("tok", "1", offset, failures, sleep=slept.append)
    assert slept == [5, 10, 20, 40, 60, 60, 60]
    assert failures == 7


def test_never_polls_without_waiting_when_offline(offline):
    """Regressionstest für den Dauerlauf: Jeder Fehlversuch muss warten."""
    slept = []
    offset, failures = None, 0
    for _ in range(200):
        offset, failures = bot_listener.poll_once("tok", "1", offset, failures, sleep=slept.append)
    assert len(slept) == 200 and min(slept) >= 5


def test_success_resets_failures_and_logs_recovery(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(bot_listener, "get_updates",
                        lambda token, offset=None: [{"update_id": 9, "message": None}])
    slept = []

    offset, failures = bot_listener.poll_once("tok", "1", None, 4, sleep=slept.append)

    assert (offset, failures) == (10, 0)
    assert slept == []
    assert "wiederhergestellt" in caplog.text


def test_empty_result_is_not_a_failure(monkeypatch):
    """Long Polling ohne neue Nachrichten liefert []: kein Fehler, keine Wartezeit."""
    monkeypatch.setattr(bot_listener, "get_updates", lambda token, offset=None: [])
    slept = []
    offset, failures = bot_listener.poll_once("tok", "1", 7, 0, sleep=slept.append)
    assert (offset, failures) == (7, 0) and slept == []


def test_failure_is_logged_with_next_attempt(offline, caplog):
    caplog.set_level(logging.INFO)
    bot_listener.poll_once("tok", "1", None, 2, sleep=lambda s: None)
    assert "Fehlversuch 3" in caplog.text and "20 s" in caplog.text


# ---------- get_updates unterscheidet Fehler und "nichts Neues" ----------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_updates_returns_none_on_network_error(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("kein Netz")
    monkeypatch.setattr(bot_listener.requests, "get", boom)
    assert bot_listener.get_updates("tok") is None


def test_get_updates_returns_empty_list_when_nothing_new(monkeypatch):
    monkeypatch.setattr(bot_listener.requests, "get",
                        lambda *a, **k: FakeResponse({"ok": True, "result": []}))
    assert bot_listener.get_updates("tok") == []
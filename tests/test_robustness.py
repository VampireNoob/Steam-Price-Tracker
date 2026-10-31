"""Robustheit (Paket 2): kaputte Steam-Antworten, defekte Einträge, sicheres Speichern."""

import json
import os

import pytest
import requests

import common
import price_tracker


# ---------- Steam liefert Unerwartetes ----------

class FakeResponse:
    def __init__(self, payload=None, html=False):
        self._payload, self._html = payload, html

    def raise_for_status(self):
        pass

    def json(self):
        if self._html:
            r = requests.Response()
            r._content = b"<html>Wartungsarbeiten</html>"
            r.status_code = 200
            return r.json()
        return self._payload


@pytest.mark.parametrize("response", [
    FakeResponse(html=True),               # HTML statt JSON
    FakeResponse(payload=[]),              # Liste statt Objekt
    FakeResponse(payload=None),            # JSON "null"
    FakeResponse(payload={"1": []}),       # Eintrag ist keine Struktur
    FakeResponse(payload={"1": None}),
])
def test_fetch_price_survives_malformed_steam_responses(monkeypatch, response):
    monkeypatch.setattr(price_tracker.requests, "get", lambda *a, **k: response)
    assert price_tracker.fetch_price(1) is None


@pytest.mark.parametrize("response", [
    FakeResponse(html=True),
    FakeResponse(payload=[]),
    FakeResponse(payload=None),
])
def test_search_survives_malformed_steam_responses(monkeypatch, response):
    monkeypatch.setattr(common.requests, "get", lambda *a, **k: response)
    assert common.search_steam_games("x") == []


# ---------- Ein defekter Eintrag bricht den Lauf nicht ab ----------

@pytest.fixture
def run_env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    return {"sent": sent, "monkeypatch": monkeypatch}


def price(cents):
    return {"price_cents": cents, "initial_cents": cents, "discount_percent": 0, "currency": "EUR"}


def test_one_failing_game_does_not_abort_the_run(run_env):
    common.save_games([{"name": "Kaputt", "appid": 1}, {"name": "Gut", "appid": 2}])
    state = {"gut": 1000}

    def fetch(appid):
        if appid == 1:
            raise RuntimeError("unerwartet")
        return price(state["gut"])
    run_env["monkeypatch"].setattr(price_tracker, "fetch_price", fetch)

    price_tracker.run()
    state["gut"] = 500
    price_tracker.run()
    assert len(run_env["sent"]) == 1 and "Gut" in run_env["sent"][0]


@pytest.mark.parametrize("bad_entry", [
    {"name": "Ohne AppID"},     # Schlüssel fehlt
    {"appid": 5},               # Name fehlt
    "kein Objekt",              # Eintrag ist ein String
    None,
])
def test_malformed_game_entry_is_skipped(run_env, bad_entry):
    common.save_games([bad_entry, {"name": "Gut", "appid": 2}])
    state = {"gut": 1000}
    run_env["monkeypatch"].setattr(price_tracker, "fetch_price", lambda appid: price(state["gut"]))

    price_tracker.run()
    state["gut"] = 500
    price_tracker.run()
    assert len(run_env["sent"]) == 1 and "Gut" in run_env["sent"][0]


# ---------- games.json wird sicher geschrieben ----------

@pytest.fixture
def games_file(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    return tmp_path


def test_save_games_leaves_no_temp_file(games_file):
    common.save_games([{"name": "A", "appid": 1}])
    assert sorted(p.name for p in games_file.iterdir()) == ["games.json"]


def test_failed_save_keeps_old_file_intact_and_cleans_up(games_file, monkeypatch):
    common.save_games([{"name": "Original", "appid": 1}])

    def broken_dump(obj, f, **kwargs):
        f.write('{"halb')            # halb geschriebene Datei ...
        raise OSError("Platte voll")  # ... und dann der Absturz
    monkeypatch.setattr(common.json, "dump", broken_dump)

    with pytest.raises(OSError):
        common.save_games([{"name": "Neu", "appid": 2}])

    assert json.loads((games_file / "games.json").read_text(encoding="utf-8")) == [
        {"name": "Original", "appid": 1}]
    assert sorted(p.name for p in games_file.iterdir()) == ["games.json"]


def test_save_retries_when_file_is_briefly_locked(games_file, monkeypatch):
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("gesperrt")
        return real_replace(src, dst)
    monkeypatch.setattr(common.os, "replace", flaky_replace)

    common.save_games([{"name": "A", "appid": 1}])
    assert calls["n"] == 3
    assert common.load_games() == [{"name": "A", "appid": 1}]


def test_save_gives_up_after_repeated_lock(games_file, monkeypatch):
    def always_locked(src, dst):
        raise PermissionError("gesperrt")
    monkeypatch.setattr(common.os, "replace", always_locked)
    with pytest.raises(PermissionError):
        common.save_games([{"name": "A", "appid": 1}])
    assert list(games_file.iterdir()) == []   # Temp-Datei wurde aufgeräumt
"""Tests für common.py: Spieleliste, Steam-Suche, letzter Preis aus der Datenbank."""

import sqlite3

import pytest
import requests

import common


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    return tmp_path


# ---------- games.json ----------

def test_load_games_without_file_returns_empty_list(paths):
    assert common.load_games() == []


def test_save_and_load_roundtrip_keeps_umlauts(paths):
    games = [{"name": "Tom Clancy’s The Division® 2", "appid": 2221490, "image": None},
             {"name": "Käse-Spiel", "appid": 1}]
    common.save_games(games)
    assert common.load_games() == games


# ---------- Steam-Suche (API gemockt) ----------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_search_parses_name_appid_and_image(monkeypatch):
    payload = {"items": [
        {"id": 2050650, "name": "Resident Evil 4", "tiny_image": "https://x/re4.jpg"},
        {"id": 254700, "name": "Resident Evil 4 (2005)"},  # ohne Bild
    ]}
    monkeypatch.setattr(common.requests, "get", lambda *a, **kw: FakeResponse(payload))

    assert common.search_steam_games("resident evil 4") == [
        {"name": "Resident Evil 4", "appid": 2050650, "image": "https://x/re4.jpg"},
        {"name": "Resident Evil 4 (2005)", "appid": 254700, "image": None},
    ]


def test_search_skips_items_without_id(monkeypatch):
    payload = {"items": [{"name": "Kaputt"}, {"id": 1, "name": "Ok"}]}
    monkeypatch.setattr(common.requests, "get", lambda *a, **kw: FakeResponse(payload))
    assert [r["appid"] for r in common.search_steam_games("x")] == [1]


def test_search_respects_max_results(monkeypatch):
    payload = {"items": [{"id": i, "name": f"Spiel {i}"} for i in range(20)]}
    monkeypatch.setattr(common.requests, "get", lambda *a, **kw: FakeResponse(payload))
    assert len(common.search_steam_games("spiel", max_results=3)) == 3


def test_search_returns_empty_list_on_network_error(monkeypatch):
    def boom(*a, **kw):
        raise requests.RequestException("timeout")
    monkeypatch.setattr(common.requests, "get", boom)
    assert common.search_steam_games("irgendwas") == []


def test_search_returns_empty_list_when_no_items(monkeypatch):
    monkeypatch.setattr(common.requests, "get", lambda *a, **kw: FakeResponse({"total": 0}))
    assert common.search_steam_games("gibtsnicht") == []


# ---------- get_latest_price ----------

def make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, appid INTEGER, "
        "name TEXT, price_cents INTEGER, discount_percent INTEGER, checked_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO price_history (appid, name, price_cents, discount_percent, checked_at) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_get_latest_price_without_database_returns_none(paths):
    assert common.get_latest_price(1) is None


def test_get_latest_price_returns_newest_entry_formatted(paths):
    make_db(paths / "prices.db", [
        (1, "Spiel", 5999, 0, "2026-07-01T10:00"),
        (1, "Spiel", 999, 75, "2026-07-02T10:00"),
    ])
    assert common.get_latest_price(1) == {
        "price": "9,99 €", "discount_percent": 75, "checked_at": "2026-07-02T10:00"}


def test_get_latest_price_unknown_appid_returns_none(paths):
    make_db(paths / "prices.db", [(1, "Spiel", 999, 0, "2026-07-01T10:00")])
    assert common.get_latest_price(999) is None
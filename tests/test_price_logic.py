"""Unit-Tests für die Preislogik und die Steam-Preisabfrage in price_tracker.py."""

import pytest
import requests

import price_tracker


# ---------- format_price / price_direction / build_change_message ----------

@pytest.mark.parametrize("cents, expected", [
    (0, "0,00 €"),
    (999, "9,99 €"),
    (5999, "59,99 €"),
    (100000, "1000,00 €"),
])
def test_format_price(cents, expected):
    assert price_tracker.format_price(cents) == expected


@pytest.mark.parametrize("previous, current, expected", [
    (5999, 2999, "gefallen"),
    (2999, 5999, "gestiegen"),
    (2999, 2999, None),
])
def test_price_direction(previous, current, expected):
    assert price_tracker.price_direction(previous, current) == expected


def test_build_change_message_drop_with_discount():
    msg = price_tracker.build_change_message(
        "Resident Evil 4", 3999, {"price_cents": 999, "discount_percent": 75}
    )
    assert msg == (
        "💰 Resident Evil 4\n"
        "Preis gefallen: 39,99 € → 9,99 €\n"
        "Aktueller Rabatt: -75%"
    )


def test_build_change_message_returns_none_when_unchanged():
    assert price_tracker.build_change_message(
        "Spiel", 1999, {"price_cents": 1999, "discount_percent": 0}
    ) is None


# ---------- fetch_price (Steam-API gemockt) ----------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def mock_steam(monkeypatch, payload):
    monkeypatch.setattr(price_tracker.requests, "get", lambda *a, **kw: FakeResponse(payload))


def test_fetch_price_parses_normal_response(monkeypatch):
    mock_steam(monkeypatch, {"42": {"success": True, "data": {"price_overview": {
        "final": 999, "initial": 3999, "discount_percent": 75, "currency": "EUR"}}}})
    assert price_tracker.fetch_price(42) == {
        "price_cents": 999, "initial_cents": 3999, "discount_percent": 75, "currency": "EUR"}


def test_fetch_price_survives_data_as_list(monkeypatch):
    """Regression: Steam liefert bei manchen Bundles 'data': [] statt eines Objekts."""
    mock_steam(monkeypatch, {"42": {"success": True, "data": []}})
    assert price_tracker.fetch_price(42) is None


def test_fetch_price_returns_none_when_success_false(monkeypatch):
    mock_steam(monkeypatch, {"42": {"success": False}})
    assert price_tracker.fetch_price(42) is None


def test_fetch_price_returns_none_for_free_game_without_price(monkeypatch):
    mock_steam(monkeypatch, {"42": {"success": True, "data": {"is_free": True}}})
    assert price_tracker.fetch_price(42) is None


def test_fetch_price_returns_none_on_network_error(monkeypatch):
    def boom(*a, **kw):
        raise requests.RequestException("kein Netz")
    monkeypatch.setattr(price_tracker.requests, "get", boom)
    assert price_tracker.fetch_price(42) is None
"""Gemeinsame Test-Einstellungen."""

import pytest
import requests


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Sperrt echte HTTP-Anfragen in ALLEN Tests (weder Steam noch Telegram).
    Tests, die Netzwerkverhalten prüfen, ersetzen requests.get/post selbst durch Fakes."""
    def blocked(*args, **kwargs):
        raise requests.ConnectionError("Netzwerk in Tests gesperrt")
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)
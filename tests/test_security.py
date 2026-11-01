"""Regressionstests für die Sicherheits-Findings (Paket 1)."""

import json
import re

import pytest
import requests

import bot_listener
import common


# ---------- Web-App ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    return flaskapp.app.test_client()


def test_cross_site_post_is_rejected(client):
    r = client.post("/add/confirm", data={"name": "x", "appid": "1"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert common.load_games() == []


def test_same_origin_post_is_accepted(client):
    r = client.post("/add/confirm", data={"name": "Spiel", "appid": "1"},
                    headers={"Origin": "http://localhost"})
    assert r.status_code == 302
    assert common.load_games()[0]["appid"] == 1


def test_game_name_cannot_break_out_of_js_string(client):
    payload = "x'+(document.title='PWNED')+'"
    client.post("/add/confirm", data={"name": payload, "appid": "5"})
    page = client.get("/").get_data(as_text=True)

    argument = re.search(r"onsubmit='return confirm\((.*)\);'", page).group(1)
    # Das Argument muss ein einziges, gültiges String-Literal sein, das genau den
    # ursprünglichen Namen enthält -> kein Ausbruch aus dem JavaScript möglich.
    assert json.loads(argument) == payload + " nicht mehr tracken?"


@pytest.mark.parametrize("bad_appid", ["abc", "", "12x", "-5", "1" * 30, "١٢"])
def test_invalid_appid_is_rejected_without_error(client, bad_appid):
    r = client.post("/add/confirm", data={"name": "Spiel", "appid": bad_appid})
    assert r.status_code == 302          # sauberer Redirect statt 500
    assert common.load_games() == []


def test_foreign_image_url_is_dropped_steam_cdn_is_kept(client):
    client.post("/add/confirm", data={"name": "A", "appid": "1",
                                        "image": "https://evil.example/track.png"})
    client.post("/add/confirm", data={"name": "B", "appid": "2",
                                        "image": "https://shared.akamai.steamstatic.com/x/y.jpg"})
    client.post("/add/confirm", data={"name": "C", "appid": "3",
                                        "image": "https://evilsteamstatic.com/y.jpg"})
    images = {g["appid"]: g["image"] for g in common.load_games()}
    assert images[1] is None
    assert images[2] == "https://shared.akamai.steamstatic.com/x/y.jpg"
    assert images[3] is None


# ---------- Bot-Token darf nicht in Fehlermeldungen auftauchen ----------

def test_safe_error_never_contains_url_or_token():
    exc = requests.HTTPError("409 Client Error: Conflict for url: "
                                "https://api.telegram.org/bot123456:GEHEIM/getUpdates")
    text = common.safe_error(exc)
    assert "GEHEIM" not in text and "telegram" not in text
    assert text == "HTTPError"


def test_send_telegram_failure_does_not_print_token(monkeypatch, capsys):
    def boom(*a, **k):
        raise requests.ConnectionError("failed for https://api.telegram.org/bot123456:GEHEIM/sendMessage")
    monkeypatch.setattr(common.requests, "post", boom)
    common.send_telegram("123456:GEHEIM", "1", "hallo")
    assert "GEHEIM" not in capsys.readouterr().out


def test_get_updates_failure_does_not_leak_token(monkeypatch, capsys, caplog):
    def boom(*a, **k):
        raise requests.ConnectionError("failed for https://api.telegram.org/bot123456:GEHEIM/getUpdates")
    monkeypatch.setattr(bot_listener.requests, "get", boom)
    assert bot_listener.get_updates("123456:GEHEIM") == []
    assert "GEHEIM" not in capsys.readouterr().out
    assert "GEHEIM" not in caplog.text
    assert "getUpdates fehlgeschlagen" in caplog.text    # es wird aber protokolliert
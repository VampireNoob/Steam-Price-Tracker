"""Neu hinzugefügte Spiele bekommen sofort einen Preis (Web, Bot, Konsole)."""

import pytest

import bot_listener
import common
import manage_games
import price_tracker


def steam_price(cents=999, discount=75):
    return {"price_cents": cents, "initial_cents": 3999,
            "discount_percent": discount, "currency": "EUR"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    return {"sent": sent, "monkeypatch": monkeypatch}


# ---------- record_initial_price ----------

def test_record_initial_price_saves_price(env):
    env["monkeypatch"].setattr(price_tracker, "fetch_price", lambda appid: steam_price())
    assert price_tracker.record_initial_price({"name": "Spiel", "appid": 1}) is True
    assert common.get_latest_price(1)["price"] == "9,99 €"


def test_record_initial_price_returns_false_without_price_data(env):
    env["monkeypatch"].setattr(price_tracker, "fetch_price", lambda appid: None)
    assert price_tracker.record_initial_price({"name": "Spiel", "appid": 1}) is False
    assert common.get_latest_price(1) is None


def test_record_initial_price_never_raises(env):
    def boom(appid):
        raise RuntimeError("unerwartet")
    env["monkeypatch"].setattr(price_tracker, "fetch_price", boom)
    assert price_tracker.record_initial_price({"name": "Spiel", "appid": 1}) is False


# ---------- Web ----------

@pytest.fixture
def client(env):
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    return flaskapp.app.test_client()


def test_web_add_shows_price_immediately(client, env):
    env["monkeypatch"].setattr(price_tracker, "fetch_price", lambda appid: steam_price())
    client.post("/add/confirm", data={"name": "Neues Spiel", "appid": "7"})
    page = client.get("/").get_data(as_text=True)
    assert "9,99 €" in page and "-75%" in page
    assert "noch nicht geprüft" not in page


def test_web_add_still_works_when_steam_has_no_price(client, env):
    env["monkeypatch"].setattr(price_tracker, "fetch_price", lambda appid: None)
    r = client.post("/add/confirm", data={"name": "Bundle", "appid": "8"})
    assert r.status_code == 302
    assert "noch nicht geprüft" in client.get("/").get_data(as_text=True)


# ---------- Bot ----------

def test_bot_pick_reports_current_price(env):
    mp = env["monkeypatch"]
    mp.setattr(price_tracker, "fetch_price", lambda appid: steam_price())
    mp.setattr(bot_listener, "pending_results", [{"name": "Spiel", "appid": 3, "image": None}])
    bot_listener.handle_pick("t", "c", "1")
    assert env["sent"] == ["✅ 'Spiel' wird jetzt getrackt. Aktuell: 9,99 € (-75%)"]


def test_bot_pick_without_price_keeps_old_message(env):
    mp = env["monkeypatch"]
    mp.setattr(price_tracker, "fetch_price", lambda appid: None)
    mp.setattr(bot_listener, "pending_results", [{"name": "Spiel", "appid": 3, "image": None}])
    bot_listener.handle_pick("t", "c", "1")
    assert env["sent"] == ["✅ 'Spiel' wird jetzt getrackt."]


# ---------- Konsole ----------

def test_console_add_prints_current_price(env, capsys):
    mp = env["monkeypatch"]
    mp.setattr(price_tracker, "fetch_price", lambda appid: steam_price(2999, 0))
    mp.setattr(common, "search_steam_games",
                lambda term: [{"name": "Spiel", "appid": 4, "image": None}])
    answers = iter(["spiel", "1"])
    mp.setattr("builtins.input", lambda prompt="": next(answers))

    manage_games.add_game("t", "c")
    out = capsys.readouterr().out
    assert "wurde hinzugefügt" in out
    assert "Aktueller Preis: 29,99 €" in out
"""Gemeinsame Listenfunktionen (Commit 10): Hinzufügen und Entfernen an einer Stelle."""

import json

import pytest

import bot_listener
import common
import manage_games
import price_tracker


@pytest.fixture
def gf(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    return tmp_path / "games.json"


def names():
    return [g["name"] for g in common.load_games()]


# ---------- common.add_game ----------

def test_add_game_stores_a_new_game(gf):
    game, is_new = common.add_game("Spiel", 42, "https://x/y.jpg")
    assert is_new is True
    assert game == {"name": "Spiel", "appid": 42, "image": "https://x/y.jpg"}
    assert common.load_games() == [game]


def test_add_game_without_image_stores_none(gf):
    common.add_game("Spiel", 42)
    assert common.load_games() == [{"name": "Spiel", "appid": 42, "image": None}]


def test_add_game_appends_and_keeps_existing_entries(gf):
    common.save_games([{"name": "Alt", "appid": 1, "zielpreis": 20}])
    common.add_game("Neu", 2)
    assert common.load_games() == [{"name": "Alt", "appid": 1, "zielpreis": 20},
                                   {"name": "Neu", "appid": 2, "image": None}]


def test_add_game_duplicate_returns_existing_and_does_not_touch_the_file(gf, monkeypatch):
    common.add_game("Original", 7)
    before = gf.read_bytes()
    saved = []
    monkeypatch.setattr(common, "save_games", lambda games: saved.append(games))

    game, is_new = common.add_game("Anderer Name", 7)

    assert is_new is False
    assert game["name"] == "Original"            # der vorhandene Eintrag, nicht der neue Name
    assert saved == [] and gf.read_bytes() == before


def test_add_game_into_a_broken_file_keeps_the_broken_copy(gf):
    gf.write_text("kaputt", encoding="utf-8")
    game, is_new = common.add_game("Neu", 1)
    assert is_new and names() == ["Neu"]
    assert gf.with_name("games.json.broken").read_text(encoding="utf-8") == "kaputt"


# ---------- common.remove_game ----------

def test_remove_game_returns_the_removed_game_and_keeps_the_others_in_order(gf):
    for i, n in enumerate("ABC", start=1):
        common.add_game(n, i)
    removed = common.remove_game(2)
    assert removed["name"] == "B"
    assert names() == ["A", "C"]


def test_remove_unknown_game_returns_none_and_does_not_write(gf, monkeypatch):
    common.add_game("A", 1)
    saved = []
    monkeypatch.setattr(common, "save_games", lambda games: saved.append(games))
    assert common.remove_game(999) is None
    assert saved == [] and names() == ["A"]


def test_remove_from_empty_or_missing_file(gf):
    assert common.remove_game(1) is None


# ---------- Web ----------

@pytest.fixture
def client(gf, monkeypatch):
    monkeypatch.setattr(price_tracker, "record_initial_price", lambda game: calls.append(game))
    calls = []
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    c = flaskapp.app.test_client()
    c.price_calls = calls
    return c


def test_web_adding_twice_reports_already_tracked_and_fetches_price_once(client):
    client.post("/add/confirm", data={"name": "Spiel", "appid": "5"})
    page = client.post("/add/confirm", data={"name": "Spiel", "appid": "5"},
                       follow_redirects=True).get_data(as_text=True)
    assert "bereits getrackt" in page
    assert names() == ["Spiel"]
    assert len(client.price_calls) == 1                  # nur beim ersten Mal


def test_web_remove_shows_confirmation_and_removes(client):
    client.post("/add/confirm", data={"name": "Spiel", "appid": "5"})
    page = client.post("/remove/5", follow_redirects=True).get_data(as_text=True)
    assert "wurde entfernt" in page
    assert names() == []


def test_web_remove_of_unknown_game_is_harmless(client, gf):
    client.post("/add/confirm", data={"name": "Spiel", "appid": "5"})
    before = gf.read_bytes()
    r = client.post("/remove/999")
    assert r.status_code == 302 and gf.read_bytes() == before


# ---------- Bot ----------

@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: messages.append(text))
    return messages


def test_bot_remove_uses_the_games_appid_not_just_the_position(gf, sent, monkeypatch):
    for i, n in enumerate("ABC", start=1):
        common.add_game(n, i * 10)
    seen = []
    real_remove = common.remove_game
    monkeypatch.setattr(common, "remove_game", lambda appid: (seen.append(appid), real_remove(appid))[1])

    bot_listener.handle_remove("tok", "1", "2")

    assert seen == [20]                                  # die AppID von "B"
    assert names() == ["A", "C"]


def test_bot_remove_reports_when_the_game_vanished_in_the_meantime(gf, sent, monkeypatch):
    common.add_game("A", 1)
    monkeypatch.setattr(common, "remove_game", lambda appid: None)
    bot_listener.handle_remove("tok", "1", "1")
    assert sent == ["Dieses Spiel ist nicht mehr in der Liste."]


def test_bot_pick_of_a_tracked_game_does_not_fetch_a_price(gf, sent, monkeypatch):
    common.add_game("Schon da", 100)
    calls = []
    monkeypatch.setattr(price_tracker, "record_initial_price", lambda game: calls.append(game))
    monkeypatch.setattr(bot_listener, "pending_results", [{"name": "Schon da", "appid": 100, "image": None}])
    bot_listener.handle_pick("tok", "1", "1")
    assert sent == ["'Schon da' wird bereits getrackt."] and calls == []


# ---------- Konsole ----------

@pytest.fixture
def console(gf, sent, monkeypatch):
    answers = []
    monkeypatch.setattr("builtins.input", lambda prompt="": answers.pop(0))
    monkeypatch.setattr(price_tracker, "record_initial_price", lambda game: False)
    return answers


def test_console_add_of_a_tracked_game_is_reported(console, sent, monkeypatch, capsys):
    common.add_game("Schon da", 100)
    monkeypatch.setattr(common, "search_steam_games",
                        lambda term: [{"name": "Schon da", "appid": 100, "image": None}])
    console.extend(["schon", "1"])
    manage_games.add_game("tok", "1")
    assert "wird bereits getrackt" in capsys.readouterr().out
    assert len(common.load_games()) == 1 and sent == []


def test_console_add_stores_the_game_and_notifies_telegram(console, sent, monkeypatch):
    monkeypatch.setattr(common, "search_steam_games",
                        lambda term: [{"name": "Neu", "appid": 5, "image": "https://x/i.jpg"}])
    console.extend(["neu", "1"])
    manage_games.add_game("tok", "1")
    assert common.load_games() == [{"name": "Neu", "appid": 5, "image": "https://x/i.jpg"}]
    assert sent == ["➕ 'Neu' wird jetzt getrackt."]


def test_console_remove_deletes_the_chosen_game_and_notifies_telegram(console, sent, capsys):
    for i, n in enumerate("ABC", start=1):
        common.add_game(n, i)
    console.append("2")
    manage_games.remove_game("tok", "1")
    assert names() == ["A", "C"]
    assert "'B' wurde entfernt" in capsys.readouterr().out
    assert sent == ["➖ 'B' wird nicht mehr getrackt."]


@pytest.mark.parametrize("answer", ["", "0", "4", "abc"])
def test_console_remove_with_invalid_input_changes_nothing(console, sent, capsys, answer):
    for i, n in enumerate("ABC", start=1):
        common.add_game(n, i)
    console.append(answer)
    manage_games.remove_game("tok", "1")
    assert names() == ["A", "B", "C"]
    assert "Abgebrochen" in capsys.readouterr().out and sent == []


def test_console_remove_with_empty_list_asks_nothing(console, sent):
    manage_games.remove_game("tok", "1")          # würde bei input() sonst IndexError werfen
    assert sent == []


def test_console_remove_reports_when_the_game_vanished(console, sent, monkeypatch, capsys):
    common.add_game("A", 1)
    monkeypatch.setattr(common, "remove_game", lambda appid: None)
    console.append("1")
    manage_games.remove_game("tok", "1")
    assert "nicht mehr in der Liste" in capsys.readouterr().out and sent == []
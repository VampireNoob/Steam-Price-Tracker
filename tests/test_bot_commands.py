"""Die Befehle des Bots (Commit 6): Parser, Handler und Zugriffsschutz."""

import json
import logging
import sqlite3

import pytest

import bot_listener
import common
import price_tracker

OWNER = 111


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    monkeypatch.setattr(bot_listener, "pending_results", [])
    monkeypatch.setattr(price_tracker, "record_initial_price", lambda game: False)
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    checks = []
    monkeypatch.setattr(price_tracker, "run", lambda: checks.append(1))

    class Bot:
        pass
    b = Bot()
    b.sent, b.checks, b.monkeypatch = sent, checks, monkeypatch
    b.say = lambda text, chat=OWNER: bot_listener.process_message(
        "tok", str(OWNER), {"chat": {"id": chat}, "text": text})
    return b


def games():
    return common.load_games()


def set_games(*names):
    common.save_games([{"name": n, "appid": i + 1} for i, n in enumerate(names)])


def put_price(appid, cents, discount):
    conn = price_tracker.init_db()
    price_tracker.save_price(conn, appid, "x", cents, discount)
    conn.close()


# ---------- parse_command ----------

@pytest.mark.parametrize("text, expected", [
    ("/list", ("/list", "")),
    ("/add Forza Horizon 5", ("/add", "Forza Horizon 5")),
    ("/Add@MeinBot   Forza 5 ", ("/add", "Forza 5")),
    ("/LIST", ("/list", "")),
    ("/remove 2", ("/remove", "2")),
    ("/addfoo bar", ("/addfoo", "bar")),      # kein /add!
    ("3", (None, "3")),
    ("hallo", (None, "hallo")),
])
def test_parse_command(text, expected):
    assert bot_listener.parse_command(text) == expected


def test_similar_looking_command_is_not_treated_as_add(bot):
    bot.say("/addfoo Kenshi")
    assert bot.sent == ["Unbekannter Befehl. /help für Übersicht."]
    assert bot_listener.pending_results == []


def test_bot_name_suffix_is_removed_from_the_search_term(bot, monkeypatch):
    terms = []
    monkeypatch.setattr(common, "search_steam_games", lambda term: terms.append(term) or [])
    bot.say("/add@MeinBot Kenshi")
    assert terms == ["Kenshi"]


def test_commands_are_case_insensitive(bot):
    bot.say("/HELP")
    assert any("Verfügbare Befehle" in m for m in bot.sent)


def test_non_command_text_is_logged_without_content(bot, caplog):
    caplog.set_level(logging.INFO)
    bot.say("mein geheimer Text")
    assert "Befehl empfangen: (Text)" in caplog.text
    assert "geheimer" not in caplog.text


# ---------- /list ----------

def test_list_with_no_games(bot):
    bot.say("/list")
    assert bot.sent == ["Aktuell werden keine Spiele getrackt."]


def test_list_shows_prices_discounts_and_unchecked_games(bot):
    set_games("Mit Rabatt", "Ohne Rabatt", "Neu")
    put_price(1, 999, 75)
    put_price(2, 2999, 0)
    bot.say("/list")
    assert bot.sent == ["Getrackte Spiele:\n"
                        "1. Mit Rabatt -- 9,99 € (-75%)\n"
                        "2. Ohne Rabatt -- 29,99 €\n"
                        "3. Neu -- noch nicht geprüft"]


# ---------- /add und Nummer wählen ----------

def results(*names):
    return [{"name": n, "appid": 100 + i, "image": None} for i, n in enumerate(names)]


def test_add_without_name_gives_a_hint(bot):
    bot.say("/add")
    assert "Bitte einen Namen angeben" in bot.sent[0]


def test_add_without_results_clears_old_search(bot, monkeypatch):
    bot.monkeypatch.setattr(bot_listener, "pending_results", results("Alt"))
    monkeypatch.setattr(common, "search_steam_games", lambda term: [])
    bot.say("/add gibtsnicht")
    assert bot.sent == ["Keine Treffer für 'gibtsnicht'."]
    assert bot_listener.pending_results == []


def test_add_lists_results_with_numbers(bot, monkeypatch):
    monkeypatch.setattr(common, "search_steam_games", lambda term: results("Erstes", "Zweites"))
    bot.say("/add spiel")
    assert bot.sent == ["Treffer:\n1. Erstes\n2. Zweites\n\nAntworte mit der Nummer, um hinzuzufügen."]


def test_picking_a_number_adds_the_right_game(bot, monkeypatch):
    monkeypatch.setattr(common, "search_steam_games", lambda term: results("Erstes", "Zweites"))
    bot.say("/add spiel")
    bot.sent.clear()
    bot.say("2")
    assert [g["name"] for g in games()] == ["Zweites"]
    assert bot.sent == ["✅ 'Zweites' wird jetzt getrackt."]
    assert bot_listener.pending_results == []        # Auswahl ist verbraucht


def test_number_without_open_search_gives_a_hint(bot):
    bot.say("1")
    assert bot.sent == ["Keine offene Suche. Erst /add <Name> verwenden."]
    assert games() == []


@pytest.mark.parametrize("bad", ["0", "3", "99"])
def test_invalid_number_keeps_the_search_open(bot, bad):
    bot.monkeypatch.setattr(bot_listener, "pending_results", results("A", "B"))
    bot.say(bad)
    assert bot.sent == ["Ungültige Nummer."]
    assert len(bot_listener.pending_results) == 2
    assert games() == []


def test_adding_an_already_tracked_game_is_reported(bot):
    common.save_games([{"name": "Schon da", "appid": 100}])
    bot.monkeypatch.setattr(bot_listener, "pending_results", results("Schon da"))
    bot.say("1")
    assert bot.sent == ["'Schon da' wird bereits getrackt."]
    assert len(games()) == 1


# ---------- /remove ----------

def test_remove_with_no_games(bot):
    bot.say("/remove 1")
    assert bot.sent == ["Aktuell werden keine Spiele getrackt."]


def test_remove_deletes_the_chosen_game_only(bot):
    set_games("A", "B", "C")
    bot.say("/remove 2")
    assert [g["name"] for g in games()] == ["A", "C"]
    assert bot.sent == ["➖ 'B' wird nicht mehr getrackt."]


@pytest.mark.parametrize("arg", ["", "0", "4", "abc", "-1"])
def test_remove_with_invalid_number_shows_the_list_and_changes_nothing(bot, arg):
    set_games("A", "B", "C")
    bot.say(f"/remove {arg}")
    assert bot.sent == ["Bitte /remove <Nummer> verwenden:\n1. A\n2. B\n3. C"]
    assert len(games()) == 3


# ---------- /help, /start, Unbekanntes ----------

@pytest.mark.parametrize("cmd", ["/help", "/start"])
def test_help_and_start_show_the_command_overview(bot, cmd):
    bot.say(cmd)
    assert "/list" in bot.sent[0] and "/add" in bot.sent[0] and "/check" in bot.sent[0]


@pytest.mark.parametrize("text", ["/foo", "hallo", "/", "12abc"])
def test_unknown_input_gets_the_hint(bot, text):
    bot.say(text)
    assert bot.sent == ["Unbekannter Befehl. /help für Übersicht."]


def test_empty_message_is_ignored(bot):
    bot.say("   ")
    assert bot.sent == []


# ---------- Zugriffsschutz ----------

@pytest.mark.parametrize("text", ["/list", "/remove 1", "/add Kenshi", "/check", "1", "/help"])
def test_strangers_can_do_nothing(bot, monkeypatch, text):
    set_games("Meins")
    monkeypatch.setattr(common, "search_steam_games", lambda term: results("X"))
    bot.monkeypatch.setattr(bot_listener, "pending_results", results("X"))

    bot.say(text, chat=999)

    assert bot.sent == []                             # keine Antwort
    assert [g["name"] for g in games()] == ["Meins"]  # nichts verändert
    assert bot.checks == []                           # kein Preis-Check gestartet


def test_group_chat_ids_with_minus_sign_work_when_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    bot_listener.process_message("tok", "-100123", {"chat": {"id": -100123}, "text": "/list"})
    assert sent == ["Aktuell werden keine Spiele getrackt."]
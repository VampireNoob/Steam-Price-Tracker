"""games.json wird beim Laden geprüft (Commit 9): Fehler in der Datei stürzen nichts ab."""

import json
import logging

import pytest

import bot_listener
import common


@pytest.fixture
def gf(tmp_path, monkeypatch):
    """Gibt den Pfad zur Test-games.json zurück (alles liegt im tmp-Ordner)."""
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    return tmp_path / "games.json"


def write(gf, data):
    gf.write_text(json.dumps(data), encoding="utf-8")


# ---------- gültige Dateien bleiben unverändert ----------

def test_missing_file_gives_empty_list(gf):
    assert common.load_games() == []


def test_valid_entries_are_returned_unchanged(gf):
    entries = [{"name": "A", "appid": 1, "image": "https://x/y.jpg"},
                {"name": "B", "appid": 2, "image": None},
                {"name": "C", "appid": 3}]
    write(gf, entries)
    assert common.load_games() == entries


def test_unknown_extra_fields_are_kept(gf):
    write(gf, [{"name": "A", "appid": 1, "zielpreis": 20}])
    assert common.load_games() == [{"name": "A", "appid": 1, "zielpreis": 20}]


def test_empty_list_and_empty_file_both_mean_no_games(gf):
    write(gf, [])
    assert common.load_games() == []
    gf.write_text("  \n", encoding="utf-8")
    assert common.load_games() == []
    assert gf.exists()                        # leere Datei wird NICHT als defekt behandelt


# ---------- ungültige Einträge werden übersprungen ----------

GOOD = {"name": "Gut", "appid": 99}


@pytest.mark.parametrize("bad", [
    {"name": "Ohne AppID"},
    {"appid": 5},
    "kein Objekt",
    None,
    5,
    [],
    {"name": "", "appid": 1},
    {"name": "   ", "appid": 1},
    {"name": 5, "appid": 1},
    {"name": "x", "appid": 0},
    {"name": "x", "appid": -3},
    {"name": "x", "appid": True},
    {"name": "x", "appid": 1.5},
    {"name": "x", "appid": ""},
    {"name": "x", "appid": "abc"},
    {"name": "x", "appid": None},
])
def test_invalid_entries_are_skipped_and_logged(gf, caplog, bad):
    write(gf, [bad, GOOD])
    assert common.load_games() == [GOOD]
    assert "Eintrag 0 übersprungen" in caplog.text


def test_appid_in_quotes_is_converted_to_a_number(gf):
    write(gf, [{"name": "A", "appid": "123"}, {"name": "B", "appid": " 45 "}])
    assert [g["appid"] for g in common.load_games()] == [123, 45]


def test_name_is_stripped(gf):
    write(gf, [{"name": "  Spiel  ", "appid": 1}])
    assert common.load_games()[0]["name"] == "Spiel"


def test_image_of_wrong_type_becomes_none(gf):
    write(gf, [{"name": "A", "appid": 1, "image": 42}, {"name": "B", "appid": 2, "image": "u"}])
    assert [g["image"] for g in common.load_games()] == [None, "u"]


def test_duplicate_appid_keeps_the_first_entry(gf, caplog):
    write(gf, [{"name": "Erst", "appid": 1}, {"name": "Doppelt", "appid": 1}])
    assert common.load_games() == [{"name": "Erst", "appid": 1}]
    assert "doppelt" in caplog.text


# ---------- komplett defekte Datei ----------

def test_broken_json_is_set_aside_and_not_overwritten_later(gf, caplog):
    gf.write_text('[{"name": "Wichtig", "appid": 1},', encoding="utf-8")    # abgeschnitten
    original = gf.read_text(encoding="utf-8")

    assert common.load_games() == []
    broken = gf.with_name("games.json.broken")
    assert broken.read_text(encoding="utf-8") == original      # Inhalt gerettet
    assert not gf.exists()
    assert "beiseitegelegt" in caplog.text

    common.save_games([{"name": "Neu", "appid": 2}])           # späteres Speichern ...
    assert broken.read_text(encoding="utf-8") == original      # ... zerstört die Kopie nicht


@pytest.mark.parametrize("content", [
    '{"name": "kein", "appid": 1}',      # Objekt statt Liste
    '"nur Text"',
    "kein json",
])
def test_file_with_wrong_structure_is_set_aside(gf, content):
    gf.write_text(content, encoding="utf-8")
    assert common.load_games() == []
    assert gf.with_name("games.json.broken").exists()


def test_utf16_file_from_powershell_is_set_aside_without_crashing(gf):
    gf.write_bytes('[{"name": "A", "appid": 1}]'.encode("utf-16"))     # wie 'echo ... > games.json'
    assert common.load_games() == []
    assert gf.with_name("games.json.broken").exists()


def test_utf8_file_with_bom_is_read_normally(gf):
    gf.write_bytes(b"\xef\xbb\xbf" + json.dumps([{"name": "A", "appid": 1}]).encode("utf-8"))
    assert common.load_games() == [{"name": "A", "appid": 1}]
    assert gf.exists()                                  # NICHT fälschlich als defekt weggelegt


# ---------- die Anwendungen stürzen nicht ab ----------

def test_web_page_survives_a_broken_games_file(gf):
    write(gf, [{"name": "Gut", "appid": 1}, {"name": "Ohne AppID"}, "Müll", None])
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    page = flaskapp.app.test_client().get("/")
    assert page.status_code == 200
    assert "Gut" in page.get_data(as_text=True)


def test_web_page_survives_unreadable_games_file(gf):
    gf.write_text("kein json", encoding="utf-8")
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    assert flaskapp.app.test_client().get("/").status_code == 200


def test_bot_list_survives_a_broken_games_file(gf, monkeypatch):
    write(gf, [{"name": "Gut", "appid": 1}, {"appid": 2}])
    sent = []
    monkeypatch.setattr(common, "send_telegram", lambda t, c, text: sent.append(text))
    bot_listener.process_message("tok", "1", {"chat": {"id": 1}, "text": "/list"})
    assert sent == ["Getrackte Spiele:\n1. Gut -- noch nicht geprüft"]
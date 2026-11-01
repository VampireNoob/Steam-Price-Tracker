"""Zeitanzeige in lokaler Zeit statt UTC (Commit 8)."""

from datetime import datetime, timedelta, timezone

import pytest

import common
import price_tracker

SOMMERZEIT = timezone(timedelta(hours=2))     # wie MESZ, ohne tzdata (fehlt unter Windows)
WINTERZEIT = timezone(timedelta(hours=1))     # wie MEZ


@pytest.mark.parametrize("utc_text, tz, expected", [
    ("2026-07-27T12:49:00+00:00", SOMMERZEIT, "27.07.2026 14:49"),
    ("2026-11-01T12:49:00+00:00", WINTERZEIT, "01.11.2026 13:49"),
    ("2026-12-31T23:30:00+00:00", WINTERZEIT, "01.01.2027 00:30"),      # Tageswechsel
    ("2026-07-27T12:49:00.123456+00:00", SOMMERZEIT, "27.07.2026 14:49"),  # Mikrosekunden
    ("2026-07-27T12:49:00Z", SOMMERZEIT, "27.07.2026 14:49"),           # 'Z'-Schreibweise
])
def test_utc_is_converted_to_the_given_timezone(utc_text, tz, expected):
    assert common.format_local_time(utc_text, tz) == expected


def test_text_without_timezone_is_treated_as_utc():
    assert common.format_local_time("2026-07-27T12:49:00", SOMMERZEIT) == "27.07.2026 14:49"


@pytest.mark.parametrize("empty", [None, ""])
def test_missing_timestamp_gives_none(empty):
    assert common.format_local_time(empty) is None


@pytest.mark.parametrize("broken", ["kaputt", "2026-13-45", "12:49"])
def test_broken_timestamp_is_shown_raw_instead_of_crashing(broken):
    assert common.format_local_time(broken) == broken


def test_without_tz_the_computers_timezone_is_used():
    iso = "2026-07-27T12:49:00+00:00"
    expected = datetime.fromisoformat(iso).astimezone().strftime("%d.%m.%Y %H:%M")
    assert common.format_local_time(iso) == expected


# ---------- Web-Oberfläche ----------

def test_web_page_shows_local_time_not_raw_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    common.save_games([{"name": "Spiel", "appid": 1}])
    conn = price_tracker.init_db()
    conn.execute(
        "INSERT INTO price_history (appid, name, price_cents, discount_percent, checked_at) "
        "VALUES (1, 'Spiel', 999, 0, '2026-07-27T12:49:00+00:00')")
    conn.commit()
    conn.close()

    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    page = flaskapp.app.test_client().get("/").get_data(as_text=True)

    expected = datetime.fromisoformat("2026-07-27T12:49:00+00:00").astimezone().strftime("%d.%m.%Y %H:%M")
    assert expected in page
    assert "2026-07-27 12:49" not in page and "T12:49" not in page   # kein Roh-Format mehr


def test_web_page_still_says_not_checked_yet_for_new_games(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "GAMES_FILE", tmp_path / "games.json")
    monkeypatch.setattr(common, "DB_FILE", tmp_path / "prices.db")
    common.save_games([{"name": "Neu", "appid": 2}])
    import app as flaskapp
    flaskapp.app.config["TESTING"] = True
    page = flaskapp.app.test_client().get("/").get_data(as_text=True)
    assert "noch nicht geprüft" in page
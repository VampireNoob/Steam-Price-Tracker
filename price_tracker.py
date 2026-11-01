"""
Steam-Preis-Tracker mit Telegram-Benachrichtigung
--------------------------------------------------
Prüft die aktuellen Preise der in games.json eingetragenen Spiele
(siehe manage_games.py zum Pflegen dieser Liste), vergleicht sie mit dem
zuletzt gespeicherten Preis (SQLite) und schickt bei Änderungen eine
Telegram-Nachricht.

Gedacht für regelmäßige Ausführung per Windows-Aufgabenplanung
(ein Skriptlauf = eine Prüfung aller Spiele, dann Programmende).

Jeder Lauf wird zusätzlich in tracker.log protokolliert (auch Fehler) --
wichtig, weil bei automatischen Läufen über die Aufgabenplanung niemand
die Konsolenausgabe sieht.
"""

import logging
from logging.handlers import RotatingFileHandler
import sqlite3
from datetime import datetime, timezone

import requests

import common

STEAM_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
LOG_FILE = common.BASE_DIR / "tracker.log"

log = logging.getLogger("price_tracker")
_logging_ready = False


def setup_logging():
    """Richtet das Logging ein: tracker.log (mit Rotation) und Konsole. Wird nur von den
    Programmen selbst aufgerufen (price_tracker.py, app.py, bot_listener.py), NICHT beim
    Import -- sonst würden z.B. Tests in die echte tracker.log schreiben."""
    global _logging_ready
    if _logging_ready:
        return
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    console_handler = logging.StreamHandler()
    root = logging.getLogger()
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    _logging_ready = True


def init_db():
    conn = sqlite3.connect(common.DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appid INTEGER NOT NULL,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            discount_percent INTEGER NOT NULL,
            checked_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def fetch_price(appid: int):
    params = {"appids": appid, "cc": common.COUNTRY_CODE, "filters": "price_overview"}
    try:
        resp = requests.get(STEAM_DETAILS_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()          # kann ValueError werfen (z.B. HTML statt JSON)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Anfrage für appid %s fehlgeschlagen: %s", appid, common.safe_error(exc))
        return None

    entry = data.get(str(appid), {}) if isinstance(data, dict) else {}
    if not isinstance(entry, dict) or not entry.get("success"):
        log.warning("Steam meldet 'success: false' für appid %s", appid)
        return None

    game_data = entry.get("data")
    if not isinstance(game_data, dict):
        # Steam liefert für manche AppIDs (z.B. Bundles/Sonderfälle) statt
        # eines Objekts eine leere Liste o.ä. zurück -- dann gibt es keine
        # brauchbaren Preisdaten, kein Grund zum Absturz.
        log.warning(f"Unerwartetes 'data'-Format für appid {appid} ({type(game_data).__name__}) -- übersprungen")
        return None

    overview = game_data.get("price_overview")
    if overview is None:
        log.info(f"Kein price_overview für appid {appid} (z.B. kostenlos/regional nicht gelistet)")
        return None

    return {
        "price_cents": overview["final"],
        "initial_cents": overview["initial"],
        "discount_percent": overview["discount_percent"],
        "currency": overview["currency"],
    }


def last_known_price(conn, appid: int):
    row = conn.execute(
        "SELECT price_cents, discount_percent FROM price_history "
        "WHERE appid = ? ORDER BY id DESC LIMIT 1",
        (appid,),
    ).fetchone()
    return row


def save_price(conn, appid: int, name: str, price_cents: int, discount_percent: int):
    conn.execute(
        "INSERT INTO price_history (appid, name, price_cents, discount_percent, checked_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (appid, name, price_cents, discount_percent, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def format_price(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")

def price_direction(previous_cents: int, current_cents: int):
    """Gibt 'gefallen', 'gestiegen' oder None (keine Änderung) zurück."""
    if current_cents == previous_cents:
        return None
    return "gefallen" if current_cents < previous_cents else "gestiegen"


def build_change_message(name: str, previous_cents: int, current: dict):
    """Baut die Telegram-Meldung für eine Preisänderung.
    Gibt None zurück, wenn sich der Preis nicht geändert hat."""
    direction = price_direction(previous_cents, current["price_cents"])
    if direction is None:
        return None
    msg = (
        f"💰 {name}\n"
        f"Preis {direction}: {format_price(previous_cents)} → "
        f"{format_price(current['price_cents'])}"
    )
    if current["discount_percent"] > 0:
        msg += f"\nAktueller Rabatt: -{current['discount_percent']}%"
    return msg


def record_initial_price(game: dict) -> bool:
    """Holt den Preis eines neu hinzugefügten Spiels sofort und speichert ihn,
    damit es nicht bis zum nächsten Check 'noch nicht geprüft' zeigt.
    Es wird keine Telegram-Nachricht gesendet. Gibt True zurück, wenn ein Preis
    gespeichert wurde. Fehler führen nie zu einem Absturz des Aufrufers."""
    try:
        current = fetch_price(game["appid"])
        if current is None:
            return False
        conn = init_db()
        try:
            save_price(conn, game["appid"], game["name"],
                        current["price_cents"], current["discount_percent"])
        finally:
            conn.close()
        return True
    except Exception:
        log.exception("Sofort-Preis für %r konnte nicht gespeichert werden", game.get("name"))
        return False


def _check_game(conn, game):
    """Prüft ein Spiel und speichert den Preis.
    Gibt die Telegram-Meldung zurück, wenn sich der Preis geändert hat, sonst None."""
    name, appid = game["name"], game["appid"]
    log.info("Prüfe: %s (%s)", name, appid)
    current = fetch_price(appid)
    if current is None:
        return None

    previous = last_known_price(conn, appid)
    save_price(conn, appid, name, current["price_cents"], current["discount_percent"])

    if previous is None:
        log.info("  Erster Datensatz: %s (-%s%%)",
                    format_price(current["price_cents"]), current["discount_percent"])
        return None

    msg = build_change_message(name, previous[0], current)
    if msg:
        log.info("  Änderung erkannt -> Telegram wird benachrichtigt")
    else:
        log.info("  Keine Änderung (%s)", format_price(current["price_cents"]))
    return msg


def run():
    log.info("=== Lauf gestartet ===")
    token, chat_id = common.load_config()
    games = common.load_games()
    if not games:
        log.warning("Keine Spiele in games.json. Erst mit manage_games.py welche hinzufügen.")
        return

    changed_messages = []
    conn = init_db()
    try:
        for game in games:
            try:
                msg = _check_game(conn, game)
            except Exception:
                # Ein defekter Eintrag darf nicht den Lauf für alle anderen abbrechen.
                log.exception("Fehler bei Eintrag %r -- übersprungen", game)
                continue
            if msg:
                changed_messages.append(msg)
    finally:
        conn.close()

    if changed_messages:
        common.send_telegram(token, chat_id, "\n\n".join(changed_messages))
        log.info("Telegram-Nachricht gesendet (%d Änderung(en))", len(changed_messages))
    else:
        log.info("Keine Preisänderungen, keine Nachricht gesendet.")

    log.info("=== Lauf beendet ===")


def main():
    setup_logging()
    try:
        run()
    except Exception:
        log.exception("Unerwarteter Fehler -- Lauf abgebrochen")
        raise


if __name__ == "__main__":
    main()
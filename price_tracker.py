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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("price_tracker")


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
    except requests.RequestException as exc:
        log.warning("Anfrage für appid %s fehlgeschlagen: %s", appid, exc)
        return None

    data = resp.json()
    entry = data.get(str(appid), {})
    if not entry.get("success"):
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


def run():
    log.info("=== Lauf gestartet ===")
    token, chat_id = common.load_config()
    games = common.load_games()
    if not games:
        log.warning("Keine Spiele in games.json. Erst mit manage_games.py welche hinzufügen.")
        return

    conn = init_db()
    changed_messages = []

    for game in games:
        name, appid = game["name"], game["appid"]
        log.info("Prüfe: %s (%s)", name, appid)
        current = fetch_price(appid)
        if current is None:
            continue

        previous = last_known_price(conn, appid)
        save_price(conn, appid, name, current["price_cents"], current["discount_percent"])

        if previous is None:
            log.info("  Erster Datensatz: %s (-%s%%)",
                format_price(current["price_cents"]), current["discount_percent"])
            continue

        prev_price_cents, prev_discount = previous
        if current["price_cents"] != prev_price_cents:
            direction = "gefallen" if current["price_cents"] < prev_price_cents else "gestiegen"
            msg = (
                f"💰 {name}\n"
                f"Preis {direction}: {format_price(prev_price_cents)} → "
                f"{format_price(current['price_cents'])}"
            )
            if current["discount_percent"] > 0:
                msg += f"\nAktueller Rabatt: -{current['discount_percent']}%"
            changed_messages.append(msg)
            log.info("  Änderung erkannt -> Telegram wird benachrichtigt")
        else:
            log.info("  Keine Änderung (%s)", format_price(current["price_cents"]))

    conn.close()

    if changed_messages:
        common.send_telegram(token, chat_id, "\n\n".join(changed_messages))
        log.info("Telegram-Nachricht gesendet (%d Änderung(en))", len(changed_messages))
    else:
        log.info("Keine Preisänderungen, keine Nachricht gesendet.")

    log.info("=== Lauf beendet ===")


def main():
    try:
        run()
    except Exception:
        log.exception("Unerwarteter Fehler -- Lauf abgebrochen")
        raise


if __name__ == "__main__":
    main()
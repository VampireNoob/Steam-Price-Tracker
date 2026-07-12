"""
Steam-Preis-Tracker mit Telegram-Benachrichtigung
--------------------------------------------------
Prüft die aktuellen Preise der in games.json eingetragenen Spiele
(siehe manage_games.py zum Pflegen dieser Liste), vergleicht sie mit dem
zuletzt gespeicherten Preis (SQLite) und schickt bei Änderungen eine
Telegram-Nachricht.

Gedacht für regelmäßige Ausführung per Windows-Aufgabenplanung
(ein Skriptlauf = eine Prüfung aller Spiele, dann Programmende).
"""

import sqlite3
from datetime import datetime, timezone

import requests

import common

STEAM_DETAILS_URL = "https://store.steampowered.com/api/appdetails"


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
    """Fragt die (inoffizielle) Steam-Store-API nach dem aktuellen Preis ab.
    Gibt None zurück, wenn z.B. keine Preisdaten verfügbar sind."""
    params = {"appids": appid, "cc": common.COUNTRY_CODE, "filters": "price_overview"}
    try:
        resp = requests.get(STEAM_DETAILS_URL, params=params, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [Warnung] Anfrage für appid {appid} fehlgeschlagen: {exc}")
        return None

    data = resp.json()
    entry = data.get(str(appid), {})
    if not entry.get("success"):
        print(f"  [Warnung] Steam meldet 'success: false' für appid {appid}")
        return None

    overview = entry.get("data", {}).get("price_overview")
    if overview is None:
        return None  # z.B. kostenloses Spiel oder regional nicht gelistet

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


def main():
    token, chat_id = common.load_config()
    games = common.load_games()
    if not games:
        print("Keine Spiele in games.json. Erst mit manage_games.py welche hinzufügen.")
        return

    conn = init_db()
    changed_messages = []

    for game in games:
        name, appid = game["name"], game["appid"]
        print(f"Prüfe: {name} ({appid}) ...")
        current = fetch_price(appid)
        if current is None:
            continue

        previous = last_known_price(conn, appid)
        save_price(conn, appid, name, current["price_cents"], current["discount_percent"])

        if previous is None:
            print(f"  Erster Datensatz: {format_price(current['price_cents'])} "
                  f"(-{current['discount_percent']}%)")
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
            print("  Änderung erkannt -> Telegram wird benachrichtigt")
        else:
            print(f"  Keine Änderung ({format_price(current['price_cents'])})")

    conn.close()

    if changed_messages:
        common.send_telegram(token, chat_id, "\n\n".join(changed_messages))
    else:
        print("Keine Preisänderungen, keine Nachricht gesendet.")


if __name__ == "__main__":
    main()
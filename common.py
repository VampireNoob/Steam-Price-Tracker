"""
Gemeinsam genutzte Funktionen für price_tracker.py, manage_games.py,
bot_listener.py und app.py: Konfiguration laden, games.json lesen/schreiben,
Telegram-Nachrichten senden, Steam-Suche, letzten bekannten Preis abfragen.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
GAMES_FILE = BASE_DIR / "games.json"
DB_FILE = BASE_DIR / "prices.db"
STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
COUNTRY_CODE = "de"
LANGUAGE = "german"


def load_config():
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit(
            "Fehler: TELEGRAM_BOT_TOKEN und/oder TELEGRAM_CHAT_ID fehlen in der .env-Datei. "
            "Siehe .env.example."
        )
    return token, chat_id


def load_games():
    if not GAMES_FILE.exists():
        return []
    with open(GAMES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_games(games):
    with open(GAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False, indent=2)


def send_telegram(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [Warnung] Telegram-Nachricht konnte nicht gesendet werden: {exc}")


def search_steam_games(term: str, max_results: int = 8):
    """Sucht Spiele über die (inoffizielle) Steam-Store-Suche.
    Gibt eine Liste von Treffern zurück:
    [{"name": ..., "appid": ..., "image": <URL oder None>}, ...]"""
    params = {"term": term, "l": LANGUAGE, "cc": COUNTRY_CODE}
    try:
        resp = requests.get(STEAM_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Warnung] Steam-Suche fehlgeschlagen: {exc}")
        return []

    data = resp.json()
    items = data.get("items", [])[:max_results]
    return [
        {"name": item["name"], "appid": item["id"], "image": item.get("tiny_image")}
        for item in items if "id" in item
    ]


def get_latest_price(appid: int):
    """Liest den zuletzt bekannten Preis für ein Spiel aus prices.db.
    Gibt None zurück, wenn noch kein price_tracker.py-Lauf für dieses Spiel
    stattfand (z.B. gerade erst hinzugefügt)."""
    if not DB_FILE.exists():
        return None
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT price_cents, discount_percent, checked_at FROM price_history "
        "WHERE appid = ? ORDER BY id DESC LIMIT 1",
        (appid,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    price_cents, discount_percent, checked_at = row
    return {
        "price": f"{price_cents / 100:.2f} €".replace(".", ","),
        "discount_percent": discount_percent,
        "checked_at": checked_at,
    }
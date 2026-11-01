"""
Gemeinsam genutzte Funktionen für price_tracker.py, manage_games.py,
bot_listener.py und app.py: Konfiguration laden, games.json lesen/schreiben,
Telegram-Nachrichten senden, Steam-Suche, letzten bekannten Preis abfragen.
"""

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
GAMES_FILE = BASE_DIR / "games.json"
DB_FILE = BASE_DIR / "prices.db"
STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
COUNTRY_CODE = "de"
LANGUAGE = "german"

log = logging.getLogger("common")


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


def _normalize_game(entry):
    """Prüft einen Eintrag aus games.json. Gibt den bereinigten Eintrag zurück oder None.
    Unbekannte zusätzliche Felder bleiben erhalten."""
    if not isinstance(entry, dict):
        return None
    name, appid = entry.get("name"), entry.get("appid")
    if not isinstance(name, str) or not name.strip():
        return None
    if isinstance(appid, str) and appid.strip().isascii() and appid.strip().isdecimal():
        appid = int(appid.strip())          # "123" in Anführungszeichen wird zu 123
    if not isinstance(appid, int) or isinstance(appid, bool) or appid <= 0:
        return None
    game = dict(entry)
    game["name"] = name.strip()
    game["appid"] = appid
    if "image" in game and not (game["image"] is None or isinstance(game["image"], str)):
        game["image"] = None
    return game


def _set_aside_broken_file(exc):
    """Defekte games.json beiseitelegen statt sie beim nächsten Speichern zu überschreiben."""
    broken = GAMES_FILE.with_name(GAMES_FILE.name + ".broken")
    try:
        os.replace(GAMES_FILE, broken)
        log.error("games.json ist defekt (%s) und wurde als %s beiseitegelegt", exc, broken.name)
    except OSError:
        log.error("games.json ist defekt (%s) und konnte nicht beiseitegelegt werden", exc)


def load_games():
    """Liest games.json. Ungültige Einträge werden übersprungen und protokolliert,
    eine komplett defekte Datei wird beiseitegelegt. Ein Fehler in der Datei bringt
    weder die Web-Oberfläche noch den Bot oder den Preis-Check zum Absturz."""
    if not GAMES_FILE.exists():
        return []
    try:
        with open(GAMES_FILE, "r", encoding="utf-8-sig") as f:   # -sig: BOM von Windows-Editoren
            text = f.read()
        if not text.strip():
            return []                                             # leere Datei = keine Spiele
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("enthält keine Liste")
    except ValueError as exc:     # JSONDecodeError und UnicodeDecodeError sind ValueError
        _set_aside_broken_file(exc)
        return []

    games, seen = [], set()
    for index, entry in enumerate(data):
        game = _normalize_game(entry)
        if game is None:
            log.warning("games.json: Eintrag %d übersprungen (ungültig): %.80r", index, entry)
            continue
        if game["appid"] in seen:
            log.warning("games.json: Eintrag %d übersprungen (AppID %d doppelt)", index, game["appid"])
            continue
        seen.add(game["appid"])
        games.append(game)
    return games


def save_games(games):
    """Atomar schreiben: erst in eine Temp-Datei, dann ersetzen. So sieht kein
    anderer Prozess (Web, Bot, Preis-Check) je eine halbfertige Datei, und bei
    einem Fehler bleibt die alte games.json unverändert."""
    tmp = GAMES_FILE.with_name(GAMES_FILE.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(games, f, ensure_ascii=False, indent=2)
        for attempt in range(5):
            try:
                os.replace(tmp, GAMES_FILE)
                break
            except PermissionError:
                # Windows: kurz gesperrt, wenn ein anderer Prozess die Datei gerade liest
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def safe_error(exc: Exception) -> str:
    """Fehlertext OHNE URL: requests-Fehler enthalten sonst die komplette Adresse,
    bei Telegram also den Bot-Token."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def send_telegram(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [Warnung] Telegram-Nachricht konnte nicht gesendet werden: {safe_error(exc)}")


def search_steam_games(term: str, max_results: int = 8):
    """Sucht Spiele über die (inoffizielle) Steam-Store-Suche.
    Gibt eine Liste von Treffern zurück:
    [{"name": ..., "appid": ..., "image": <URL oder None>}, ...]"""
    params = {"term": term, "l": LANGUAGE, "cc": COUNTRY_CODE}
    try:
        resp = requests.get(STEAM_SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()          # kann ValueError werfen (z.B. HTML statt JSON)
    except (requests.RequestException, ValueError) as exc:
        print(f"[Warnung] Steam-Suche fehlgeschlagen: {safe_error(exc)}")
        return []

    if not isinstance(data, dict):
        return []
    items = data.get("items", [])[:max_results]

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


def format_local_time(iso_ts, tz=None):
    """Wandelt einen UTC-Zeitstempel aus der Datenbank in lokale Zeit um,
    z.B. '2026-07-27T12:49:00+00:00' -> '27.07.2026 14:49' (in Deutschland im Sommer).
    Ohne Zeitzone im Text wird UTC angenommen. tz=None bedeutet: Zeitzone des Rechners.
    Gibt None zurück, wenn kein Zeitstempel da ist, und den Rohtext, wenn er defekt ist."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return str(iso_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")
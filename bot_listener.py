"""
Telegram-Bot-Steuerung für den Steam-Preis-Tracker.
Läuft dauerhaft in einer Schleife (Long Polling) und reagiert auf Befehle,
die du direkt im Telegram-Chat mit deinem Bot schreibst:

    /list             -- zeigt aktuell getrackte Spiele
    /add <Name>        -- sucht ein Spiel auf Steam, zeigt Treffer zur Auswahl
    <Nummer>           -- wählt einen Treffer aus einer vorherigen /add-Suche
    /remove <Nummer>   -- entfernt ein Spiel (Nummer aus /list)
    /check             -- führt sofort einen Preis-Check aus
    /help              -- zeigt diese Übersicht

Nur Nachrichten von der in .env eingetragenen TELEGRAM_CHAT_ID werden
verarbeitet, alle anderen werden stillschweigend ignoriert.
"""

import requests

import common
import price_tracker

POLL_TIMEOUT = 25  # Sekunden Long Polling pro Anfrage
pending_results = []  # letzte /add-Suchtreffer, zum Nachwählen per Nummer


def get_updates(token, offset=None):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": POLL_TIMEOUT}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(url, params=params, timeout=POLL_TIMEOUT + 10)
        resp.raise_for_status()
        return resp.json().get("result", [])
    except requests.RequestException as exc:
        print(f"[Warnung] getUpdates fehlgeschlagen: {exc}")
        return []


def handle_list(token, chat_id):
    games = common.load_games()
    if not games:
        common.send_telegram(token, chat_id, "Aktuell werden keine Spiele getrackt.")
        return

    lines = []
    for i, g in enumerate(games, start=1):
        price_info = common.get_latest_price(g["appid"])
        if price_info:
            price_part = price_info["price"]
            if price_info["discount_percent"] > 0:
                price_part += f" (-{price_info['discount_percent']}%)"
        else:
            price_part = "noch nicht geprüft"
        lines.append(f"{i}. {g['name']} -- {price_part}")

    common.send_telegram(token, chat_id, "Getrackte Spiele:\n" + "\n".join(lines))


def handle_add(token, chat_id, term):
    global pending_results
    if not term:
        common.send_telegram(token, chat_id, "Bitte einen Namen angeben, z.B. /add Forza Horizon 5")
        return
    results = common.search_steam_games(term)
    if not results:
        common.send_telegram(token, chat_id, f"Keine Treffer für '{term}'.")
        pending_results = []
        return
    pending_results = results
    lines = [f"{i}. {r['name']}" for i, r in enumerate(results, start=1)]
    common.send_telegram(
        token, chat_id,
        "Treffer:\n" + "\n".join(lines) + "\n\nAntworte mit der Nummer, um hinzuzufügen."
    )


def handle_pick(token, chat_id, number_text):
    global pending_results
    if not pending_results:
        common.send_telegram(token, chat_id, "Keine offene Suche. Erst /add <Name> verwenden.")
        return
    if not number_text.isdigit() or not (1 <= int(number_text) <= len(pending_results)):
        common.send_telegram(token, chat_id, "Ungültige Nummer.")
        return

    picked = pending_results[int(number_text) - 1]
    pending_results = []

    games = common.load_games()
    if any(g["appid"] == picked["appid"] for g in games):
        common.send_telegram(token, chat_id, f"'{picked['name']}' wird bereits getrackt.")
        return
    games.append({"name": picked["name"], "appid": picked["appid"], "image": picked.get("image")})
    common.save_games(games)
    common.send_telegram(token, chat_id, f"✅ '{picked['name']}' wird jetzt getrackt.")


def handle_remove(token, chat_id, number_text):
    games = common.load_games()
    if not games:
        common.send_telegram(token, chat_id, "Aktuell werden keine Spiele getrackt.")
        return
    if not number_text.isdigit() or not (1 <= int(number_text) <= len(games)):
        lines = [f"{i}. {g['name']}" for i, g in enumerate(games, start=1)]
        common.send_telegram(
            token, chat_id,
            "Bitte /remove <Nummer> verwenden:\n" + "\n".join(lines)
        )
        return
    removed = games.pop(int(number_text) - 1)
    common.save_games(games)
    common.send_telegram(token, chat_id, f"➖ '{removed['name']}' wird nicht mehr getrackt.")


def handle_help(token, chat_id):
    text = (
        "Verfügbare Befehle:\n"
        "/list -- getrackte Spiele anzeigen\n"
        "/add <Name> -- Spiel suchen und hinzufügen\n"
        "/remove <Nummer> -- Spiel entfernen (Nummer aus /list)\n"
        "/check -- Preis-Check sofort ausführen\n"
        "/help -- diese Übersicht"
    )
    common.send_telegram(token, chat_id, text)


def handle_check(token, chat_id):
    common.send_telegram(token, chat_id, "Preis-Check läuft ...")
    price_tracker.run()
    common.send_telegram(token, chat_id, "Preis-Check abgeschlossen.")


def process_message(token, allowed_chat_id, message):
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()
    if chat_id != str(allowed_chat_id) or not text:
        return  # Nachrichten von anderen Chats werden ignoriert

    if text.startswith("/add"):
        handle_add(token, chat_id, text[len("/add"):].strip())
    elif text.startswith("/remove"):
        handle_remove(token, chat_id, text[len("/remove"):].strip())
    elif text.startswith("/list"):
        handle_list(token, chat_id)
    elif text.startswith("/check"):
        handle_check(token, chat_id)
    elif text.startswith("/help") or text.startswith("/start"):
        handle_help(token, chat_id)
    elif text.isdigit():
        handle_pick(token, chat_id, text)
    else:
        common.send_telegram(token, chat_id, "Unbekannter Befehl. /help für Übersicht.")


def main():
    token, chat_id = common.load_config()
    print("Bot-Listener gestartet. Strg+C zum Beenden.")
    common.send_telegram(token, chat_id, "🤖 Bot-Steuerung ist jetzt aktiv. /help für Befehle.")

    offset = None
    while True:
        updates = get_updates(token, offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if message:
                process_message(token, chat_id, message)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBeendet.")
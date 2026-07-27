"""
Verwaltung der getrackten Spiele (games.json).
Suche läuft über die Steam-Namenssuche -- du musst nie eine AppID selbst kennen.
Änderungen werden dauerhaft in games.json gespeichert und bleiben nach
einem Neustart erhalten.
"""

import common


def list_games():
    games = common.load_games()
    if not games:
        print("\nAktuell werden keine Spiele getrackt.\n")
        return games
    print("\nAktuell getrackte Spiele:")
    for i, g in enumerate(games, start=1):
        print(f"  {i}. {g['name']} (AppID {g['appid']})")
    print()
    return games


def add_game(token, chat_id):
    term = input("Nach welchem Spiel suchen? ").strip()
    if not term:
        return
    results = common.search_steam_games(term)
    if not results:
        print("Keine Treffer gefunden.\n")
        return

    print("\nTreffer:")
    for i, r in enumerate(results, start=1):
        print(f"  {i}. {r['name']} (AppID {r['appid']})")
    choice = input("Nummer wählen (Enter zum Abbrechen): ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(results)):
        print("Abgebrochen.\n")
        return

    picked = results[int(choice) - 1]
    games = common.load_games()
    if any(g["appid"] == picked["appid"] for g in games):
        print(f"'{picked['name']}' wird bereits getrackt.\n")
        return

    games.append({"name": picked["name"], "appid": picked["appid"], "image": picked.get("image")})
    common.save_games(games)
    print(f"'{picked['name']}' wurde hinzugefügt.\n")
    common.send_telegram(token, chat_id, f"➕ '{picked['name']}' wird jetzt getrackt.")


def remove_game(token, chat_id):
    games = list_games()
    if not games:
        return
    choice = input("Nummer zum Entfernen wählen (Enter zum Abbrechen): ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(games)):
        print("Abgebrochen.\n")
        return

    removed = games.pop(int(choice) - 1)
    common.save_games(games)
    print(f"'{removed['name']}' wurde entfernt.\n")
    common.send_telegram(token, chat_id, f"➖ '{removed['name']}' wird nicht mehr getrackt.")


def main():
    token, chat_id = common.load_config()
    while True:
        print("=== Steam-Preis-Tracker: Spieleverwaltung ===")
        print("1. Getrackte Spiele anzeigen")
        print("2. Spiel hinzufügen")
        print("3. Spiel entfernen")
        print("4. Beenden")
        choice = input("Auswahl: ").strip()

        if choice == "1":
            list_games()
        elif choice == "2":
            add_game(token, chat_id)
        elif choice == "3":
            remove_game(token, chat_id)
        elif choice == "4":
            break
        else:
            print("Ungültige Auswahl.\n")


if __name__ == "__main__":
    main()
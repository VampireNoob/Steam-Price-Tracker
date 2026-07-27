"""
Steam Price Tracker -- Web-Frontend (Flask)
--------------------------------------------
Browser-Oberfläche für dieselben Daten (games.json, prices.db), die auch
price_tracker.py, manage_games.py und bot_listener.py nutzen -- alle vier
Zugriffswege funktionieren nebeneinander, ohne sich zu stören.

Hinweis: app.secret_key ist hier bewusst simpel/fest, weil die App nur
lokal läuft und kein Login-System hat. Für ein späteres Cloud-Deployment
müsste der Key aus der .env kommen statt im Code zu stehen.
"""

import sqlite3

from flask import Flask, flash, redirect, render_template, request, url_for

import common
import price_tracker

app = Flask(__name__)
app.secret_key = "steam-tracker-local-dev"


def get_latest_price(appid: int):
    """Liest den zuletzt bekannten Preis für ein Spiel aus prices.db.
    Gibt None zurück, wenn noch kein price_tracker.py-Lauf stattfand."""
    if not common.DB_FILE.exists():
        return None
    conn = sqlite3.connect(common.DB_FILE)
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


@app.route("/")
def index():
    games = common.load_games()
    rows = []
    for game in games:
        price_info = get_latest_price(game["appid"])
        rows.append({
            "name": game["name"],
            "appid": game["appid"],
            "price": price_info["price"] if price_info else "noch nicht geprüft",
            "discount_percent": price_info["discount_percent"] if price_info else 0,
            "checked_at": price_info["checked_at"] if price_info else None,
        })
    return render_template("index.html", games=rows)


@app.route("/add", methods=["GET", "POST"])
def add_game():
    results = []
    term = ""
    if request.method == "POST":
        term = request.form.get("term", "").strip()
        if term:
            results = common.search_steam_games(term)
            if not results:
                flash(f"Keine Treffer für '{term}'.", "error")
    return render_template("add.html", results=results, term=term)


@app.route("/add/confirm", methods=["POST"])
def confirm_add():
    name = request.form.get("name")
    appid_raw = request.form.get("appid")
    if not name or not appid_raw:
        flash("Ungültige Auswahl.", "error")
        return redirect(url_for("add_game"))

    appid = int(appid_raw)
    games = common.load_games()
    if any(g["appid"] == appid for g in games):
        flash(f"'{name}' wird bereits getrackt.", "info")
    else:
        games.append({"name": name, "appid": appid})
        common.save_games(games)
        flash(f"'{name}' wurde hinzugefügt.", "success")
    return redirect(url_for("index"))


@app.route("/remove/<int:appid>", methods=["POST"])
def remove_game(appid):
    games = common.load_games()
    removed = next((g for g in games if g["appid"] == appid), None)
    games = [g for g in games if g["appid"] != appid]
    common.save_games(games)
    if removed:
        flash(f"'{removed['name']}' wurde entfernt.", "success")
    return redirect(url_for("index"))


@app.route("/check", methods=["POST"])
def check_now():
    price_tracker.run()
    flash("Preis-Check abgeschlossen.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
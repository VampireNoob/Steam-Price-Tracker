# Steam Price Tracker

A small application built as a school project to practice Python fundamentals: connecting to an external API, persisting data, and sending notifications. It tracks the Steam prices of a user-defined list of games and sends a Telegram message whenever a price changes. It can be controlled from three independent places — the terminal, Telegram, or a browser — all working on the same data.

## What it does (current state)

- **Search & manage tracked games** (`manage_games.py`) — an interactive console menu lets you search Steam by game name (no need to know the AppID), add matches to your tracking list, or remove games again. The list is stored in `games.json` and persists across restarts.
- **Check prices** (`price_tracker.py`) — fetches the current price for every tracked game via Steam's store API, compares it against the last known price (stored in a local SQLite database, `prices.db`), and sends a Telegram message if the price went up or down. Every run is logged to `tracker.log` (size-limited via rotation), so scheduled runs remain traceable even without a visible console.
- **Telegram bot control** (`bot_listener.py`) — runs continuously (long polling) and reacts to commands sent directly in the Telegram chat: `/list` (shows tracked games with current price/discount), `/add <name>`, `/remove <number>`, `/check` (runs a price check on demand), `/help`. Only messages from the configured chat ID are processed.
- **Web frontend** (`app.py`, Flask) — a browser-based view of the same data: see tracked games with current price/discount and a game thumbnail, search and add new games (with preview images), remove games, and trigger a manual price check, all from `http://127.0.0.1:5000`.
- **Automation** — both `price_tracker.py` and `bot_listener.py` run unattended via Windows Task Scheduler: the price check daily at a fixed time, the bot listener at login (via `pythonw.exe`, no visible window), so notifications and bot commands work without manually starting anything.
- **Shared logic** (`common.py`) — configuration loading, `games.json` read/write, Telegram sending, and Steam search are factored out so every entry point (console, bot, web) uses the same code instead of duplicating it.

All of the above has been manually tested end to end, including simulated and real price changes (e.g. a live Steam sale), Telegram bot commands, both scheduled tasks running unattended, and the full web flow (view, search, add, remove, manual check).

## Setup

1. `pip install -r requirements.txt`
2. Create a Telegram bot via **@BotFather** (`/newbot`) and copy the token it gives you
3. Send your new bot any message, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser to find your chat ID (`"chat":{"id": ...}`)
4. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
5. Pick any entry point:
   - `python manage_games.py` — console menu
   - `python bot_listener.py` — Telegram bot control (`/help` for commands)
   - `python app.py` — web interface at `http://127.0.0.1:5000`
6. `python price_tracker.py` — checks prices once; the first run per game only records a baseline (no notification yet), later runs report changes

> `games.json` is created automatically the first time you add a game via any of the three entry points above. `games.example.json` just shows the expected format.

### Running unattended (Windows Task Scheduler)

- **Price check**: daily trigger → Action: `venv\Scripts\python.exe` with argument `price_tracker.py`, "Start in" set to the project folder.
- **Bot listener**: "At log on" trigger → Action: `venv\Scripts\pythonw.exe` (no console window) with argument `bot_listener.py`, same "Start in" folder. Under the task's Settings tab, disable "Stop the task if it runs longer than X days" so it isn't killed after a few days.

## Why Steam only (not Instant Gaming or others)

Steam has a public, if unofficial, JSON API for both game search and price lookups, which made this project reliable without needing to scrape and parse HTML. Instant Gaming and similar shops don't offer anything comparable — supporting them would mean scraping their website directly, which is more fragile (breaks on layout changes), potentially against their terms of service, and out of scope for this project.

## Roadmap — possible future extensions

- **Cloud hosting** — GitHub Pages and Netlify can't run Python, so they're not an option here. If pursued:
  - **GitHub Actions** to run the price-check on a schedule in the cloud, independent of whether a computer is turned on
  - **PythonAnywhere** (or similar) to host the web frontend and/or the bot listener, since both need an actual Python runtime, not static hosting

This is intentionally out of scope for the current version — everything above runs locally and depends on the PC being on.

## Tech stack

Python, Flask (web frontend), `requests` (HTTP), `python-dotenv` (config), SQLite (price history), Steam Store API (search + price data), Telegram Bot API (notifications + interactive commands), Windows Task Scheduler (automation), Python `logging` (rotating file logs).

## Contact

Feel free to reach out via GitHub or Instagram:
- GitHub: [@VampireNoob](https://github.com/VampireNoob)
- Instagram: [@vampirenoob](https://www.instagram.com/vampirenoob/)
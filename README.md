# Steam Price Tracker

A small console application built as a school project to practice Python fundamentals: connecting to an external API, persisting data, and sending notifications. It tracks the Steam prices of a user-defined list of games and sends a Telegram message whenever a price changes.

## What it does (current state)

- **Search & manage tracked games** (`manage_games.py`) — an interactive console menu lets you search Steam by game name (no need to know the AppID), add matches to your tracking list, or remove games again. The list is stored in `games.json` and persists across restarts.
- **Check prices** (`price_tracker.py`) — fetches the current price for every tracked game via Steam's store API, compares it against the last known price (stored in a local SQLite database, `prices.db`), and sends a Telegram message if the price went up or down.
- **Telegram notifications** — used both for price changes and for confirming when a game is added to or removed from the tracking list.
- **Shared logic** (`common.py`) — configuration loading, `games.json` read/write, Telegram sending, and Steam search are factored out so both scripts use the same code instead of duplicating it.

All of the above has been manually tested end to end: Steam search returns real results, `games.json` correctly persists additions/removals, a simulated price change was correctly detected and triggered a real Telegram message.

## Setup

1. `pip install -r requirements.txt`
2. Create a Telegram bot via **@BotFather** (`/newbot`) and copy the token it gives you
3. Send your new bot any message, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser to find your chat ID (`"chat":{"id": ...}`)
4. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
5. `python manage_games.py` — add the games you want to track
6. `python price_tracker.py` — checks prices once; the first run per game only records a baseline (no notification yet), later runs report changes
7. `games.json` is created automatically the first time you add a game via `manage_games.py`. `games.example.json` just shows the expected format.

## Why Steam only (not Instant Gaming or others)

Steam has a public, if unofficial, JSON API for both game search and price lookups, which made this project reliable without needing to scrape and parse HTML. Instant Gaming and similar shops don't offer anything comparable — supporting them would mean scraping their website directly, which is more fragile (breaks on layout changes), potentially against their terms of service, and out of scope for a first version.

## Roadmap — what's still coming

- **Automation** — running `price_tracker.py` on a schedule (e.g. daily) via Windows Task Scheduler, so it checks prices without manual runs. *(Next step, not yet implemented.)*
- **Web frontend** — a browser-based interface (planned with Flask) as an alternative to the console menu for managing tracked games, once the console version is fully stable.
- **Cloud hosting** — GitHub Pages and Netlify can't run Python, so they're not an option here. Once the frontend exists, the plan is:
  - **GitHub Actions** to run the price-check on a schedule in the cloud, independent of whether a computer is turned on
  - **PythonAnywhere** (or similar) to host the web frontend itself, since it needs an actual Python runtime, not static hosting

## Tech stack

Python, `requests` (HTTP), `python-dotenv` (config), SQLite (price history), Steam Store API (search + price data), Telegram Bot API (notifications).

## Contact

Feel free to reach out via GitHub or Instagram:
- GitHub: [@VampireNoob](https://github.com/VampireNoob)
- Instagram: [@vampirenoob](https://www.instagram.com/vampirenoob/)
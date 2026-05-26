# Cricket Verse Telegram Bot

A Python Telegram bot for the Cricket Verse ball data and match flow you described.

## Features

- `/playmatch <overs>` creates an active match in a group.
- Captain 1 starts the match; another user joins as Captain 2.
- Random captain toss winner, bat/bowl choice, team names, player add/remove/select flow.
- `/myteam` works only for captains during an active match and shows only that captain's own team.
- Start stays locked until both teams have equal players and the starting batter/bowler are selected.
- Pacer and spinner delivery data, batter run + length selection, hard-ball logic, bouncer limit, extras, spam protocol, wickets, catch guesses, run outs, over changes, innings switch, target chase.
- SQLite database stores player career stats and completed match snapshots.
- `/howplayed <telegram_id>` summarizes saved stats with Gemini when `GEMINI_API_KEY` is set.
- Natural AI questions work when a message replies to a user, mentions a saved `@username`, or includes a Telegram id. Examples: `how did he play?`, `stats @playername`, `what is 123456789 batting record?`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
```

4. Run:

```bash
python main.py
```

## Free Render Deploy

This repo supports Render's free web service by using Telegram webhooks.

1. Push this project to GitHub.
2. On Render, create a new **Web Service** from the repo.
3. Use these settings:

```text
Plan: Free
Build Command: pip install -r requirements.txt
Start Command: python main.py
```

4. Add environment variables:

```env
RUN_MODE=webhook
WEBHOOK_PATH=telegram-webhook
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
DATABASE_PATH=/tmp/cricket_verse.sqlite3
```

Render automatically provides `PORT` and `RENDER_EXTERNAL_URL`, and the bot uses them to set the Telegram webhook.

Free Render storage is temporary. With `DATABASE_PATH=/tmp/cricket_verse.sqlite3`, stats can reset after redeploys or restarts. For permanent stats, use a paid Render disk or move the database to an external hosted database.

## Commands

- `/playmatch 5` - start a 5-over match.
- `/myteam` - captain team controls.
- `/howplayed 123456789` - Gemini/stat summary for a Telegram user id.
- Reply to a player and ask `how did he play?` - AI answers from the database and live match state.
- Ask `stats @username` or `what is 123456789 performance?` - AI answers for that player if they exist in the database.
- `/cancelmatch` - end the active match in the chat.

## Ball Flow

1. Bowler selects a delivery.
2. Bot secretly picks the actual length from the delivery data.
3. Batter selects a run.
4. Batter selects a length guess: Full, Yorker, Good, Short, and Bouncer when that delivery can be a bouncer.
5. If the batter length matches the actual length, the batter gets the selected run. If it misses, MLR/hard-ball/wicket rules decide the result.

## Notes

- Telegram bots cannot reliably convert every `@username` to an id unless the user has interacted with the bot. Adding by numeric Telegram id is the most reliable method.
- The bot stores active match state in SQLite, so it can recover after a restart.
- Catch timeouts use `python-telegram-bot` job queue, and Render webhook deploys use the `webhooks` extra from `requirements.txt`.

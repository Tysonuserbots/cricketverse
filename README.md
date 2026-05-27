# Cricket Verse Telegram Bot

A Python Telegram bot for the Cricket Verse ball data and match flow you described.

## Features

- `/playmatch <overs>` creates an active match in a group.
- Captain 1 starts the match; another user joins as Captain 2.
- Random captain toss winner, bat/bowl choice, team names, player add/remove/select flow.
- `/myteam` works only for captains during an active match and shows only that captain's own team.
- Start stays locked until both teams have equal players and the starting batter/bowler are selected.
- `/add` lets captains add a replied, tagged, or numeric-id player to their own team.
- Match start needs group admin approval after both captains press Start.
- Pacer and spinner delivery data, batter run + length selection, hard-ball logic, batter bouncer limit, extras, spam protocol, wickets, catch guesses, run outs, DRS, over changes, innings switch, target chase.
- SQLite database stores player career stats, completed match snapshots with match ids, player-of-match records, and virtual credit profiles.
- `/howplayed <telegram_id>` summarizes saved stats with Gemini when `GEMINI_API_KEY` is set.
- `/ask` answers only live ongoing-match questions.
- `/buzz` answers saved database/history/player-stat questions.
- `/matchin <id>` shows full saved match details and every player line.
- `/myprofile` shows cricket stats, virtual credits, and fun-game record.
- Virtual-credit games are for entertainment only: no real money, no deposit, no withdrawal.

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
- `/add <telegram_id> <name>` - captain-only quick add; also works when replying to or tagging a Telegram user.
- `/howplayed 123456789` - Gemini/stat summary for a Telegram user id.
- `/ask who is winning?` - live match analysis only.
- `/buzz top runs` or `/buzz most wickets` - database-backed history and player stats.
- `/matchin 12` - saved match details for match id 12.
- `/myprofile` - your stats and virtual credits.
- `/games` - list virtual-credit games.
- `/tossduel 50`, `/runrace 50`, `/wicketpick 50` - PvP virtual-credit challenges.
- `/cancelmatch` - end the active match in the chat.

## Ball Flow

1. Bowler selects a delivery.
2. Bot secretly picks the actual length from the delivery data.
3. Batter selects a run.
4. Batter selects a length guess: Full, Yorker, Good, Short, and Bouncer when that delivery can be a bouncer.
5. If the batter length matches the actual length, the batter gets the selected run. If it misses, MLR/hard-ball/wicket rules decide the result.
6. For the first 3 hard balls in an over, length miss gives miss-length runs. Bouncers count toward that hard-ball cap.
7. A batter can use the Bouncer length option once per over when it is offered.
8. LBW and Stumped wickets offer DRS to the batting captain when reviews remain.

## AI Behavior

- Natural reply AI is disabled. The bot will not answer random replied/tagged questions.
- Use `/ask` for current match questions such as who is winning, who choked, or where the pressure shifted.
- Use `/buzz` for previous match details, leaderboards, player stats, and saved database facts.
- Answers are short, English-only, cricket-focused, and can include light funny roast commentary.

## Virtual Credits

- Credits are in-bot entertainment points only.
- There is no real-money gambling, buying, selling, deposit, withdrawal, or cash prize.
- Fun-game winners gain virtual credits from the loser and records appear in `/myprofile`.

## Notes

- Telegram bots cannot reliably convert every `@username` to an id unless the user has interacted with the bot. Adding by numeric Telegram id is the most reliable method.
- The bot stores active match state in SQLite, so it can recover after a restart.
- Catch timeouts use `python-telegram-bot` job queue, and Render webhook deploys use the `webhooks` extra from `requirements.txt`.

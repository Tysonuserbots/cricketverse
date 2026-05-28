# Cricket Verse Telegram Bot

A Python Telegram bot for the Cricket Verse ball data and match flow you described.

## Features

- `/playmatch <overs>` creates an active match in a group.
- Captain 1 starts the match; another user joins as Captain 2.
- Random captain toss winner, bat/bowl choice, team names, player add/remove/select flow.
- `/myteam` works only for captains during an active match and shows only that captain's own team.
- Start stays locked until both teams have equal players and the starting batter/bowler are selected.
- `/add` lets captains add a replied, tagged, or numeric-id player to their own team.
- Only the initial match start needs group admin approval after both captains press Start.
- `/playmatch <overs> <powerplay_overs>` creates a match with optional powerplay overs.
- Pacer and spinner delivery data, batter run + length selection, hard-ball logic, batter bouncer guess, powerplay rules, free hits, wide rebowls, extras, spam protocol, wickets, catch guesses, run outs, DRS, over changes, innings switch, target chase.
- SQLite database stores player career stats, completed match snapshots with match ids, player-of-match records, and puzzle game records.
- `/start` checks bot health and ping. `/help` lists public commands only.
- `/howplayed <telegram_id>` summarizes saved stats with Gemini when `GEMINI_API_KEY` is set.
- `/ask` answers only live ongoing-match questions.
- `/buzz` answers saved database/history/player-stat questions.
- `/matchin <id>` shows full saved match details and every player line.
- `/logs <num>` lets owner id `6262064767` inspect recent batter/bowler button presses.
- `/spam <num>` lets owner id `6262064767` repeat text or a replied message 1 to 100 times.
- `/exp` explains the last completed ball with run/wicket reason and probability notes.
- `/myprofile` shows cricket stats and puzzle record.
- `/games` and `/puzzle` start button-based puzzle games.
- `/pvp <overs> <powerplay_overs>` starts a 1v1 match with no team building.
- `/guide` shows simple help pages with Next, Back, and Close buttons.
- `/casino`, `/bet`, `/dice`, and `/roll` use virtual in-bot credits only.

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

- `/start` - bot health and ping.
- `/help` - public command list.
- `/playmatch 5 2` - start a 5-over match with 2 powerplay overs.
- `/pvp 5 2` - start a 1v1 match with 2 powerplay overs.
- `/myteam` - captain team controls.
- `/add <telegram_id> <name>` - captain-only quick add; also works when replying to or tagging a Telegram user.
- `/howplayed 123456789` - Gemini/stat summary for a Telegram user id.
- `/ask who is winning?` - live match analysis only.
- `/buzz top runs` or `/buzz most wickets` - database-backed history and player stats.
- `/matchin 12` - saved match details for match id 12.
- `/logs 10` - owner-only last 10 batter/bowler button presses.
- `/spam 5 hello` - owner-only spam text; reply to a message with `/spam 5` to repeat that message.
- `/exp` - explain the last live ball result.
- `/guide` - simple button guide.
- `/myprofile` - your stats and puzzle game record.
- `/games` or `/puzzle` - button puzzle arena.
- `/casino 100` - open virtual-credit casino buttons.
- `/bet heads 100` or `/bet tails 100` - coin bet.
- `/dice 100` or `/roll 100` - dice multiplier game.
- `/cancelmatch` - end the active match in the chat.

## Ball Flow

1. Bowler selects a delivery.
2. Bot secretly picks the actual length from the delivery data.
3. Batter selects a run.
4. Batter selects a length guess: Full, Yorker, Good, Short, and Bouncer when that delivery can be a bouncer.
5. If the batter length matches the actual length, the batter gets the selected run. If it misses, MLR/hard-ball/wicket rules decide the result.
6. For normal overs, the first 4 hard balls in an over use hard-ball restriction. In powerplay, only the first 2 hard balls are restricted.
7. Bouncers count toward the hard-ball cap.
8. The batter can guess Bouncer length once per over, even if the bowler did not press Bouncer.
9. No-balls create a free hit for the next legal ball.
10. No-ball batting runs use MRL logic.
11. Wides do not count as legal balls, so the delivery is rebowled.
12. Powerplay has reduced catch-out chance.
13. LBW and Stumped wickets offer DRS to the batting captain when reviews remain.

## AI Behavior

- Natural reply AI is disabled. The bot will not answer random replied/tagged questions.
- Use `/ask` for current match questions such as who is winning, who choked, or where the pressure shifted.
- Use `/buzz` for previous match details, leaderboards, player stats, and saved database facts.
- Answers are short, English-only, cricket-focused, and can include light funny roast commentary.

## Puzzle Games

- Old stake-style virtual-credit games are removed from the command surface.
- Puzzle games use Telegram buttons only.
- 2048 is available from `/games`.
- Minefield and Memory Match are also available from `/games`.
- Puzzle wins and losses appear in `/myprofile`.

## Credits

- Credits are only in-bot points, never real money.
- Owner id `6262064767` can add credits with `/add <tg_id> <amount>` or by replying `/add <amount>`.
- Dice multipliers: 1=x0.5, 2=x0.75, 3=x1, 4=x1.5, 5=x2, 6=x2.5.

## Notes

- Telegram bots cannot reliably convert every `@username` to an id unless the user has interacted with the bot. Adding by numeric Telegram id is the most reliable method.
- The bot stores active match state in SQLite, so it can recover after a restart.
- Catch timeouts use `python-telegram-bot` job queue, and Render webhook deploys use the `webhooks` extra from `requirements.txt`.

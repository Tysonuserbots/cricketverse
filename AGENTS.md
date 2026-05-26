# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python Telegram bot for Cricket Verse match flow. The entry point is `main.py`, which calls `cricket_verse.bot.run()`. Application code lives in `cricket_verse/`:

- `bot.py` wires Telegram handlers, callbacks, startup mode, and runtime state.
- `engine.py` contains match rules and ball-resolution logic.
- `models.py` defines match data structures and serialization helpers.
- `database.py` handles SQLite persistence for live matches, stats, and match snapshots.
- `formatting.py` builds scorecards and roster text; `config.py` loads settings.
- `game_data.py` stores cricket delivery/run data; `gemini.py` handles AI summaries.

There is currently no `tests/` directory. Keep generated files such as `__pycache__/`, local SQLite databases, and `.env` out of version control.

## Build, Test, and Development Commands

- `python -m venv .venv` creates a local virtual environment.
- `.venv\Scripts\Activate.ps1` activates it on Windows PowerShell.
- `pip install -r requirements.txt` installs runtime dependencies.
- `python main.py` runs the bot locally in polling mode by default.
- `python -m compileall cricket_verse main.py` performs a quick syntax check when no test suite is available.

For Render, use `render.yaml` or set `Build Command: pip install -r requirements.txt` and `Start Command: python main.py`.

## Coding Style & Naming Conventions

Use Python 3.12-compatible syntax and the existing style: 4-space indentation, `snake_case` functions and variables, `PascalCase` dataclasses, and constants in `UPPER_CASE`. Prefer typed signatures, `from __future__ import annotations`, and small helpers for shared handler/engine logic.

## Testing Guidelines

No formal test framework is configured yet. When adding tests, place them under `tests/` and use `pytest` with filenames like `test_engine.py` or `test_database.py`. Prioritize deterministic tests for `engine.py`, `models.py`, and `database.py`; avoid Telegram or Gemini network calls. Until then, run `python -m compileall cricket_verse main.py`.

## Commit & Pull Request Guidelines

This checkout does not include Git history, so no project-specific commit convention is available. Use short imperative subjects such as `Add match recovery validation` or `Fix webhook startup config`. Pull requests should include a summary, commands run, config changes, and screenshots or Telegram transcript snippets for user-visible flow changes.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local development and never commit real tokens. Required configuration is `TELEGRAM_BOT_TOKEN`; Gemini features also need `GEMINI_API_KEY`. For webhook deploys set `RUN_MODE=webhook`, `WEBHOOK_PATH`, and a persistent `DATABASE_PATH` if stats must survive restarts.

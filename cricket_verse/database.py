from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import Match


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_schema()

    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                display_name TEXT NOT NULL,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS career_stats (
                tg_id INTEGER PRIMARY KEY,
                matches INTEGER NOT NULL DEFAULT 0,
                innings INTEGER NOT NULL DEFAULT 0,
                runs INTEGER NOT NULL DEFAULT 0,
                balls INTEGER NOT NULL DEFAULT 0,
                fours INTEGER NOT NULL DEFAULT 0,
                sixes INTEGER NOT NULL DEFAULT 0,
                outs INTEGER NOT NULL DEFAULT 0,
                ducks INTEGER NOT NULL DEFAULT 0,
                wickets INTEGER NOT NULL DEFAULT 0,
                balls_bowled INTEGER NOT NULL DEFAULT 0,
                runs_conceded INTEGER NOT NULL DEFAULT 0,
                wides INTEGER NOT NULL DEFAULT 0,
                no_balls INTEGER NOT NULL DEFAULT 0,
                catches INTEGER NOT NULL DEFAULT 0,
                drops INTEGER NOT NULL DEFAULT 0,
                runouts INTEGER NOT NULL DEFAULT 0,
                player_of_match INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(tg_id) REFERENCES players(tg_id)
            );

            CREATE TABLE IF NOT EXISTS active_matches (
                chat_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS completed_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._ensure_column("career_stats", "player_of_match", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("career_stats", "games_played", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("career_stats", "games_won", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("career_stats", "games_lost", "INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_user(self, user: Any, display_name: str | None = None) -> None:
        name = display_name or getattr(user, "first_name", None) or getattr(user, "full_name", None) or str(user.id)
        self.conn.execute(
            """
            INSERT INTO players (tg_id, username, first_name, display_name, last_seen)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tg_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                display_name=excluded.display_name,
                last_seen=CURRENT_TIMESTAMP
            """,
            (
                int(user.id),
                getattr(user, "username", None),
                getattr(user, "first_name", None),
                name,
            ),
        )
        self.conn.execute("INSERT OR IGNORE INTO career_stats (tg_id) VALUES (?)", (int(user.id),))
        self.conn.commit()

    def upsert_manual_player(self, tg_id: int, display_name: str) -> None:
        self.conn.execute(
            """
            INSERT INTO players (tg_id, username, first_name, display_name, last_seen)
            VALUES (?, NULL, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tg_id) DO UPDATE SET
                display_name=excluded.display_name,
                last_seen=CURRENT_TIMESTAMP
            """,
            (int(tg_id), display_name, display_name),
        )
        self.conn.execute("INSERT OR IGNORE INTO career_stats (tg_id) VALUES (?)", (int(tg_id),))
        self.conn.commit()

    def save_match(self, match: Match) -> None:
        self.conn.execute(
            """
            INSERT INTO active_matches (chat_id, state_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                state_json=excluded.state_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (int(match.chat_id), json.dumps(match.to_dict())),
        )
        self.conn.commit()

    def load_match(self, chat_id: int) -> Match | None:
        row = self.conn.execute(
            "SELECT state_json FROM active_matches WHERE chat_id = ?",
            (int(chat_id),),
        ).fetchone()
        if not row:
            return None
        return Match.from_dict(json.loads(row["state_json"]))

    def delete_match(self, chat_id: int) -> None:
        self.conn.execute("DELETE FROM active_matches WHERE chat_id = ?", (int(chat_id),))
        self.conn.commit()

    def complete_match(self, match: Match, summary: dict[str, Any]) -> int:
        cursor = self.conn.execute(
            "INSERT INTO completed_matches (chat_id, summary_json) VALUES (?, ?)",
            (int(match.chat_id), json.dumps(summary)),
        )
        match_id = int(cursor.lastrowid)
        saved = dict(summary)
        saved["match_id"] = match_id
        self.conn.execute(
            "UPDATE completed_matches SET summary_json = ? WHERE id = ?",
            (json.dumps(saved), match_id),
        )
        self.delete_match(match.chat_id)
        return match_id

    def apply_match_stats(self, match: Match, player_of_match_id: int | None = None) -> None:
        for pid, stats in match.match_stats.items():
            tg_id = int(pid)
            self.upsert_manual_player(tg_id, stats["name"])
            batting = stats["batting"]
            bowling = stats["bowling"]
            fielding = stats["fielding"]
            innings = 1 if batting["balls"] or batting["runs"] or batting["out"] else 0
            ducks = 1 if batting["out"] and batting["runs"] == 0 else 0
            outs = 1 if batting["out"] else 0
            self.conn.execute(
                """
                UPDATE career_stats SET
                    matches = matches + 1,
                    innings = innings + ?,
                    runs = runs + ?,
                    balls = balls + ?,
                    fours = fours + ?,
                    sixes = sixes + ?,
                    outs = outs + ?,
                    ducks = ducks + ?,
                    wickets = wickets + ?,
                    balls_bowled = balls_bowled + ?,
                    runs_conceded = runs_conceded + ?,
                    wides = wides + ?,
                    no_balls = no_balls + ?,
                    catches = catches + ?,
                    drops = drops + ?,
                    runouts = runouts + ?
                    , player_of_match = player_of_match + ?
                WHERE tg_id = ?
                """,
                (
                    innings,
                    int(batting["runs"]),
                    int(batting["balls"]),
                    int(batting["fours"]),
                    int(batting["sixes"]),
                    outs,
                    ducks,
                    int(bowling["wickets"]),
                    int(bowling["balls"]),
                    int(bowling["runs"]),
                    int(bowling["wides"]),
                    int(bowling["no_balls"]),
                    int(fielding["catches"]),
                    int(fielding["drops"]),
                    int(fielding["runouts"]),
                    1 if player_of_match_id and int(player_of_match_id) == tg_id else 0,
                    tg_id,
                ),
            )
        self.conn.commit()

    def player_stats(self, tg_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT p.tg_id, p.username, p.display_name, c.*
            FROM players p
            LEFT JOIN career_stats c ON c.tg_id = p.tg_id
            WHERE p.tg_id = ?
            """,
            (int(tg_id),),
        ).fetchone()
        return dict(row) if row else None

    def player_by_username(self, username: str) -> dict[str, Any] | None:
        clean = username.strip().lstrip("@").lower()
        row = self.conn.execute(
            """
            SELECT p.tg_id, p.username, p.display_name, c.*
            FROM players p
            LEFT JOIN career_stats c ON c.tg_id = p.tg_id
            WHERE lower(p.username) = ?
            """,
            (clean,),
        ).fetchone()
        return dict(row) if row else None

    def recent_match_stats(self, tg_id: int, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT summary_json, created_at
            FROM completed_matches
            ORDER BY id DESC
            LIMIT 25
            """
        ).fetchall()
        found: list[dict[str, Any]] = []
        for row in rows:
            summary = json.loads(row["summary_json"])
            player = summary.get("players", {}).get(str(tg_id))
            if player:
                found.append({"created_at": row["created_at"], "stats": player, "result": summary.get("result")})
            if len(found) >= limit:
                break
        return found

    def completed_match(self, match_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, chat_id, summary_json, created_at FROM completed_matches WHERE id = ?",
            (int(match_id),),
        ).fetchone()
        if not row:
            return None
        summary = json.loads(row["summary_json"])
        summary.setdefault("match_id", int(row["id"]))
        return {
            "id": int(row["id"]),
            "chat_id": int(row["chat_id"]),
            "created_at": row["created_at"],
            "summary": summary,
        }

    def recent_matches(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, chat_id, summary_json, created_at
            FROM completed_matches
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        matches = []
        for row in rows:
            summary = json.loads(row["summary_json"])
            summary.setdefault("match_id", int(row["id"]))
            matches.append(
                {
                    "id": int(row["id"]),
                    "chat_id": int(row["chat_id"]),
                    "created_at": row["created_at"],
                    "summary": summary,
                }
            )
        return matches

    def career_leaders(self, metric: str, limit: int = 5) -> list[dict[str, Any]]:
        allowed = {
            "runs": "runs",
            "wickets": "wickets",
            "catches": "catches",
            "player_of_match": "player_of_match",
            "games_won": "games_won",
        }
        column = allowed.get(metric, "runs")
        rows = self.conn.execute(
            f"""
            SELECT p.tg_id, p.display_name, p.username, c.*
            FROM career_stats c
            JOIN players p ON p.tg_id = c.tg_id
            ORDER BY c.{column} DESC, c.matches DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def ensure_profile(self, tg_id: int, display_name: str) -> None:
        self.upsert_manual_player(int(tg_id), display_name)

    def profile(self, tg_id: int) -> dict[str, Any] | None:
        return self.player_stats(tg_id)

    def record_game_result(self, tg_id: int, won: bool) -> None:
        self.conn.execute("INSERT OR IGNORE INTO career_stats (tg_id) VALUES (?)", (int(tg_id),))
        self.conn.execute(
            """
            UPDATE career_stats SET
                games_played = games_played + 1,
                games_won = games_won + ?,
                games_lost = games_lost + ?
            WHERE tg_id = ?
            """,
            (1 if won else 0, 0 if won else 1, int(tg_id)),
        )
        self.conn.commit()

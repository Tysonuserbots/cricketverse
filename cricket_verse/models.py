from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def user_label(user: Any) -> str:
    first_name = getattr(user, "first_name", "") or ""
    if first_name.strip():
        return first_name.strip()
    full_name = " ".join(
        part for part in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if part
    ).strip()
    return full_name or getattr(user, "username", None) or str(getattr(user, "id", "Unknown"))


def new_player(user_id: int, name: str, is_captain: bool = False) -> dict[str, Any]:
    return {
        "id": int(user_id),
        "name": name,
        "is_captain": is_captain,
        "style": None,
        "out": False,
    }


def new_player_stats(name: str, team_key: str) -> dict[str, Any]:
    return {
        "name": name,
        "team": team_key,
        "batting": {
            "runs": 0,
            "balls": 0,
            "fours": 0,
            "sixes": 0,
            "out": False,
            "dismissal": None,
        },
        "bowling": {
            "balls": 0,
            "runs": 0,
            "wickets": 0,
            "wides": 0,
            "no_balls": 0,
        },
        "fielding": {
            "catches": 0,
            "drops": 0,
            "runouts": 0,
        },
    }


@dataclass
class Match:
    chat_id: int
    overs: int
    phase: str = "joining"
    main_message_id: int | None = None
    innings: int = 1
    captains: dict[str, dict[str, Any]] = field(default_factory=dict)
    teams: dict[str, dict[str, Any]] = field(default_factory=dict)
    toss_winner: str | None = None
    batting_team: str | None = None
    bowling_team: str | None = None
    innings_order: list[str] = field(default_factory=list)
    score: dict[str, Any] = field(default_factory=dict)
    innings_history: list[dict[str, Any]] = field(default_factory=list)
    current_batter_id: int | None = None
    current_bowler_id: int | None = None
    current_bowler_style: str | None = None
    ready: dict[str, bool] = field(default_factory=dict)
    over_state: dict[str, Any] = field(default_factory=dict)
    match_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_action: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_delivery: dict[str, Any] | None = None
    pending_catch: dict[str, Any] | None = None
    target: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "overs": self.overs,
            "phase": self.phase,
            "main_message_id": self.main_message_id,
            "innings": self.innings,
            "captains": self.captains,
            "teams": self.teams,
            "toss_winner": self.toss_winner,
            "batting_team": self.batting_team,
            "bowling_team": self.bowling_team,
            "innings_order": self.innings_order,
            "score": self.score,
            "innings_history": self.innings_history,
            "current_batter_id": self.current_batter_id,
            "current_bowler_id": self.current_bowler_id,
            "current_bowler_style": self.current_bowler_style,
            "ready": self.ready,
            "over_state": self.over_state,
            "match_stats": self.match_stats,
            "pending_action": self.pending_action,
            "pending_delivery": self.pending_delivery,
            "pending_catch": self.pending_catch,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Match":
        return cls(**data)


def make_match(chat_id: int, overs: int, captain_id: int, captain_name: str) -> Match:
    cap = {"id": int(captain_id), "name": captain_name}
    match = Match(chat_id=chat_id, overs=overs)
    match.captains = {"A": cap}
    match.teams = {
        "A": {
            "name": None,
            "captain_id": int(captain_id),
            "players": [new_player(captain_id, captain_name, True)],
        },
        "B": {"name": None, "captain_id": None, "players": []},
    }
    match.ready = {str(captain_id): False}
    reset_score(match)
    return match


def reset_score(match: Match) -> None:
    match.score = {
        "runs": 0,
        "wickets": 0,
        "legal_balls": 0,
        "timeline": [],
        "last_delivery": "None",
        "last_length_ok": None,
        "over_events": [],
    }
    match.over_state = {
        "delivery_counts": {},
        "last_code": None,
        "consecutive": 0,
        "bouncers": 0,
        "hard_slots": 0,
    }
    match.current_batter_id = None
    match.current_bowler_id = None
    match.current_bowler_style = None
    match.pending_delivery = None
    match.pending_catch = None

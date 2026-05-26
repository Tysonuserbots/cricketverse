from __future__ import annotations

import random
from typing import Any

from .game_data import (
    CATCH_DROP_RUNS,
    CATCH_TIME_WEIGHTS,
    DELIVERIES_BY_STYLE,
    HARD_WICKET_TYPES,
    MISS_RUN_WEIGHTS,
)
from .models import Match, new_player_stats


def weighted_choice(weights: dict[Any, int]) -> Any:
    total = sum(weights.values())
    pick = random.uniform(0, total)
    upto = 0
    for item, weight in weights.items():
        upto += weight
        if pick <= upto:
            return item
    return next(reversed(weights))


def overs_text(legal_balls: int) -> str:
    return f"{legal_balls // 6}.{legal_balls % 6}"


def balls_limit(match: Match) -> int:
    return match.overs * 6


def balls_left(match: Match) -> int:
    return max(0, balls_limit(match) - int(match.score["legal_balls"]))


def current_run_rate(match: Match) -> float:
    balls = int(match.score["legal_balls"])
    if balls == 0:
        return 0.0
    return float(match.score["runs"]) * 6 / balls


def required_run_rate(match: Match) -> float | None:
    if not match.target:
        return None
    remaining = balls_left(match)
    if remaining <= 0:
        return None
    needed = max(0, match.target - int(match.score["runs"]))
    return needed * 6 / remaining


def ensure_match_player_stats(match: Match) -> None:
    for team_key, team in match.teams.items():
        for player in team["players"]:
            pid = str(player["id"])
            if pid not in match.match_stats:
                match.match_stats[pid] = new_player_stats(player["name"], team_key)


def get_team_key_for_player(match: Match, user_id: int) -> str | None:
    for team_key, team in match.teams.items():
        if any(int(player["id"]) == int(user_id) for player in team["players"]):
            return team_key
    return None


def get_player(match: Match, user_id: int) -> dict[str, Any] | None:
    for team in match.teams.values():
        for player in team["players"]:
            if int(player["id"]) == int(user_id):
                return player
    return None


def active_players(match: Match, team_key: str) -> list[dict[str, Any]]:
    return list(match.teams[team_key]["players"])


def available_batters(match: Match, team_key: str) -> list[dict[str, Any]]:
    return [player for player in match.teams[team_key]["players"] if not player.get("out")]


def team_name(match: Match, team_key: str | None) -> str:
    if not team_key:
        return "None"
    return match.teams[team_key].get("name") or f"Team {team_key}"


def all_out(match: Match) -> bool:
    batting_team = match.batting_team
    if not batting_team:
        return False
    team_size = len(match.teams[batting_team]["players"])
    return team_size > 0 and int(match.score["wickets"]) >= team_size


def innings_over(match: Match) -> bool:
    if match.target and int(match.score["runs"]) >= match.target:
        return True
    return int(match.score["legal_balls"]) >= balls_limit(match) or all_out(match)


def legal_over_complete(match: Match) -> bool:
    return int(match.score["legal_balls"]) > 0 and int(match.score["legal_balls"]) % 6 == 0


def choose_length(style: str, code: int) -> str:
    delivery = DELIVERIES_BY_STYLE[style][code]
    return random.choice(delivery.lengths)


def length_matches(actual_length: str, batter_length: str) -> bool:
    return actual_length.strip().lower() == batter_length.strip().lower()


def miss_runs(style: str, code: int, length: str, batter_run: int) -> int:
    delivery = DELIVERIES_BY_STYLE[style][code]
    legal = [run for run in delivery.mlr[length] if run != int(batter_run)]
    if not legal:
        legal = list(delivery.mlr[length])
    weights = {run: MISS_RUN_WEIGHTS.get(run, 1) for run in legal}
    return int(weighted_choice(weights))


def next_extra(match: Match, style: str, code: int) -> str | None:
    delivery = DELIVERIES_BY_STYLE[style][code]
    counts = match.over_state["delivery_counts"]
    code_key = str(code)
    usage_after = int(counts.get(code_key, 0)) + 1
    consecutive_after = int(match.over_state["consecutive"]) + 1 if match.over_state["last_code"] == code else 1

    if usage_after >= 4:
        return "no_ball" if random.randint(1, 100) <= 80 else "wide"
    if consecutive_after >= 3:
        return "no_ball" if random.randint(1, 100) <= 70 else None
    if consecutive_after == 2:
        return "wide" if random.randint(1, 100) <= 30 else None

    roll = random.randint(1, 100)
    if roll <= delivery.wide_pct:
        return "wide"
    if roll <= delivery.wide_pct + delivery.no_ball_pct:
        return "no_ball"
    if roll <= delivery.wide_pct + delivery.no_ball_pct + delivery.leg_bye_pct:
        return "leg_bye"
    return None


def register_delivery_use(match: Match, style: str, code: int) -> None:
    delivery = DELIVERIES_BY_STYLE[style][code]
    counts = match.over_state["delivery_counts"]
    code_key = str(code)
    counts[code_key] = int(counts.get(code_key, 0)) + 1
    if match.over_state["last_code"] == code:
        match.over_state["consecutive"] = int(match.over_state["consecutive"]) + 1
    else:
        match.over_state["last_code"] = code
        match.over_state["consecutive"] = 1
    if delivery.bouncer:
        match.over_state["bouncers"] = int(match.over_state["bouncers"]) + 1
    if delivery.hard or delivery.bouncer:
        match.over_state["hard_slots"] = int(match.over_state["hard_slots"]) + 1


def hard_ball_forces_miss_logic(match: Match, style: str, code: int) -> bool:
    delivery = DELIVERIES_BY_STYLE[style][code]
    return (delivery.hard or delivery.bouncer) and int(match.over_state["hard_slots"]) <= 3


def score_runs_for_ball(match: Match, style: str, code: int, length: str, batter_run: int, ok: bool) -> int:
    if ok:
        return int(batter_run)
    if hard_ball_forces_miss_logic(match, style, code):
        return miss_runs(style, code, length, batter_run)
    delivery = DELIVERIES_BY_STYLE[style][code]
    if delivery.hard and int(match.over_state["hard_slots"]) > 3:
        return int(batter_run)
    return miss_runs(style, code, length, batter_run)


def wicket_check(match: Match, style: str, code: int, length_ok: bool, batter_run: int) -> dict[str, Any]:
    delivery = DELIVERIES_BY_STYLE[style][code]
    bfr_equals_br = int(code) == int(batter_run)
    if bfr_equals_br:
        roll = random.randint(1, 100)
        if length_ok:
            if roll <= 30:
                return {"kind": "direct", "wicket_type": random.choice(HARD_WICKET_TYPES)}
            if roll <= 90:
                return {"kind": "none"}
            return {"kind": "run_out"}
        if roll <= 60:
            return {"kind": "direct", "wicket_type": random.choice(HARD_WICKET_TYPES)}
        if roll <= 90:
            return {"kind": "catch", "catch_type": 1}
        return {"kind": "run_out"}

    if not length_ok and delivery.catch_ball and random.randint(1, 100) <= 30:
        return {"kind": "catch", "catch_type": 2}
    return {"kind": "none"}


def make_pending_delivery(match: Match, style: str, code: int, batter_run: int, batter_length: str) -> dict[str, Any]:
    delivery = DELIVERIES_BY_STYLE[style][code]
    existing = match.pending_delivery or {}
    length = existing.get("actual_length") or choose_length(style, code)
    ok = length_matches(length, batter_length)
    extra = next_extra(match, style, code)
    register_delivery_use(match, style, code)
    return {
        "style": style,
        "code": code,
        "delivery_name": delivery.name,
        "length": length,
        "batter_length": batter_length,
        "length_ok": ok,
        "batter_run": int(batter_run),
        "extra": extra,
    }


def choose_fielder(match: Match) -> dict[str, Any] | None:
    bowling_team = match.bowling_team
    if not bowling_team:
        return None
    candidates = [p for p in match.teams[bowling_team]["players"] if int(p["id"]) != int(match.current_bowler_id or 0)]
    if not candidates:
        candidates = list(match.teams[bowling_team]["players"])
    return random.choice(candidates) if candidates else None


def build_pending_catch(match: Match, wicket: dict[str, Any]) -> dict[str, Any] | None:
    fielder = choose_fielder(match)
    if not fielder:
        return None
    air_time = int(weighted_choice(CATCH_TIME_WEIGHTS))
    pending = {
        "fielder_id": int(fielder["id"]),
        "fielder_name": fielder["name"],
        "answer": int(match.pending_delivery["batter_run"]),
        "air_time": air_time,
        "drop_runs": CATCH_DROP_RUNS[air_time],
        "catch_type": int(wicket["catch_type"]),
    }
    match.pending_catch = pending
    match.phase = "catch_pending"
    return pending


def apply_ball(
    match: Match,
    *,
    bat_runs: int,
    extra_runs: int = 0,
    legal: bool = True,
    wicket_type: str | None = None,
    fielder_id: int | None = None,
    timeline_token: str | None = None,
    batter_ball: bool = True,
    bowler_charged_runs: int | None = None,
) -> None:
    ensure_match_player_stats(match)
    batter_id = str(match.current_batter_id)
    bowler_id = str(match.current_bowler_id)
    match.score["runs"] = int(match.score["runs"]) + int(bat_runs) + int(extra_runs)

    if timeline_token is None:
        timeline_token = str(bat_runs)
    match.score["timeline"].append(timeline_token)
    match.score["over_events"].append(timeline_token)

    if batter_id in match.match_stats:
        batting = match.match_stats[batter_id]["batting"]
        batting["runs"] += int(bat_runs)
        if batter_ball:
            batting["balls"] += 1
        if int(bat_runs) == 4:
            batting["fours"] += 1
        if int(bat_runs) == 6:
            batting["sixes"] += 1

    if bowler_id in match.match_stats:
        bowling = match.match_stats[bowler_id]["bowling"]
        if legal:
            bowling["balls"] += 1
        bowling["runs"] += int(bowler_charged_runs if bowler_charged_runs is not None else bat_runs + extra_runs)
        if timeline_token.endswith("wd"):
            bowling["wides"] += 1
        if "NB" in timeline_token:
            bowling["no_balls"] += 1

    if legal:
        match.score["legal_balls"] = int(match.score["legal_balls"]) + 1

    if wicket_type:
        match.score["wickets"] = int(match.score["wickets"]) + 1
        if batter_id in match.match_stats:
            match.match_stats[batter_id]["batting"]["out"] = True
            match.match_stats[batter_id]["batting"]["dismissal"] = wicket_type
        player = get_player(match, int(match.current_batter_id))
        if player:
            player["out"] = True
        if bowler_id in match.match_stats and wicket_type != "Run Out":
            match.match_stats[bowler_id]["bowling"]["wickets"] += 1
        if fielder_id and str(fielder_id) in match.match_stats:
            fielding = match.match_stats[str(fielder_id)]["fielding"]
            if wicket_type == "Catch Out":
                fielding["catches"] += 1
            if wicket_type == "Run Out":
                fielding["runouts"] += 1
        match.current_batter_id = None


def resolve_pending_delivery(match: Match) -> dict[str, Any]:
    data = match.pending_delivery
    if not data:
        return {"status": "none"}

    style = data["style"]
    code = int(data["code"])
    delivery_name = data["delivery_name"]
    length = data["length"]
    batter_length = data.get("batter_length", "Unknown")
    length_ok = bool(data["length_ok"])
    batter_run = int(data["batter_run"])
    extra = data["extra"]

    match.score["last_delivery"] = f"{delivery_name} Length {length} (bat: {batter_length})"
    match.score["last_length_ok"] = length_ok

    if extra == "wide":
        apply_ball(
            match,
            bat_runs=0,
            extra_runs=1,
            legal=False,
            timeline_token="wd",
            batter_ball=False,
            bowler_charged_runs=1,
        )
        match.pending_delivery = None
        return {
            "status": "extra",
            "extra": "wide",
            "text": "Wide ball",
            "delivery": delivery_name,
            "length": length,
            "batter_length": batter_length,
        }

    if extra == "leg_bye":
        apply_ball(
            match,
            bat_runs=0,
            extra_runs=1,
            legal=True,
            timeline_token="1lb",
            batter_ball=True,
            bowler_charged_runs=0,
        )
        match.pending_delivery = None
        return {
            "status": "extra",
            "extra": "leg_bye",
            "text": "Leg bye",
            "delivery": delivery_name,
            "length": length,
            "batter_length": batter_length,
        }

    bat_runs = score_runs_for_ball(match, style, code, length, batter_run, length_ok)

    if extra == "no_ball":
        total = bat_runs + 1
        token = f"{total}NB"
        apply_ball(
            match,
            bat_runs=bat_runs,
            extra_runs=1,
            legal=False,
            timeline_token=token,
            batter_ball=False,
            bowler_charged_runs=total,
        )
        match.pending_delivery = None
        return {
            "status": "extra",
            "extra": "no_ball",
            "text": "No ball",
            "runs": total,
            "delivery": delivery_name,
            "length": length,
            "batter_length": batter_length,
        }

    wicket = wicket_check(match, style, code, length_ok, batter_run)
    if wicket["kind"] == "catch":
        pending = build_pending_catch(match, wicket)
        if pending:
            return {"status": "catch_pending", "pending": pending}
        wicket = {"kind": "direct", "wicket_type": "Catch Out"}

    if wicket["kind"] == "run_out":
        apply_ball(
            match,
            bat_runs=0,
            legal=True,
            wicket_type="Run Out",
            timeline_token="W(ro)",
        )
        match.pending_delivery = None
        return {
            "status": "wicket",
            "wicket_type": "Run Out",
            "delivery": delivery_name,
            "length": length,
            "batter_length": batter_length,
            "length_ok": length_ok,
        }

    if wicket["kind"] == "direct":
        token_map = {"Bowled": "W(b)", "LBW": "W(lbw)", "Stumped": "W(st)", "Catch Out": "W(c)"}
        apply_ball(
            match,
            bat_runs=0,
            legal=True,
            wicket_type=wicket["wicket_type"],
            timeline_token=token_map.get(wicket["wicket_type"], "W"),
        )
        match.pending_delivery = None
        return {
            "status": "wicket",
            "wicket_type": wicket["wicket_type"],
            "delivery": delivery_name,
            "length": length,
            "batter_length": batter_length,
            "length_ok": length_ok,
        }

    apply_ball(match, bat_runs=bat_runs, legal=True, timeline_token=str(bat_runs))
    match.pending_delivery = None
    return {
        "status": "runs",
        "runs": bat_runs,
        "delivery": delivery_name,
        "length": length,
        "batter_length": batter_length,
        "length_ok": length_ok,
    }


def finish_catch(match: Match, guess: int | None) -> dict[str, Any]:
    pending = match.pending_catch
    if not pending:
        return {"status": "none"}
    correct = guess is not None and int(guess) == int(pending["answer"])
    if correct:
        apply_ball(
            match,
            bat_runs=0,
            legal=True,
            wicket_type="Catch Out",
            fielder_id=int(pending["fielder_id"]),
            timeline_token="W(c)",
        )
        result = {
            "status": "out",
            "fielder_name": pending["fielder_name"],
            "catch_type": pending["catch_type"],
        }
    else:
        drop_runs = int(pending["drop_runs"])
        apply_ball(
            match,
            bat_runs=drop_runs,
            legal=True,
            timeline_token=str(drop_runs),
        )
        fid = str(pending["fielder_id"])
        if fid in match.match_stats:
            match.match_stats[fid]["fielding"]["drops"] += 1
        result = {
            "status": "dropped",
            "fielder_name": pending["fielder_name"],
            "runs": drop_runs,
            "timeout": guess is None,
        }
    match.pending_catch = None
    match.pending_delivery = None
    match.phase = "playing"
    return result

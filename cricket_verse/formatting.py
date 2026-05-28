from __future__ import annotations

from typing import Any

from .engine import current_run_rate, in_powerplay, overs_text, required_run_rate, team_name
from .models import Match


def player_name(match: Match, user_id: int | None) -> str:
    if not user_id:
        return "None"
    for team in match.teams.values():
        for player in team["players"]:
            if int(player["id"]) == int(user_id):
                return player["name"]
    return str(user_id)


def batter_line(match: Match) -> str:
    if not match.current_batter_id:
        return "┃ ➠ None • 0 (0) ┃\n┃ ⚡ SR • 0.00 ┃"
    stats = match.match_stats.get(str(match.current_batter_id), {}).get("batting", {})
    runs = int(stats.get("runs", 0))
    balls = int(stats.get("balls", 0))
    sr = runs * 100 / balls if balls else 0.0
    return f"┃ ➠ {player_name(match, match.current_batter_id)} • {runs} ({balls}) ┃\n┃ ⚡ SR • {sr:.2f} ┃"


def bowler_line(match: Match) -> str:
    if not match.current_bowler_id:
        return "┃ ➠ None • 0W ┃\n┃ ©️0.0 • 0 ┃"
    stats = match.match_stats.get(str(match.current_bowler_id), {}).get("bowling", {})
    balls = int(stats.get("balls", 0))
    runs = int(stats.get("runs", 0))
    wickets = int(stats.get("wickets", 0))
    return (
        f"┃ ➠ {player_name(match, match.current_bowler_id)} • {wickets}W ┃\n"
        f"┃ ©️{overs_text(balls)} • {runs} ┃"
    )


def timeline(match: Match) -> str:
    items = match.score.get("timeline", [])[-8:]
    if not items:
        return "⬤"
    return " | ".join(str(item) for item in items)


def scoreboard(match: Match) -> str:
    batting = team_name(match, match.batting_team)
    bowling = team_name(match, match.bowling_team)
    score = match.score
    crr = current_run_rate(match)
    rrr = required_run_rate(match)
    rrr_line = f"┃ 📊 RRR • {rrr:.2f} ┃\n" if match.innings == 2 and rrr is not None else ""
    last_ok = score.get("last_length_ok")
    length_mark = "✔" if last_ok is True else "✘" if last_ok is False else "-"
    target_line = ""
    if match.target:
        target_line = f"\n🎯 Target: {match.target} in {match.overs * 6} balls"
    pp_line = f"\nPP: {match.powerplay_overs} over(s)" if in_powerplay(match) else ""
    free_hit_line = "\nFREE HIT ACTIVE" if match.over_state.get("free_hit") else ""
    innings_banner = f"╔━━━━━━━╗\n➠ INNINGS -{match.innings}\n╚━━━━━━━╝\n" if match.innings == 2 else ""
    return (
        f"{innings_banner}"
        f"༺━━━━━━━━━━━━━━━━━༻\n"
        f"🏏 {batting} {score['runs']} / {score['wickets']}\n"
        f"🥎 {bowling} - {overs_text(score['legal_balls'])}/{match.overs}"
        f"{target_line}{pp_line}{free_hit_line}\n"
        f"⚔══════════════════⚔\n"
        f"⏱ {overs_text(score['legal_balls'])} OVER • LIVE\n"
        f"╭━━━━━━━━━━━━╮\n"
        f"┃ 📈 CRR • {crr:.2f} ┃\n"
        f"{rrr_line}"
        f"╰━━━━━━━━━━━━╯\n"
        f"╭━━━ 🏌️‍♂️ BATTER ━━━╮\n"
        f"{batter_line(match)}\n"
        f"╰━━━━━━━━━━━━━━╯\n"
        f"╭━━━ ⛹🏼‍♂️ BOWLER ━━╮\n"
        f"{bowler_line(match)}\n"
        f"╰━━━━━━━━━━━━━╯\n"
        f"Last Delivery - {score.get('last_delivery', 'None')} {length_mark}\n"
        f"TIMELINE\n"
        f"╒═══════════════════╕\n"
        f"| {timeline(match)} |\n"
        f"╘═══════════════════╛\n"
        f"⚔══════════════════⚔"
    )


def teams_text(match: Match) -> str:
    lines = ["🏏 Cricket Verse Team Setup", ""]
    for key in ("A", "B"):
        team = match.teams[key]
        cap_id = team.get("captain_id")
        name = team.get("name") or f"Team {key} name pending"
        lines.append(f"{key}. {name}")
        for idx, player in enumerate(team["players"], start=1):
            cap = " (cap)" if int(player["id"]) == int(cap_id or 0) else ""
            out = " OUT" if player.get("out") else ""
            style = f" [{player['style']}]" if player.get("style") else ""
            lines.append(f"{idx}) {player['name']}{cap}{style}{out}")
        lines.append("")
    lines.append(f"Batting: {team_name(match, match.batting_team)}")
    lines.append(f"Bowling: {team_name(match, match.bowling_team)}")
    lines.append(f"Current batter: {player_name(match, match.current_batter_id)}")
    lines.append(f"Current bowler: {player_name(match, match.current_bowler_id)}")
    return "\n".join(lines)


def team_roster_text(match: Match, team_key: str) -> str:
    team = match.teams[team_key]
    cap_id = team.get("captain_id")
    role = "Batting" if team_key == match.batting_team else "Bowling" if team_key == match.bowling_team else "Waiting"
    changes_left = max(0, 2 - int(match.captain_change_counts.get(str(cap_id), 0))) if cap_id else 0
    lines = [
        f"{team_name(match, team_key)}",
        f"Role: {role}",
        f"Mid-match changes left: {changes_left}",
        "",
        "Your team:",
    ]
    for idx, player in enumerate(team["players"], start=1):
        cap = " (cap)" if int(player["id"]) == int(cap_id or 0) else ""
        out = " OUT" if player.get("out") else ""
        style = f" [{player['style']}]" if player.get("style") else ""
        lines.append(f"{idx}) {player['name']}{cap}{style}{out}")
    if team_key == match.batting_team:
        lines.extend(["", f"Current batter: {player_name(match, match.current_batter_id)}"])
    if team_key == match.bowling_team:
        lines.extend(["", f"Current bowler: {player_name(match, match.current_bowler_id)}"])
    return "\n".join(lines)


def innings_scorecard(match: Match, title: str = "INNINGS SCORECARD") -> str:
    batting_key = match.batting_team
    bowling_key = match.bowling_team
    lines = [
        f"╔════════════════╗",
        f"🏏 {title}",
        f"╚════════════════╝",
        f"{team_name(match, batting_key)} {match.score['runs']}/{match.score['wickets']} ({overs_text(match.score['legal_balls'])})",
        "",
        "BATTERS",
    ]
    if batting_key:
        for player in match.teams[batting_key]["players"]:
            stats = match.match_stats.get(str(player["id"]), {}).get("batting", {})
            dismissal = stats.get("dismissal") or ("not out" if stats else "did not bat")
            lines.append(
                f"• {player['name']} - {stats.get('runs', 0)} ({stats.get('balls', 0)}) {dismissal}"
            )
    lines.append("")
    lines.append("BOWLERS")
    if bowling_key:
        for player in match.teams[bowling_key]["players"]:
            stats = match.match_stats.get(str(player["id"]), {}).get("bowling", {})
            if stats.get("balls", 0) or stats.get("runs", 0) or stats.get("wickets", 0):
                lines.append(
                    f"• {player['name']} - {overs_text(stats.get('balls', 0))} ov, "
                    f"{stats.get('runs', 0)} runs, {stats.get('wickets', 0)}W"
                )
    return "\n".join(lines)


def match_summary(match: Match, result: str) -> dict[str, Any]:
    return {
        "result": result,
        "overs": match.overs,
        "powerplay_overs": match.powerplay_overs,
        "teams": {
            key: {
                "name": team_name(match, key),
                "captain_id": match.teams[key].get("captain_id"),
                "players": match.teams[key].get("players", []),
            }
            for key in match.teams
        },
        "innings_history": match.innings_history,
        "players": match.match_stats,
        "player_of_match": match.player_of_match,
    }


def player_of_match_text(match: Match) -> str:
    pom = match.player_of_match or {}
    if not pom:
        return "Player of the Match: not available."
    return f"Player of the Match: {pom.get('name')} - {pom.get('reason')}"


def completed_match_text(record: dict[str, Any]) -> str:
    summary = record["summary"]
    lines = [
        f"Match #{record['id']}",
        summary.get("result", "Result not recorded"),
        f"Saved: {record.get('created_at')}",
        "",
    ]
    for innings in summary.get("innings_history", []):
        lines.append(
            f"Innings {innings.get('innings')}: {innings.get('team')} "
            f"{innings.get('runs')}/{innings.get('wickets')} ({overs_text(int(innings.get('balls', 0)))})"
        )
    pom = summary.get("player_of_match") or {}
    if pom:
        lines.extend(["", f"Player of the Match: {pom.get('name')} - {pom.get('reason')}"])
    lines.append("")
    lines.append("Player data")
    players = summary.get("players", {})
    for stats in players.values():
        batting = stats.get("batting", {})
        bowling = stats.get("bowling", {})
        fielding = stats.get("fielding", {})
        lines.append(
            f"- {stats.get('name')} ({team_label(summary, stats.get('team'))}): "
            f"{batting.get('runs', 0)}({batting.get('balls', 0)}), "
            f"{bowling.get('wickets', 0)}W/{bowling.get('runs', 0)}, "
            f"C {fielding.get('catches', 0)}, RO {fielding.get('runouts', 0)}, D {fielding.get('drops', 0)}"
        )
    return "\n".join(lines)


def team_label(summary: dict[str, Any], team_key: str | None) -> str:
    teams = summary.get("teams", {})
    if team_key and team_key in teams:
        return teams[team_key].get("name") or f"Team {team_key}"
    return str(team_key or "Team")


def profile_text(profile: dict[str, Any]) -> str:
    runs = int(profile.get("runs") or 0)
    balls = int(profile.get("balls") or 0)
    sr = runs * 100 / balls if balls else 0.0
    return (
        f"{profile.get('display_name', profile.get('tg_id'))}\n"
        f"Matches: {profile.get('matches', 0)} | Runs: {runs} | SR: {sr:.2f}\n"
        f"Wickets: {profile.get('wickets', 0)} | Catches: {profile.get('catches', 0)} | POTM: {profile.get('player_of_match', 0)}\n"
        f"Puzzle games: {profile.get('games_won', 0)}W/{profile.get('games_lost', 0)}L from {profile.get('games_played', 0)}"
    )

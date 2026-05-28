from __future__ import annotations

import logging
import asyncio
import random
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings, load_settings
from .database import Database
from .engine import (
    available_batters,
    balls_left,
    build_pending_catch,
    decide_drs,
    ensure_match_player_stats,
    finish_catch,
    get_player,
    get_team_key_for_player,
    innings_over,
    legal_over_complete,
    choose_length,
    make_pending_delivery,
    overs_text,
    resolve_pending_delivery,
    reset_drs_reviews,
    select_player_of_match,
    team_name,
)
from .formatting import (
    completed_match_text,
    innings_scorecard,
    match_summary,
    player_name,
    player_of_match_text,
    profile_text,
    scoreboard,
    team_roster_text,
    teams_text,
)
from .game_data import DELIVERIES_BY_STYLE, RUN_CHOICES, delivery_label
from .gemini import answer_buzz_question, answer_match_question, answer_player_question, summarize_player
from .models import Match, make_match, new_player, reset_score, user_label


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)


def db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def active_match(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Match | None:
    return db(context).load_match(chat_id)


def captain_team(match: Match, user_id: int) -> str | None:
    for key, team in match.teams.items():
        if int(team.get("captain_id") or 0) == int(user_id):
            return key
    return None


def captain_ids(match: Match) -> list[int]:
    return [int(team["captain_id"]) for team in match.teams.values() if team.get("captain_id")]


def update_match_player_name(match: Match, user: Any) -> None:
    name = user_label(user)
    user_id = int(user.id)
    for cap in match.captains.values():
        if int(cap["id"]) == user_id:
            cap["name"] = name
    for team in match.teams.values():
        for player in team["players"]:
            if int(player["id"]) == user_id:
                player["name"] = name
                if str(user_id) in match.match_stats:
                    match.match_stats[str(user_id)]["name"] = name


def other_team(team_key: str) -> str:
    return "B" if team_key == "A" else "A"


def team_sizes_equal(match: Match) -> bool:
    return len(match.teams["A"]["players"]) == len(match.teams["B"]["players"])


def can_start_match(match: Match) -> bool:
    return team_sizes_equal(match) and bool(match.current_batter_id) and bool(match.current_bowler_id)


def captain_changes_left(match: Match, cap_id: int) -> int:
    used = int(match.captain_change_counts.get(str(cap_id), 0))
    return max(0, 2 - used)


def use_captain_change(match: Match, cap_id: int) -> int:
    key = str(cap_id)
    match.captain_change_counts[key] = int(match.captain_change_counts.get(key, 0)) + 1
    return captain_changes_left(match, cap_id)


def append_button_log(match: Match, user: Any, role: str, action: str, value: str) -> None:
    log = {
        "innings": match.innings,
        "over": overs_text(match.score.get("legal_balls", 0)),
        "role": role,
        "player": user_label(user),
        "user_id": int(user.id),
        "action": action,
        "value": value,
    }
    match.button_logs.append(log)
    if len(match.button_logs) > 120:
        match.button_logs = match.button_logs[-120:]


def logs_text(match: Match, limit: int) -> str:
    logs = match.button_logs[-limit:]
    if not logs:
        return "No batter/bowler button logs yet."
    lines = [f"Last {len(logs)} button log(s):"]
    for idx, item in enumerate(logs, start=1):
        lines.append(
            f"{idx}. Inn {item.get('innings')} {item.get('over')} ov - "
            f"{item.get('role')} {item.get('player')} pressed {item.get('action')}: {item.get('value')}"
        )
    return "\n".join(lines)


def explanation_text(match: Match) -> str:
    exp = match.score.get("last_explanation")
    if not exp:
        return "No completed ball explanation yet."
    lines = [
        "Last ball explanation",
        f"Delivery: {exp.get('delivery')} | BFR: {exp.get('bowler_fixed_run')} | Batter run: {exp.get('batter_run')}",
        f"Length: actual {exp.get('actual_length')} vs batter {exp.get('batter_length')} - {'matched' if exp.get('length_ok') else 'missed'}",
        f"Outcome: {exp.get('outcome')} | Runs: {exp.get('runs', 0)}",
        f"Reason: {exp.get('reason')}",
    ]
    if exp.get("hard_ball"):
        lines.append(f"Hard-ball slot: {exp.get('hard_slot')}/{exp.get('hard_limit')} ({'powerplay' if exp.get('powerplay') else 'normal over'})")
    if exp.get("extra_probability"):
        lines.append(f"Extra probability: {exp.get('extra_probability')}")
    if exp.get("wicket_probability"):
        lines.append(f"Wicket probability: {exp.get('wicket_probability')}")
    if exp.get("free_hit_active"):
        lines.append("Free hit was active before this ball.")
    return "\n".join(lines)


def reset_ready(match: Match) -> None:
    match.ready = {str(cid): False for cid in captain_ids(match)}


def reset_over_state(match: Match) -> None:
    free_hit = bool(match.over_state.get("free_hit", False))
    match.over_state = {
        "delivery_counts": {},
        "last_code": None,
        "consecutive": 0,
        "bouncers": 0,
        "hard_slots": 0,
        "batter_bouncers": 0,
        "free_hit": free_hit,
    }
    match.score["over_events"] = []


def join_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Join as Captain 2", callback_data="join")]])


def toss_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Bat", callback_data="toss:bat"), InlineKeyboardButton("Bowl", callback_data="toss:bowl")]]
    )


def admin_approval_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Admin Approve Start", callback_data="admin_start")]])


def team_menu_markup(match: Match, team_key: str, cap_id: int) -> InlineKeyboardMarkup:
    if can_start_match(match):
        ready_label = "Start ✓" if match.ready.get(str(cap_id)) else "Start"
    else:
        ready_label = "Start Locked 🔒"
    rows = [
        [
            InlineKeyboardButton("Add", callback_data=f"team:add:{team_key}"),
            InlineKeyboardButton("Remove", callback_data=f"team:remove:{team_key}"),
            InlineKeyboardButton("Select", callback_data=f"team:select:{team_key}"),
            InlineKeyboardButton("Change", callback_data=f"team:change:{team_key}"),
        ],
        [InlineKeyboardButton(ready_label, callback_data=f"ready:{cap_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def ready_markup(match: Match) -> InlineKeyboardMarkup:
    rows = []
    for cap_id in captain_ids(match):
        if can_start_match(match):
            label = "Start ✓" if match.ready.get(str(cap_id)) else "Start"
        else:
            label = "Start Locked 🔒"
        rows.append([InlineKeyboardButton(f"{label} - {player_name(match, cap_id)}", callback_data=f"ready:{cap_id}")])
    return InlineKeyboardMarkup(rows)


def remove_markup(match: Match, team_key: str) -> InlineKeyboardMarkup:
    rows = []
    cap_id = int(match.teams[team_key]["captain_id"])
    for idx, player in enumerate(match.teams[team_key]["players"], start=1):
        if int(player["id"]) == cap_id:
            continue
        rows.append([InlineKeyboardButton(f"{idx}. {player['name']}", callback_data=f"remove:{team_key}:{player['id']}")])
    rows = rows or [[InlineKeyboardButton("No removable players", callback_data="noop")]]
    rows.append([InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")])
    return InlineKeyboardMarkup(rows)


def select_batter_markup(match: Match, team_key: str) -> InlineKeyboardMarkup:
    rows = []
    for idx, player in enumerate(available_batters(match, team_key), start=1):
        rows.append([InlineKeyboardButton(f"{idx}. {player['name']}", callback_data=f"pick_batter:{player['id']}")])
    rows = rows or [[InlineKeyboardButton("No batters available", callback_data="noop")]]
    rows.append([InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")])
    return InlineKeyboardMarkup(rows)


def select_bowler_markup(match: Match, team_key: str) -> InlineKeyboardMarkup:
    rows = []
    for idx, player in enumerate(match.teams[team_key]["players"], start=1):
        style = f" [{player['style']}]" if player.get("style") else ""
        rows.append([InlineKeyboardButton(f"{idx}. {player['name']}{style}", callback_data=f"pick_bowler:{player['id']}")])
    rows.append([InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")])
    return InlineKeyboardMarkup(rows)


def change_batter_markup(match: Match, team_key: str) -> InlineKeyboardMarkup:
    rows = []
    for idx, player in enumerate(available_batters(match, team_key), start=1):
        if int(player["id"]) == int(match.current_batter_id or 0):
            continue
        rows.append([InlineKeyboardButton(f"{idx}. {player['name']}", callback_data=f"change_batter:{player['id']}")])
    rows = rows or [[InlineKeyboardButton("No alternate batters", callback_data="noop")]]
    rows.append([InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")])
    return InlineKeyboardMarkup(rows)


def change_bowler_markup(match: Match, team_key: str) -> InlineKeyboardMarkup:
    rows = []
    for idx, player in enumerate(match.teams[team_key]["players"], start=1):
        if int(player["id"]) == int(match.current_bowler_id or 0):
            continue
        style = f" [{player['style']}]" if player.get("style") else ""
        rows.append([InlineKeyboardButton(f"{idx}. {player['name']}{style}", callback_data=f"change_bowler:{player['id']}")])
    rows = rows or [[InlineKeyboardButton("No alternate bowlers", callback_data="noop")]]
    rows.append([InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")])
    return InlineKeyboardMarkup(rows)


def style_markup(player_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Pacer", callback_data=f"style:{player_id}:pacer"),
                InlineKeyboardButton("Spinner", callback_data=f"style:{player_id}:spinner"),
            ]
        ]
    )


def bowling_markup(match: Match) -> InlineKeyboardMarkup:
    style = match.current_bowler_style or "pacer"
    rows = []
    buttons = []
    for code in sorted(DELIVERIES_BY_STYLE[style]):
        delivery = DELIVERIES_BY_STYLE[style][code]
        if delivery.bouncer and int(match.over_state.get("bouncers", 0)) >= 2:
            buttons.append(InlineKeyboardButton(f"{code} {delivery.name} 🔒", callback_data="locked:bouncer"))
        else:
            buttons.append(InlineKeyboardButton(delivery_label(style, code), callback_data=f"bowl:{code}"))
        if len(buttons) == 2:
            rows.append(buttons)
            buttons = []
    if buttons:
        rows.append(buttons)
    return InlineKeyboardMarkup(rows)


def run_markup() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(str(run), callback_data=f"bat:{run}") for run in RUN_CHOICES[:3]],
        [InlineKeyboardButton(str(run), callback_data=f"bat:{run}") for run in RUN_CHOICES[3:]],
    ]
    return InlineKeyboardMarkup(rows)


def length_markup(match: Match) -> InlineKeyboardMarkup:
    style = match.pending_delivery.get("style", match.current_bowler_style or "pacer")
    code = int(match.pending_delivery.get("code", 0))
    delivery = DELIVERIES_BY_STYLE[style][code]
    lengths = ["Full", "Yorker", "Good", "Short"]
    if int(match.over_state.get("batter_bouncers", 0)) < 1:
        lengths.append("Bouncer")
    rows = []
    row = []
    for length in lengths:
        row.append(InlineKeyboardButton(length, callback_data=f"length:{length}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def catch_markup() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(str(run), callback_data=f"catch:{run}") for run in RUN_CHOICES[:3]],
        [InlineKeyboardButton(str(run), callback_data=f"catch:{run}") for run in RUN_CHOICES[3:]],
    ]
    return InlineKeyboardMarkup(rows)


def drs_markup(match: Match, team_key: str | None) -> InlineKeyboardMarkup | None:
    if not team_key:
        return None
    reviews = int(match.drs_reviews.get(team_key, 0))
    if reviews <= 0:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"DRS ({reviews} left)", callback_data="drs")]])


async def answer_not_you(query: Any, required_name: str) -> None:
    await query.answer(f"You are not {required_name}!", show_alert=True)


async def edit_main(
    context: ContextTypes.DEFAULT_TYPE,
    match: Match,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not match.main_message_id:
        sent = await context.bot.send_message(match.chat_id, text, reply_markup=reply_markup)
        match.main_message_id = sent.message_id
        return
    try:
        await context.bot.edit_message_text(
            chat_id=match.chat_id,
            message_id=match.main_message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            sent = await context.bot.send_message(match.chat_id, text, reply_markup=reply_markup)
            match.main_message_id = sent.message_id


async def edit_query_message(query: Any, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc) and query.message:
            await query.message.reply_text(text, reply_markup=reply_markup)


async def edit_team_menu_by_id(
    context: ContextTypes.DEFAULT_TYPE,
    match: Match,
    team_key: str,
    message_id: int | None,
    prefix: str | None = None,
) -> None:
    if not message_id:
        return
    cap_id = int(match.teams[team_key]["captain_id"])
    text = team_roster_text(match, team_key)
    if prefix:
        text = f"{prefix}\n\n{text}"
    try:
        await context.bot.edit_message_text(
            chat_id=match.chat_id,
            message_id=int(message_id),
            text=text,
            reply_markup=team_menu_markup(match, team_key, cap_id),
        )
    except BadRequest:
        return


def split_telegram_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        candidate = paragraph if not current else f"{current}\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


async def reply_long(update: Update, text: str) -> None:
    if not update.message:
        return
    for chunk in split_telegram_text(text):
        await update.message.reply_text(chunk)


async def save_and_show_setup(context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    await edit_main(context, match, teams_text(match), ready_markup(match))
    db(context).save_match(match)


async def playmatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    chat_id = update.effective_chat.id
    if active_match(context, chat_id):
        await update.message.reply_text("A match is already active in this chat. Use /cancelmatch to stop it.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Use: /playmatch <overs> <powerplay_overs>")
        return
    overs = int(context.args[0])
    if overs < 1 or overs > 50:
        await update.message.reply_text("Overs must be between 1 and 50.")
        return
    if len(context.args) > 1 and not context.args[1].isdigit():
        await update.message.reply_text("Powerplay overs must be a number. Example: /playmatch 5 2")
        return
    pp_overs = int(context.args[1]) if len(context.args) > 1 else 0
    if pp_overs < 0 or pp_overs > overs:
        await update.message.reply_text("Powerplay overs must be from 0 up to total overs.")
        return

    db(context).upsert_user(update.effective_user)
    match = make_match(chat_id, overs, update.effective_user.id, user_label(update.effective_user), pp_overs)
    sent = await update.message.reply_text(
        f"🏏 Cricket Verse match created for {overs} over(s).\n"
        f"Powerplay: {pp_overs} over(s).\n"
        f"Captain 1: {match.captains['A']['name']}\n\n"
        f"Waiting for Captain 2.",
        reply_markup=join_markup(),
    )
    match.main_message_id = sent.message_id
    db(context).save_match(match)


async def cancelmatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("No active match in this chat.")
        return
    if update.effective_user and update.effective_user.id not in captain_ids(match):
        await update.message.reply_text("Only a captain can cancel the match.")
        return
    db(context).delete_match(update.effective_chat.id)
    await update.message.reply_text("Match cancelled.")


async def myteam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("/myteam works only when there is an active match.")
        return
    update_match_player_name(match, update.effective_user)
    db(context).save_match(match)
    team_key = captain_team(match, update.effective_user.id)
    if not team_key:
        await update.message.reply_text("Only captains can use /myteam.")
        return
    await update.message.reply_text(
        team_roster_text(match, team_key),
        reply_markup=team_menu_markup(match, team_key, update.effective_user.id),
    )


async def add_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("/add works only when there is an active match.")
        return
    team_key = captain_team(match, update.effective_user.id)
    if not team_key:
        await update.message.reply_text("Only captains can use /add.")
        return

    player_id, display_name = resolve_player_from_message(update, context, update.message.text or "")
    if not player_id:
        await update.message.reply_text("Reply to a player, tag a Telegram user, or use /add <telegram_id> <name>.")
        return
    if get_player(match, player_id):
        player = get_player(match, player_id)
        if player:
            player["name"] = display_name
        await update.message.reply_text(f"{display_name} is already in this match. Name refreshed.")
        db(context).save_match(match)
        await save_and_show_setup(context, match)
        return

    match.teams[team_key]["players"].append(new_player(player_id, display_name))
    db(context).upsert_manual_player(player_id, display_name)
    ensure_match_player_stats(match)
    reset_ready(match)
    await update.message.reply_text(f"Added {display_name} to {team_name(match, team_key)}.")
    await save_and_show_setup(context, match)


async def howplayed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    target_id = extract_target_id(update.message.text or "", update)
    if not target_id:
        await update.message.reply_text("Use /howplayed <telegram_id>, or reply to a player and say how he played.")
        return
    await send_player_summary(update, context, target_id)


def live_match_snapshot(match: Match) -> dict[str, Any]:
    ensure_match_player_stats(match)
    return {
        "phase": match.phase,
        "innings": match.innings,
        "overs": match.overs,
        "batting_team": team_name(match, match.batting_team),
        "bowling_team": team_name(match, match.bowling_team),
        "target": match.target,
        "innings_history": match.innings_history,
        "score": {
            "runs": match.score.get("runs", 0),
            "wickets": match.score.get("wickets", 0),
            "legal_balls": match.score.get("legal_balls", 0),
            "overs": overs_text(match.score.get("legal_balls", 0)),
            "balls_left": balls_left(match),
            "target": match.target,
            "last_delivery": match.score.get("last_delivery"),
            "timeline": match.score.get("timeline", [])[-12:],
            "drs_reviews": match.drs_reviews,
        },
        "current_batter": {
            "id": match.current_batter_id,
            "name": player_name(match, match.current_batter_id),
            "stats": match.match_stats.get(str(match.current_batter_id), {}).get("batting", {}),
        },
        "current_bowler": {
            "id": match.current_bowler_id,
            "name": player_name(match, match.current_bowler_id),
            "style": match.current_bowler_style,
            "stats": match.match_stats.get(str(match.current_bowler_id), {}).get("bowling", {}),
        },
        "players": match.match_stats,
    }


async def ask_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Use: /ask who is winning this match?")
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("/ask works during an active match only.")
        return
    cfg = settings(context)
    answer = await answer_match_question(cfg.gemini_api_key, cfg.gemini_model, question, live_match_snapshot(match))
    await reply_long(update, answer[:1800])


def buzz_payload(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "recent_matches": db(context).recent_matches(5),
        "leaders": {
            "runs": db(context).career_leaders("runs", 5),
            "wickets": db(context).career_leaders("wickets", 5),
            "catches": db(context).career_leaders("catches", 5),
            "player_of_match": db(context).career_leaders("player_of_match", 5),
        },
    }
    id_match = re.search(r"\b\d+\b", question)
    if id_match:
        record = db(context).completed_match(int(id_match.group(0)))
        if record:
            data["match"] = record
    target_id = extract_question_target_id(update, context, question)
    if target_id:
        data["player_stats"] = db(context).player_stats(target_id)
        data["player_recent"] = db(context).recent_match_stats(target_id)
    return data


async def buzz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Use: /buzz top runs, /buzz most wickets, or /buzz match 12")
        return
    cfg = settings(context)
    answer = await answer_buzz_question(cfg.gemini_api_key, cfg.gemini_model, question, buzz_payload(update, context, question))
    await reply_long(update, answer[:2200])


async def matchin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Use: /matchin <match_id>")
        return
    record = db(context).completed_match(int(context.args[0]))
    if not record:
        await update.message.reply_text(f"No saved match found with id {context.args[0]}.")
        return
    await reply_long(update, completed_match_text(record))


async def myprofile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db(context).upsert_user(update.effective_user)
    profile = db(context).profile(update.effective_user.id)
    if not profile:
        await update.message.reply_text("Profile was not found. Send one more message and try again.")
        return
    await update.message.reply_text(profile_text(profile))


async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    if not await is_chat_admin(context, update.effective_chat.id, update.effective_user.id):
        await update.message.reply_text("Only group admins can use /logs.")
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("No active match in this chat.")
        return
    limit = 10
    if context.args and context.args[0].isdigit():
        limit = max(1, min(50, int(context.args[0])))
    await update.message.reply_text(logs_text(match, limit))


async def exp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    match = active_match(context, update.effective_chat.id)
    if not match:
        await update.message.reply_text("/exp works only during a live match.")
        return
    await update.message.reply_text(explanation_text(match))


def puzzle_games(context: ContextTypes.DEFAULT_TYPE) -> dict[str, dict[str, Any]]:
    return context.application.bot_data.setdefault("puzzle_games", {})


async def games(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Puzzle arena. Play with buttons, no money, no stakes.\nChoose one:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Number Lock", callback_data="puzzle:start:math")],
                [InlineKeyboardButton("Pattern Chase", callback_data="puzzle:start:sequence")],
                [InlineKeyboardButton("Cricket Brain", callback_data="puzzle:start:cricket")],
                [InlineKeyboardButton("2048", callback_data="puzzle:start:2048")],
            ]
        ),
    )


async def puzzle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await games(update, context)


async def game_2048(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    game_id = f"{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
    board = new_2048_board()
    puzzle_games(context)[game_id] = {"type": "2048", "board": board, "score": 0}
    await update.message.reply_text(render_2048(board), reply_markup=markup_2048(game_id))


def make_puzzle(kind: str) -> dict[str, Any]:
    if kind == "math":
        a = random.randint(8, 30)
        b = random.randint(3, 15)
        c = random.randint(2, 9)
        answer = a + b * c
        question = f"Number Lock: {a} + {b} x {c} = ?"
    elif kind == "sequence":
        start = random.randint(1, 8)
        step = random.randint(2, 6)
        answer = start + step * 4
        question = f"Pattern Chase: {start}, {start + step}, {start + step * 2}, {start + step * 3}, ?"
    else:
        needed = random.choice([8, 10, 12, 15])
        balls = random.choice([3, 4, 6])
        if needed <= balls:
            answer = "rotate strike"
        elif needed <= balls * 2:
            answer = "target gaps"
        else:
            answer = "attack boundary"
        question = f"Cricket Brain: Need {needed} from {balls} balls. Best plan?"
        options = ["rotate strike", "target gaps", "attack boundary", "block it"]
        return {"question": question, "options": options, "answer": options.index(answer)}

    options = {answer}
    while len(options) < 4:
        options.add(answer + random.choice([-9, -6, -4, -3, 3, 4, 6, 9]))
    option_list = list(options)
    random.shuffle(option_list)
    return {"question": question, "options": [str(item) for item in option_list], "answer": option_list.index(answer)}


def new_2048_board() -> list[list[int]]:
    board = [[0 for _ in range(4)] for _ in range(4)]
    add_2048_tile(board)
    add_2048_tile(board)
    return board


def add_2048_tile(board: list[list[int]]) -> None:
    empty = [(r, c) for r in range(4) for c in range(4) if board[r][c] == 0]
    if not empty:
        return
    r, c = random.choice(empty)
    board[r][c] = 4 if random.randint(1, 10) == 1 else 2


def merge_2048_line(line: list[int]) -> tuple[list[int], int]:
    values = [value for value in line if value]
    merged: list[int] = []
    gained = 0
    idx = 0
    while idx < len(values):
        if idx + 1 < len(values) and values[idx] == values[idx + 1]:
            value = values[idx] * 2
            merged.append(value)
            gained += value
            idx += 2
        else:
            merged.append(values[idx])
            idx += 1
    return merged + [0] * (4 - len(merged)), gained


def move_2048(board: list[list[int]], direction: str) -> tuple[list[list[int]], bool, int]:
    new_board = [row[:] for row in board]
    gained = 0
    if direction in {"L", "R"}:
        for r in range(4):
            row = new_board[r][:]
            if direction == "R":
                row.reverse()
            merged, score = merge_2048_line(row)
            if direction == "R":
                merged.reverse()
            new_board[r] = merged
            gained += score
    else:
        for c in range(4):
            col = [new_board[r][c] for r in range(4)]
            if direction == "D":
                col.reverse()
            merged, score = merge_2048_line(col)
            if direction == "D":
                merged.reverse()
            for r in range(4):
                new_board[r][c] = merged[r]
            gained += score
    changed = new_board != board
    if changed:
        add_2048_tile(new_board)
    return new_board, changed, gained


def has_2048_moves(board: list[list[int]]) -> bool:
    if any(0 in row for row in board):
        return True
    for r in range(4):
        for c in range(4):
            if r + 1 < 4 and board[r][c] == board[r + 1][c]:
                return True
            if c + 1 < 4 and board[r][c] == board[r][c + 1]:
                return True
    return False


def render_2048(board: list[list[int]], score: int = 0) -> str:
    rows = []
    for row in board:
        rows.append(" | ".join(f"{value or '.':>4}" for value in row))
    return f"2048 Cricket Puzzle\nScore: {score}\n" + "\n".join(rows)


def markup_2048(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Up", callback_data=f"puzzle:2048:{game_id}:U")],
            [
                InlineKeyboardButton("Left", callback_data=f"puzzle:2048:{game_id}:L"),
                InlineKeyboardButton("Right", callback_data=f"puzzle:2048:{game_id}:R"),
            ],
            [InlineKeyboardButton("Down", callback_data=f"puzzle:2048:{game_id}:D")],
        ]
    )


async def start_puzzle_from_query(query: Any, context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    if kind == "2048":
        game_id = f"{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
        board = new_2048_board()
        puzzle_games(context)[game_id] = {"type": "2048", "board": board, "score": 0}
        await edit_query_message(query, render_2048(board), markup_2048(game_id))
        return
    puzzle_id = f"{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
    puzzle_data = make_puzzle(kind)
    puzzle_games(context)[puzzle_id] = puzzle_data
    buttons = [
        [InlineKeyboardButton(option, callback_data=f"puzzle:ans:{puzzle_id}:{idx}")]
        for idx, option in enumerate(puzzle_data["options"])
    ]
    await edit_query_message(
        query,
        f"{puzzle_data['question']}\nPick the answer before someone steals the glory.",
        InlineKeyboardMarkup(buttons),
    )


async def handle_puzzle(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    parts = data.split(":")
    if len(parts) >= 3 and parts[1] == "start":
        await start_puzzle_from_query(query, context, parts[2])
        return
    if len(parts) == 4 and parts[1] == "2048":
        game_id = parts[2]
        direction = parts[3]
        game = puzzle_games(context).get(game_id)
        if not game or game.get("type") != "2048":
            await query.answer("2048 board expired.", show_alert=True)
            return
        if direction not in {"U", "D", "L", "R"}:
            await query.answer("Bad move.", show_alert=True)
            return
        board, changed, gained = move_2048(game["board"], direction)
        if not changed:
            await query.answer("No tiles moved.", show_alert=True)
            return
        game["board"] = board
        game["score"] = int(game.get("score", 0)) + int(gained)
        if any(value >= 2048 for row in board for value in row):
            puzzle_games(context).pop(game_id, None)
            db(context).upsert_user(user)
            db(context).record_game_result(user.id, True)
            await edit_query_message(query, f"{render_2048(board, game['score'])}\n\n2048 made by {user_label(user)}. Big brain innings.")
            return
        if not has_2048_moves(board):
            puzzle_games(context).pop(game_id, None)
            db(context).upsert_user(user)
            db(context).record_game_result(user.id, False)
            await edit_query_message(query, f"{render_2048(board, game['score'])}\n\nGame over. The board defended like prime death bowling.")
            return
        await edit_query_message(query, render_2048(board, game["score"]), markup_2048(game_id))
        return
    if len(parts) != 4 or parts[1] != "ans":
        await query.answer("Puzzle expired.", show_alert=True)
        return
    puzzle_id = parts[2]
    if not parts[3].isdigit():
        await query.answer("Puzzle expired.", show_alert=True)
        return
    picked = int(parts[3])
    puzzle_data = puzzle_games(context).pop(puzzle_id, None)
    if not puzzle_data:
        await query.answer("Puzzle already finished.", show_alert=True)
        return
    correct = picked == int(puzzle_data["answer"])
    db(context).upsert_user(user)
    db(context).record_game_result(user.id, correct)
    if correct:
        await query.answer("Solved.", show_alert=True)
        await edit_query_message(
            query,
            f"{user_label(user)} solved it.\n{puzzle_data['question']}\nAnswer: {puzzle_data['options'][picked]}\nClean brain, captain energy.",
        )
    else:
        answer = puzzle_data["options"][int(puzzle_data["answer"])]
        await query.answer("Wrong answer.", show_alert=True)
        await edit_query_message(
            query,
            f"{user_label(user)} missed it.\n{puzzle_data['question']}\nCorrect answer: {answer}\nThat decision review is gone forever.",
        )


QUESTION_STARTERS = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "is",
    "are",
    "was",
    "were",
    "did",
    "does",
    "do",
    "can",
    "will",
    "should",
    "tell",
    "show",
    "give",
    "stats",
    "score",
    "performance",
    "batting",
    "bowling",
    "kaisa",
    "kaise",
    "kesa",
    "kya",
    "kitna",
    "kitne",
)


def extract_target_id(text: str, update: Update) -> int | None:
    match = re.search(r"\b\d{5,}\b", text)
    if match:
        return int(match.group(0))
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        return int(update.message.reply_to_message.from_user.id)
    return None


def is_player_question(text: str) -> bool:
    clean = text.strip().lower()
    if not clean:
        return False
    if "?" in clean:
        return True
    return clean.startswith(QUESTION_STARTERS)


def extract_mentioned_username(text: str) -> str | None:
    username_match = re.search(r"@([A-Za-z][A-Za-z0-9_]{4,31})", text)
    return username_match.group(1) if username_match else None


def extract_question_target_id(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int | None:
    if not update.message:
        return None
    for entity in update.message.entities or []:
        if getattr(entity, "type", "") == "text_mention" and getattr(entity, "user", None):
            db(context).upsert_user(entity.user)
            return int(entity.user.id)
        if getattr(entity, "type", "") == "text_link":
            link_match = re.search(r"tg://user\?id=(\d+)", getattr(entity, "url", "") or "")
            if link_match:
                return int(link_match.group(1))

    id_match = re.search(r"\b\d{5,}\b", text)
    if id_match:
        return int(id_match.group(0))

    username = extract_mentioned_username(text)
    if username:
        found = db(context).player_by_username(username)
        if found:
            return int(found["tg_id"])

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        db(context).upsert_user(update.message.reply_to_message.from_user)
        return int(update.message.reply_to_message.from_user.id)

    return None


def live_player_snapshot(match: Match | None, target_id: int) -> dict[str, Any] | None:
    if not match:
        return None
    player = get_player(match, target_id)
    if not player:
        return {
            "match_active": True,
            "score": match.score,
            "innings": match.innings,
            "player": None,
        }
    stats = match.match_stats.get(str(target_id), {})
    team_key = get_team_key_for_player(match, target_id)
    return {
        "match_active": True,
        "phase": match.phase,
        "innings": match.innings,
        "batting_team": team_name(match, match.batting_team),
        "bowling_team": team_name(match, match.bowling_team),
        "score": {
            "runs": match.score.get("runs", 0),
            "wickets": match.score.get("wickets", 0),
            "legal_balls": match.score.get("legal_balls", 0),
            "overs": overs_text(match.score.get("legal_balls", 0)),
            "target": match.target,
            "last_delivery": match.score.get("last_delivery"),
            "timeline": match.score.get("timeline", [])[-8:],
        },
        "player": {
            "id": int(target_id),
            "name": player["name"],
            "team": team_name(match, team_key),
            "is_current_batter": int(match.current_batter_id or 0) == int(target_id),
            "is_current_bowler": int(match.current_bowler_id or 0) == int(target_id),
            "out": bool(player.get("out")),
            "batting": stats.get("batting", {}),
            "bowling": stats.get("bowling", {}),
            "fielding": stats.get("fielding", {}),
        },
    }


async def send_player_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: int) -> None:
    stats = db(context).player_stats(target_id)
    if not update.message:
        return
    if not stats:
        await update.message.reply_text(f"No saved stats found for Telegram id {target_id}.")
        return
    recent = db(context).recent_match_stats(target_id)
    cfg = settings(context)
    text = await summarize_player(cfg.gemini_api_key, cfg.gemini_model, stats, recent)
    await reply_long(update, text)


async def maybe_answer_player_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    match: Match | None,
    text: str,
) -> bool:
    if not update.message or not is_player_question(text):
        return False
    target_id = extract_question_target_id(update, context, text)
    if not target_id:
        return False

    stats = db(context).player_stats(target_id)
    live = live_player_snapshot(match, target_id)
    if not stats:
        if live and live.get("player"):
            player = live["player"]
            stats = {
                "tg_id": target_id,
                "display_name": player["name"],
                "matches": 0,
                "runs": 0,
                "balls": 0,
                "wickets": 0,
                "catches": 0,
                "drops": 0,
            }
        else:
            await update.message.reply_text(f"No saved match stats found for Telegram id {target_id}.")
            return True

    recent = db(context).recent_match_stats(target_id)
    cfg = settings(context)
    answer = await answer_player_question(cfg.gemini_api_key, cfg.gemini_model, text, stats, recent, live)
    await reply_long(update, answer)
    return True


async def text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    db(context).upsert_user(update.effective_user)

    match = active_match(context, update.effective_chat.id)
    if match:
        update_match_player_name(match, update.effective_user)

    if match:
        action = match.pending_action.get(str(update.effective_user.id))
        if action:
            if action["type"] == "team_name":
                reply = update.message.reply_to_message
                bot_id = getattr(context.bot, "id", None)
                if not reply or not reply.from_user or int(reply.from_user.id) != int(bot_id or 0):
                    await update.message.reply_text("Reply to the bot's team-name message so I know this is the official team name.")
                    return
                team_key = action["team"]
                match.teams[team_key]["name"] = text[:40]
                match.pending_action.pop(str(update.effective_user.id), None)
                await update.message.reply_text(f"{team_key} team name set to {text[:40]}.")
                if match.teams["A"].get("name") and match.teams["B"].get("name"):
                    match.toss_winner = random.choice([team for team in ("A", "B") if match.teams[team].get("captain_id")])
                    match.phase = "toss"
                    toss_cap = match.teams[match.toss_winner]["captain_id"]
                    await edit_main(
                        context,
                        match,
                        f"🪙 Random toss complete. {player_name(match, toss_cap)} ({team_name(match, match.toss_winner)}) wins it.\n"
                        "Coin has spoken. Choose Bat or Bowl.",
                        toss_markup(),
                    )
                db(context).save_match(match)
                return

            if action["type"] == "add":
                team_key = action["team"]
                player_id, display_name = resolve_player_from_message(update, context, text)
                if not player_id:
                    await edit_team_menu_by_id(
                        context,
                        match,
                        team_key,
                        action.get("menu_message_id"),
                        "Send a numeric Telegram id, or a @username that already exists in the bot database.",
                    )
                    return
                if get_player(match, player_id):
                    await edit_team_menu_by_id(
                        context,
                        match,
                        team_key,
                        action.get("menu_message_id"),
                        "That player is already in this match.",
                    )
                    return
                match.teams[team_key]["players"].append(new_player(player_id, display_name))
                db(context).upsert_manual_player(player_id, display_name)
                match.pending_action.pop(str(update.effective_user.id), None)
                ensure_match_player_stats(match)
                reset_ready(match)
                await edit_team_menu_by_id(
                    context,
                    match,
                    team_key,
                    action.get("menu_message_id"),
                    f"Added {display_name} to {team_name(match, team_key)}.",
                )
                await save_and_show_setup(context, match)
                return

    return


def resolve_player_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> tuple[int | None, str]:
    message = update.message
    if message and message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user
        db(context).upsert_user(user)
        return int(user.id), user_label(user)

    if message:
        for entity in message.entities or []:
            if getattr(entity, "type", "") == "text_mention" and getattr(entity, "user", None):
                user = entity.user
                db(context).upsert_user(user)
                return int(user.id), user_label(user)
            if getattr(entity, "type", "") == "text_link":
                link_match = re.search(r"tg://user\?id=(\d+)", getattr(entity, "url", "") or "")
                if link_match:
                    player_id = int(link_match.group(1))
                    return player_id, f"Player {player_id}"

    return resolve_player_input(context, text)


def resolve_player_input(context: ContextTypes.DEFAULT_TYPE, text: str) -> tuple[int | None, str]:
    id_match = re.search(r"\b\d{5,}\b", text)
    if id_match:
        player_id = int(id_match.group(0))
        display_name = text.replace(id_match.group(0), "").strip(" -:") or f"Player {player_id}"
        return player_id, display_name[:40]
    username_match = re.search(r"@?([A-Za-z][A-Za-z0-9_]{4,31})", text)
    if username_match:
        found = db(context).player_by_username(username_match.group(1))
        if found:
            return int(found["tg_id"]), found["display_name"]
    return None, text[:40]


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat or not update.effective_user:
        return
    data = query.data or ""
    if data == "noop":
        return
    if data.startswith("puzzle:"):
        await handle_puzzle(update, context, data)
        return

    match = active_match(context, update.effective_chat.id)
    if not match:
        await query.answer("No active match.", show_alert=True)
        return
    update_match_player_name(match, update.effective_user)

    if data == "join":
        await handle_join(update, context, match)
    elif data.startswith("toss:"):
        await handle_toss(update, context, match, data.split(":", 1)[1])
    elif data.startswith("team:"):
        await handle_team_menu(update, context, match, data)
    elif data.startswith("remove:"):
        await handle_remove(update, context, match, data)
    elif data.startswith("pick_batter:"):
        await handle_pick_batter(update, context, match, int(data.split(":")[1]))
    elif data.startswith("pick_bowler:"):
        await handle_pick_bowler(update, context, match, int(data.split(":")[1]))
    elif data.startswith("change_batter:"):
        await handle_change_batter(update, context, match, int(data.split(":")[1]))
    elif data.startswith("change_bowler:"):
        await handle_change_bowler(update, context, match, int(data.split(":")[1]))
    elif data.startswith("style:"):
        _, player_id, style = data.split(":")
        await handle_style(update, context, match, int(player_id), style)
    elif data.startswith("ready:"):
        await handle_ready(update, context, match, int(data.split(":")[1]))
    elif data == "admin_start":
        await handle_admin_start(update, context, match)
    elif data.startswith("bowl:"):
        await handle_bowl(update, context, match, int(data.split(":")[1]))
    elif data.startswith("bat:"):
        await handle_bat(update, context, match, int(data.split(":")[1]))
    elif data.startswith("length:"):
        await handle_length(update, context, match, data.split(":", 1)[1])
    elif data.startswith("catch:"):
        await handle_catch(update, context, match, int(data.split(":")[1]))
    elif data == "drs":
        await handle_drs(update, context, match)
    elif data == "locked:bouncer":
        await query.answer("Bouncer option is locked after 2 bouncers in this over.", show_alert=True)


async def handle_join(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if match.phase != "joining":
        await query.answer("Captain 2 already joined.", show_alert=True)
        return
    if int(user.id) == int(match.captains["A"]["id"]):
        await query.answer("Captain 1 cannot also be Captain 2.", show_alert=True)
        return
    db(context).upsert_user(user)
    name = user_label(user)
    match.captains["B"] = {"id": int(user.id), "name": name}
    match.teams["B"]["captain_id"] = int(user.id)
    match.teams["B"]["players"] = [new_player(user.id, name, True)]
    match.ready[str(user.id)] = False
    match.pending_action = {
        str(match.captains["A"]["id"]): {"type": "team_name", "team": "A"},
        str(match.captains["B"]["id"]): {"type": "team_name", "team": "B"},
    }
    match.phase = "team_names"
    await edit_main(
        context,
        match,
        "Captains joined.\n\n"
        f"Captain A: {match.captains['A']['name']}\n"
        f"Captain B: {match.captains['B']['name']}\n\n"
        "Both captains should send their team name in this chat.",
    )
    db(context).save_match(match)


async def handle_toss(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, choice: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or match.phase != "toss":
        return
    toss_cap = int(match.teams[match.toss_winner]["captain_id"])
    if int(user.id) != toss_cap:
        await answer_not_you(query, player_name(match, toss_cap))
        return
    winner = match.toss_winner
    loser = other_team(winner)
    if choice == "bat":
        match.batting_team, match.bowling_team = winner, loser
    else:
        match.batting_team, match.bowling_team = loser, winner
    match.innings_order = [match.batting_team, match.bowling_team]
    match.phase = "setup"
    reset_ready(match)
    ensure_match_player_stats(match)
    await save_and_show_setup(context, match)


async def handle_team_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, data: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _, action, team_key = data.split(":")
    if captain_team(match, user.id) != team_key:
        await answer_not_you(query, player_name(match, match.teams[team_key]["captain_id"]))
        return
    if action == "add":
        match.pending_action[str(user.id)] = {
            "type": "add",
            "team": team_key,
            "menu_message_id": getattr(query.message, "message_id", None),
        }
        db(context).save_match(match)
        await edit_query_message(
            query,
            "Reply to a player, tag a Telegram user, or send a numeric Telegram id.\n"
            "You can also use: /add <telegram_id> <name>",
            InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"team:back:{team_key}")]]),
        )
    elif action == "remove":
        await edit_query_message(query, f"Remove from {team_name(match, team_key)}:", remove_markup(match, team_key))
    elif action == "select":
        await show_select_menu(update, match, team_key)
    elif action == "change":
        await show_change_menu(update, match, team_key, user.id)
    elif action == "back":
        await edit_query_message(query, team_roster_text(match, team_key), team_menu_markup(match, team_key, user.id))


async def show_select_menu(update: Update, match: Match, team_key: str) -> None:
    query = update.callback_query
    if not query:
        return
    if team_key == match.batting_team:
        if match.current_batter_id and match.phase != "setup":
            await edit_query_message(query, f"Current batter is already {player_name(match, match.current_batter_id)}.")
            return
        await edit_query_message(query, "Select a batter:", select_batter_markup(match, team_key))
    elif team_key == match.bowling_team:
        if match.current_bowler_id and match.phase != "setup":
            await edit_query_message(query, f"Current bowler is already {player_name(match, match.current_bowler_id)}.")
            return
        await edit_query_message(query, "Select a bowler:", select_bowler_markup(match, team_key))
    else:
        await edit_query_message(query, "Toss is not complete yet.")


async def show_change_menu(update: Update, match: Match, team_key: str, cap_id: int) -> None:
    query = update.callback_query
    if not query:
        return
    if match.phase != "playing":
        await query.answer("Mid-match change is available only while play is live.", show_alert=True)
        return
    left = captain_changes_left(match, cap_id)
    if left <= 0:
        await query.answer("You already used your 2 mid-match changes.", show_alert=True)
        return
    if team_key == match.batting_team:
        await edit_query_message(query, f"Change batter ({left} left):", change_batter_markup(match, team_key))
    elif team_key == match.bowling_team:
        await edit_query_message(query, f"Change bowler ({left} left):", change_bowler_markup(match, team_key))
    else:
        await query.answer("Team role is not ready yet.", show_alert=True)


async def handle_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, data: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    _, team_key, player_id_text = data.split(":")
    if captain_team(match, user.id) != team_key:
        await answer_not_you(query, player_name(match, match.teams[team_key]["captain_id"]))
        return
    player_id = int(player_id_text)
    if player_id == int(match.teams[team_key]["captain_id"]):
        await query.answer("Captain cannot be removed.", show_alert=True)
        return
    match.teams[team_key]["players"] = [p for p in match.teams[team_key]["players"] if int(p["id"]) != player_id]
    if match.current_batter_id == player_id:
        match.current_batter_id = None
    if match.current_bowler_id == player_id:
        match.current_bowler_id = None
        match.current_bowler_style = None
    reset_ready(match)
    await save_and_show_setup(context, match)
    await edit_query_message(
        query,
        f"Removed player.\n\n{team_roster_text(match, team_key)}",
        team_menu_markup(match, team_key, int(user.id)),
    )


async def handle_pick_batter(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, player_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not match.batting_team:
        return
    if captain_team(match, user.id) != match.batting_team:
        await answer_not_you(query, player_name(match, match.teams[match.batting_team]["captain_id"]))
        return
    player = get_player(match, player_id)
    if not player or get_team_key_for_player(match, player_id) != match.batting_team or player.get("out"):
        await query.answer("This batter is not available.", show_alert=True)
        return
    match.current_batter_id = player_id
    ensure_match_player_stats(match)
    await edit_query_message(
        query,
        f"Current batter: {player['name']}\n\n{team_roster_text(match, match.batting_team)}",
        team_menu_markup(match, match.batting_team, int(user.id)),
    )
    await maybe_resume_after_selection(context, match)


async def handle_pick_bowler(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, player_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not match.bowling_team:
        return
    if captain_team(match, user.id) != match.bowling_team:
        await answer_not_you(query, player_name(match, match.teams[match.bowling_team]["captain_id"]))
        return
    player = get_player(match, player_id)
    if not player or get_team_key_for_player(match, player_id) != match.bowling_team:
        await query.answer("This bowler is not available.", show_alert=True)
        return
    if player.get("style"):
        match.current_bowler_id = player_id
        match.current_bowler_style = player["style"]
        ensure_match_player_stats(match)
        await edit_query_message(
            query,
            f"Current bowler: {player['name']} ({player['style']})\n\n{team_roster_text(match, match.bowling_team)}",
            team_menu_markup(match, match.bowling_team, int(user.id)),
        )
        await maybe_resume_after_selection(context, match)
    else:
        match.pending_action[str(user.id)] = {"type": "style", "team": match.bowling_team, "player_id": player_id}
        db(context).save_match(match)
        await edit_query_message(query, f"Choose bowling style for {player['name']}:", style_markup(player_id))


async def handle_change_batter(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, player_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not match.batting_team:
        return
    if match.phase != "playing":
        await query.answer("Wait until the live play screen is active.", show_alert=True)
        return
    if captain_team(match, user.id) != match.batting_team:
        await answer_not_you(query, player_name(match, match.teams[match.batting_team]["captain_id"]))
        return
    if captain_changes_left(match, user.id) <= 0:
        await query.answer("You already used your 2 mid-match changes.", show_alert=True)
        return
    player = get_player(match, player_id)
    if not player or get_team_key_for_player(match, player_id) != match.batting_team or player.get("out"):
        await query.answer("This batter is not available.", show_alert=True)
        return
    if int(player_id) == int(match.current_batter_id or 0):
        await query.answer("That batter is already on strike.", show_alert=True)
        return
    match.current_batter_id = player_id
    left = use_captain_change(match, user.id)
    ensure_match_player_stats(match)
    await edit_query_message(
        query,
        f"Batter changed to {player['name']}. Changes left: {left}\n\n{team_roster_text(match, match.batting_team)}",
        team_menu_markup(match, match.batting_team, int(user.id)),
    )
    await edit_main(context, match, scoreboard(match), bowling_markup(match))
    db(context).save_match(match)


async def handle_change_bowler(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, player_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not match.bowling_team:
        return
    if match.phase != "playing":
        await query.answer("Wait until the live play screen is active.", show_alert=True)
        return
    if captain_team(match, user.id) != match.bowling_team:
        await answer_not_you(query, player_name(match, match.teams[match.bowling_team]["captain_id"]))
        return
    if captain_changes_left(match, user.id) <= 0:
        await query.answer("You already used your 2 mid-match changes.", show_alert=True)
        return
    player = get_player(match, player_id)
    if not player or get_team_key_for_player(match, player_id) != match.bowling_team:
        await query.answer("This bowler is not available.", show_alert=True)
        return
    if int(player_id) == int(match.current_bowler_id or 0):
        await query.answer("That bowler is already bowling.", show_alert=True)
        return
    if player.get("style"):
        match.current_bowler_id = player_id
        match.current_bowler_style = player["style"]
        left = use_captain_change(match, user.id)
        ensure_match_player_stats(match)
        await edit_query_message(
            query,
            f"Bowler changed to {player['name']} ({player['style']}). Changes left: {left}\n\n{team_roster_text(match, match.bowling_team)}",
            team_menu_markup(match, match.bowling_team, int(user.id)),
        )
        await edit_main(context, match, scoreboard(match), bowling_markup(match))
        db(context).save_match(match)
        return
    match.pending_action[str(user.id)] = {
        "type": "style_change",
        "team": match.bowling_team,
        "player_id": player_id,
    }
    db(context).save_match(match)
    await edit_query_message(query, f"Choose bowling style for {player['name']}:", style_markup(player_id))


async def handle_style(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, player_id: int, style: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or style not in DELIVERIES_BY_STYLE:
        return
    if not match.bowling_team or captain_team(match, user.id) != match.bowling_team:
        await answer_not_you(query, player_name(match, match.teams[match.bowling_team]["captain_id"]))
        return
    player = get_player(match, player_id)
    if not player:
        return
    player["style"] = style
    match.current_bowler_id = player_id
    match.current_bowler_style = style
    action = match.pending_action.get(str(user.id), {})
    left_text = ""
    if action.get("type") == "style_change":
        left_text = f" Changes left: {use_captain_change(match, user.id)}"
    match.pending_action.pop(str(user.id), None)
    ensure_match_player_stats(match)
    await edit_query_message(
        query,
        f"Current bowler: {player['name']} ({style}).{left_text}\n\n{team_roster_text(match, match.bowling_team)}",
        team_menu_markup(match, match.bowling_team, int(user.id)),
    )
    await maybe_resume_after_selection(context, match)


async def is_chat_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        return False
    return member.status in {"administrator", "creator"}


async def handle_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if match.phase != "awaiting_admin_approval":
        await query.answer("Admin approval is not needed right now.", show_alert=True)
        return
    if not await is_chat_admin(context, match.chat_id, user.id):
        await query.answer("Only a group admin can approve the match start.", show_alert=True)
        return
    match.phase = "playing"
    await query.message.reply_text(f"Admin {user_label(user)} approved the start. Game on.")
    await edit_main(context, match, scoreboard(match), bowling_markup(match))
    db(context).save_match(match)


async def handle_ready(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, cap_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if int(user.id) != int(cap_id):
        await answer_not_you(query, player_name(match, cap_id))
        return
    if not can_start_match(match):
        await query.answer(
            "Start is locked: teams must be equal and starting batter/bowler must be selected.",
            show_alert=True,
        )
        return
    match.ready[str(cap_id)] = True
    if all(match.ready.get(str(cid)) for cid in captain_ids(match)):
        match.phase = "awaiting_admin_approval"
        await edit_main(context, match, scoreboard(match), admin_approval_markup())
        await query.message.reply_text(
            "Both captains pressed Start. Waiting for a group admin to approve the match start.",
            reply_markup=admin_approval_markup(),
        )
    else:
        await save_and_show_setup(context, match)
    db(context).save_match(match)


async def maybe_resume_after_selection(context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    if match.phase in {"awaiting_new_batter", "awaiting_new_bowler", "awaiting_new_batter_bowler"}:
        if match.current_batter_id and match.current_bowler_id:
            match.phase = "playing"
            await edit_main(context, match, scoreboard(match), bowling_markup(match))
        else:
            await edit_main(context, match, teams_text(match), ready_markup(match))
        db(context).save_match(match)
        return

    if match.phase == "setup":
        await save_and_show_setup(context, match)
        return

    if match.phase == "playing":
        await edit_main(context, match, scoreboard(match), bowling_markup(match))
        db(context).save_match(match)


async def handle_bowl(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, code: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if match.phase != "playing":
        await query.answer("Wait for the current game step.", show_alert=True)
        return
    if int(user.id) != int(match.current_bowler_id or 0):
        await answer_not_you(query, player_name(match, match.current_bowler_id))
        return
    style = match.current_bowler_style or "pacer"
    delivery = DELIVERIES_BY_STYLE[style][code]
    if delivery.bouncer and int(match.over_state.get("bouncers", 0)) >= 2:
        await query.answer("Bouncer option is locked after 2 bouncers.", show_alert=True)
        return
    append_button_log(match, user, "Bowler", "delivery", delivery_label(style, code))
    actual_length = choose_length(style, code)
    match.pending_delivery = {
        "style": style,
        "code": code,
        "actual_length": actual_length,
        "delivery_name": delivery.name,
    }
    match.phase = "awaiting_batter_run"
    db(context).save_match(match)
    await edit_main(
        context,
        match,
        f"{scoreboard(match)}\n\n🏏 {player_name(match, match.current_batter_id)}, select your run.",
        run_markup(),
    )


async def handle_bat(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, run: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if match.phase != "awaiting_batter_run" or not match.pending_delivery:
        await query.answer("No ball is waiting for a batter run.", show_alert=True)
        return
    if int(user.id) != int(match.current_batter_id or 0):
        await answer_not_you(query, player_name(match, match.current_batter_id))
        return
    append_button_log(match, user, "Batter", "run", str(run))
    match.pending_delivery["batter_run"] = int(run)
    match.phase = "awaiting_batter_length"
    db(context).save_match(match)
    await edit_main(
        context,
        match,
        f"{scoreboard(match)}\n\n{player_name(match, match.current_batter_id)}, select the length.",
        length_markup(match),
    )


async def handle_length(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, length: str) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if match.phase != "awaiting_batter_length" or not match.pending_delivery:
        await query.answer("No ball is waiting for a length.", show_alert=True)
        return
    if int(user.id) != int(match.current_batter_id or 0):
        await answer_not_you(query, player_name(match, match.current_batter_id))
        return
    if length == "Bouncer":
        if int(match.over_state.get("batter_bouncers", 0)) >= 1:
            await query.answer("Bouncer length is already used by the batter this over.", show_alert=True)
            return
        match.over_state["batter_bouncers"] = int(match.over_state.get("batter_bouncers", 0)) + 1
    append_button_log(match, user, "Batter", "length", length)
    style = match.pending_delivery["style"]
    code = int(match.pending_delivery["code"])
    run = int(match.pending_delivery["batter_run"])
    match.pending_delivery = make_pending_delivery(match, style, code, run, length)
    result = resolve_pending_delivery(match)
    if result["status"] == "catch_pending":
        pending = result["pending"]
        db(context).save_match(match)
        await edit_main(context, match, scoreboard(match))
        await announce_catch(context, match, pending)
        return
    await post_ball(context, match, result)


async def announce_catch(context: ContextTypes.DEFAULT_TYPE, match: Match, pending: dict[str, Any]) -> None:
    await context.bot.send_message(
        match.chat_id,
        "🧤 CATCH CHANCE!\n"
        f"Fielder: {pending['fielder_name']}\n"
        f"Air time: {pending['air_time']} seconds\n\n"
        "Guess the batter number: 0,1,2,3,4,6",
        reply_markup=catch_markup(),
    )
    if context.job_queue:
        context.job_queue.run_once(
            catch_timeout,
            when=int(pending["air_time"]),
            data={"chat_id": match.chat_id},
            name=f"catch-timeout-{match.chat_id}",
        )


async def handle_catch(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match, guess: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not match.pending_catch:
        return
    fielder_id = int(match.pending_catch["fielder_id"])
    if int(user.id) != fielder_id:
        await answer_not_you(query, player_name(match, fielder_id))
        return
    result = finish_catch(match, guess)
    await query.message.reply_text(catch_result_text(result))
    await post_ball(context, match, result)


async def catch_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = int(context.job.data["chat_id"])
    match = active_match(context, chat_id)
    if not match or not match.pending_catch:
        return
    result = finish_catch(match, None)
    await context.bot.send_message(chat_id, catch_result_text(result))
    await post_ball(context, match, result)


def event_commentary(match: Match, result: dict[str, Any]) -> str | None:
    batter = player_name(match, match.current_batter_id)
    bowler = player_name(match, match.current_bowler_id)
    status = result.get("status")
    last_over_pressure = balls_left(match) <= 6 or (
        match.innings == 2 and match.target and max(0, int(match.target) - int(match.score.get("runs", 0))) <= 12
    )

    if status == "extra":
        extra = result.get("extra")
        if extra == "wide":
            return random.choice(
                [
                    f"Wide called. {bowler} loses the line: +1 and that ball must be bowled again.",
                    f"That drifts outside reach. Wide ball, one added, rebowl coming.",
                    f"Loose from {bowler}. The umpire stretches the arms for a wide.",
                    "Wide. That one needed its own map back to the pitch. Reball, pressure still alive.",
                ]
            )
        if extra == "no_ball":
            return random.choice(
                [
                    f"No ball from {bowler}. {result.get('runs', 1)} added and the next ball is a FREE HIT.",
                    f"Front line trouble. No ball called, {result.get('runs', 1)} added. Free hit loading.",
                    f"Illegal delivery. No ball, free hit next. The bowler just handed out a gift voucher.",
                    "No ball. The crease has filed a complaint, and the batter gets a free swing next.",
                ]
            )
        if extra == "leg_bye":
            return random.choice(
                [
                    "Leg bye taken. It clips the body and they squeeze one.",
                    "No bat involved, but the batters are quick enough for a leg bye.",
                    "Leg bye added. Smart running keeps the scoreboard moving.",
                    "Leg bye. Not pretty, but the scoreboard does not judge.",
                ]
            )

    if status == "wicket":
        wicket_type = result.get("wicket_type", "Wicket")
        if last_over_pressure:
            return random.choice(
                [
                    f"{wicket_type}! Last-over nerves explode. This match just kicked the door open.",
                    f"{wicket_type}! Absolute pressure theft from {bowler}. The chase is sweating now.",
                    f"{wicket_type}! In the crunch, the batter blinked first. Brutal timing.",
                ]
            )
        return random.choice(
            [
                f"Big moment. {wicket_type}! {bowler} breaks through when it matters.",
                f"That's out. {wicket_type}, and the innings takes a sharp turn.",
                f"{wicket_type}! The bowling side erupts after a decisive delivery.",
                f"{wicket_type}! The batter's plan has left the group chat.",
                f"{wicket_type}! The batter read that like a terms-and-conditions page.",
                f"{wicket_type}! That shot had ambition, not permission.",
            ]
        )

    if status == "out":
        return random.choice(
            [
                f"Taken cleanly. {result.get('fielder_name', 'The fielder')} holds the catch under pressure.",
                f"Catch completed. Safe hands from {result.get('fielder_name', 'the fielder')}.",
                f"No mistake in the field. {result.get('fielder_name', 'The fielder')} makes it count.",
                f"Grabbed! {result.get('fielder_name', 'The fielder')} pockets it like rent was due.",
            ]
        )

    if status == "dropped":
        return random.choice(
            [
                f"Chance goes down. {result.get('runs', 0)} run(s) added after the drop.",
                f"That was in the air, but it does not stick. The batting side steals {result.get('runs', 0)}.",
                f"Drop catch. A real let-off, and the score moves by {result.get('runs', 0)}.",
                f"Dropped. Somewhere, the bowler just stared into the middle distance.",
            ]
        )

    if status == "runs" and result.get("free_hit"):
        return random.choice(
            [
                f"Free hit used for {result.get('runs', 0)}. No wicket fear, just vibes and violence.",
                f"Free hit done: {result.get('runs', 0)} run(s). The bowler survives, but the group chat will remember.",
            ]
        )

    if status == "runs" and last_over_pressure:
        return random.choice(
            [
                f"{result.get('runs', 0)} run(s). Every ball is now a tiny heart attack.",
                f"{batter} takes {result.get('runs', 0)}. Last-over pressure is chewing nails.",
                f"{result.get('runs', 0)} added. This finish is getting loud.",
            ]
        )

    if status == "runs" and int(result.get("runs", 0)) in {4, 6}:
        runs = int(result["runs"])
        if runs == 4:
            return random.choice(
                [
                    f"Cracked away for four. {batter} finds the gap beautifully.",
                    f"Four runs. Timed well and placed even better.",
                    f"That races away. Boundary for {batter}.",
                    f"{batter} sends it away for four. Fielders became spectators for a second.",
                ]
            )
        return random.choice(
            [
                f"Massive hit. {batter} sends it all the way for six.",
                "Six runs. Clean connection and maximum reward.",
                f"That is launched. {batter} clears the rope.",
                f"Six! {batter} has given that ball travel plans.",
            ]
        )

    return None


def catch_result_text(result: dict[str, Any]) -> str:
    if result["status"] == "out":
        return (
            "╔════════════════╗\n"
            "🚨 WICKET!! Catch OUT\n"
            "╚════════════════╝\n"
            f"🧤 Caught by ➤ {result['fielder_name']}"
        )
    if result.get("timeout"):
        return f"⌛ Catch timeout. DROP CATCH, +{result['runs']} run(s)."
    return f"DROP CATCH by {result['fielder_name']}, +{result['runs']} run(s)."


async def post_ball(context: ContextTypes.DEFAULT_TYPE, match: Match, result: dict[str, Any]) -> None:
    if result.get("explain"):
        match.score["last_explanation"] = result["explain"]
    commentary = event_commentary(match, result)
    review_team = result.get("drs_team")
    reviewable = bool(result.get("reviewable")) and result.get("wicket_type") in {"LBW", "Stumped"}
    review_markup = drs_markup(match, review_team) if reviewable else None
    if commentary:
        text = commentary
        if review_markup:
            cap_id = match.teams[review_team]["captain_id"]
            text += (
                f"\n\nDRS available for {team_name(match, review_team)}. "
                f"Captain {player_name(match, cap_id)} has 30 seconds."
            )
        await context.bot.send_message(match.chat_id, text, reply_markup=review_markup)

    if review_markup:
        match.pending_drs = {
            "team_key": review_team,
            "batter_id": result.get("batter_id"),
            "bowler_id": result.get("bowler_id"),
            "wicket_type": result.get("wicket_type"),
            "result": result,
        }
        match.phase = "drs_window"
        db(context).save_match(match)
        if context.job_queue:
            context.job_queue.run_once(
                drs_timeout,
                when=30,
                data={"chat_id": match.chat_id},
                name=f"drs-timeout-{match.chat_id}",
            )
        return

    await continue_after_ball(context, match, result)


async def continue_after_ball(context: ContextTypes.DEFAULT_TYPE, match: Match, result: dict[str, Any]) -> None:
    if match.phase == "drs_window":
        match.phase = "playing"

    if innings_over(match):
        await finish_innings_or_match(context, match)
        return

    needs_batter = result.get("status") in {"wicket", "out"} and match.current_batter_id is None
    needs_bowler = legal_over_complete(match)

    if needs_batter and needs_bowler:
        match.phase = "awaiting_new_batter_bowler"
        match.current_bowler_id = None
        match.current_bowler_style = None
        over_score = " | ".join(match.score.get("over_events", []))
        reset_over_state(match)
        batting_cap = match.teams[match.batting_team]["captain_id"]
        bowling_cap = match.teams[match.bowling_team]["captain_id"]
        await context.bot.send_message(
            match.chat_id,
            "╔════════════════╗\n"
            f"🚨 WICKET + OVER COMPLETE\n"
            "╚════════════════╝\n"
            f"⚡ {team_name(match, match.batting_team)} {match.score['runs']}/{match.score['wickets']}\n"
            f"Timeline: {over_score or 'None'}\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🏏 New batter captain: {player_name(match, batting_cap)}\n"
            f"🥎 New bowler captain: {player_name(match, bowling_cap)}\n"
            "Use /myteam → Select.",
        )
        await edit_main(context, match, scoreboard(match))
        db(context).save_match(match)
        return

    if needs_batter:
        match.phase = "awaiting_new_batter"
        batting_cap = match.teams[match.batting_team]["captain_id"]
        await context.bot.send_message(
            match.chat_id,
            "╔════════════════╗\n"
            f"🚨 WICKET!! {result.get('wicket_type', 'Catch Out')}\n"
            "╚════════════════╝\n"
            f"⚡ {team_name(match, match.batting_team)} {match.score['runs']}/{match.score['wickets']}\n"
            f"⏱ OVER • {overs_text(match.score['legal_balls'])}\n"
            f"🏏 Select New Batsman\n"
            f"Captain: {player_name(match, batting_cap)}\n"
            "Use /myteam → Select.",
        )
        await edit_main(context, match, scoreboard(match))
        db(context).save_match(match)
        return

    if needs_bowler:
        match.phase = "awaiting_new_bowler"
        match.current_bowler_id = None
        match.current_bowler_style = None
        over_score = " | ".join(match.score.get("over_events", []))
        reset_over_state(match)
        bowling_cap = match.teams[match.bowling_team]["captain_id"]
        await context.bot.send_message(
            match.chat_id,
            "╔════════════════╗\n"
            "⏱ OVER COMPLETE\n"
            "╚════════════════╝\n"
            f"⚡ {team_name(match, match.batting_team)} {match.score['runs']}/{match.score['wickets']}\n"
            f"Timeline: {over_score or 'None'}\n"
            "━━━━━━━━━━━━━━━━\n"
            "🥎 Select New Bowler\n"
            f"Captain: {player_name(match, bowling_cap)}\n"
            "Use /myteam → Select.",
        )
        await edit_main(context, match, scoreboard(match))
        db(context).save_match(match)
        return

    match.phase = "playing"
    await edit_main(context, match, scoreboard(match), bowling_markup(match))
    db(context).save_match(match)


async def handle_drs(update: Update, context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if not match.pending_drs:
        await query.answer("No active DRS review now.", show_alert=True)
        return
    team_key = str(match.pending_drs.get("team_key") or "")
    cap_id = int(match.teams.get(team_key, {}).get("captain_id") or 0)
    if int(user.id) != cap_id:
        await answer_not_you(query, player_name(match, cap_id))
        return
    if int(match.drs_reviews.get(team_key, 0)) <= 0:
        await query.answer("No DRS reviews left.", show_alert=True)
        return
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass
    decision = decide_drs(match)
    if decision["status"] == "upheld":
        await query.answer("DRS: wicket stays.", show_alert=True)
        await query.message.reply_text(
            f"DRS says OUT. Review lost. {team_name(match, team_key)} have {decision['reviews_left']} left."
        )
    elif decision["status"] == "overturned":
        await query.answer("DRS: batter survives.", show_alert=True)
        await query.message.reply_text(
            f"DRS overturns it. Batter is back. {team_name(match, team_key)} keep {decision['reviews_left']} review(s)."
        )
    else:
        await query.answer("DRS could not be resolved.", show_alert=True)
        return
    await continue_after_ball(context, match, decision["result"])


async def drs_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = int(context.job.data["chat_id"])
    match = active_match(context, chat_id)
    if not match or not match.pending_drs:
        return
    result = dict(match.pending_drs.get("result", {}))
    match.pending_drs = None
    await context.bot.send_message(chat_id, "DRS window closed. Wicket stands.")
    await continue_after_ball(context, match, result)


async def finish_innings_or_match(context: ContextTypes.DEFAULT_TYPE, match: Match) -> None:
    innings_record = {
        "innings": match.innings,
        "team": team_name(match, match.batting_team),
        "team_key": match.batting_team,
        "runs": int(match.score["runs"]),
        "wickets": int(match.score["wickets"]),
        "balls": int(match.score["legal_balls"]),
    }
    match.innings_history.append(innings_record)
    await context.bot.send_message(match.chat_id, innings_scorecard(match))

    if match.innings == 1:
        first_runs = int(match.score["runs"])
        old_batting = match.batting_team
        old_bowling = match.bowling_team
        match.innings = 2
        match.target = first_runs + 1
        match.batting_team = old_bowling
        match.bowling_team = old_batting
        reset_score(match)
        reset_drs_reviews(match)
        match.target = first_runs + 1
        for player in match.teams[match.batting_team]["players"]:
            player["out"] = False
        match.phase = "setup"
        reset_ready(match)
        await context.bot.send_message(
            match.chat_id,
            f"╔━━━━━━━╗\n➠ INNINGS -2\n╚━━━━━━━╝\n"
            f"{team_name(match, match.batting_team)} need {match.target} runs in {match.overs * 6} balls.\n"
            "Captains select batter and bowler, then both press Ready.",
        )
        await save_and_show_setup(context, match)
        return

    result_text = final_result(match)
    match.player_of_match = select_player_of_match(match, winning_team_key(match))
    pom_id = int(match.player_of_match["id"]) if match.player_of_match else None
    db(context).apply_match_stats(match, pom_id)
    match_id = db(context).complete_match(match, match_summary(match, result_text))
    final_text = f"Match #{match_id}\n{result_text}\n{player_of_match_text(match)}"
    await edit_main(context, match, f"{scoreboard(match)}\n\n{final_text}")
    await context.bot.send_message(
        match.chat_id,
        f"MATCH COMPLETE\n{final_text}\nUse /matchin {match_id} for full saved details.",
    )


def final_result(match: Match) -> str:
    if len(match.innings_history) < 2:
        return "Match finished."
    first = match.innings_history[0]
    second = match.innings_history[1]
    first_team = first["team"]
    second_team = second["team"]
    if second["runs"] >= int(match.target or 0):
        wickets_left = max(0, len(match.teams[match.batting_team]["players"]) - second["wickets"])
        return f"{second_team} won by {wickets_left} wicket(s)."
    margin = first["runs"] - second["runs"]
    if margin == 0:
        return "Match tied."
    return f"{first_team} won by {margin} run(s)."


def winning_team_key(match: Match) -> str | None:
    if len(match.innings_history) < 2:
        return None
    first = match.innings_history[0]
    second = match.innings_history[1]
    if second["runs"] >= int(match.target or 0):
        return match.batting_team
    if first["runs"] == second["runs"]:
        return None
    return match.bowling_team


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Unhandled Telegram error", exc_info=context.error)


def run() -> None:
    cfg = load_settings()
    database = Database(cfg.database_path)
    application = Application.builder().token(cfg.telegram_bot_token).build()
    application.bot_data["db"] = database
    application.bot_data["settings"] = cfg
    application.bot_data["puzzle_games"] = {}

    application.add_handler(CommandHandler("playmatch", playmatch))
    application.add_handler(CommandHandler("cancelmatch", cancelmatch))
    application.add_handler(CommandHandler("myteam", myteam))
    application.add_handler(CommandHandler("add", add_player))
    application.add_handler(CommandHandler("howplayed", howplayed))
    application.add_handler(CommandHandler("ask", ask_match))
    application.add_handler(CommandHandler("buzz", buzz))
    application.add_handler(CommandHandler("matchin", matchin))
    application.add_handler(CommandHandler("myprofile", myprofile))
    application.add_handler(CommandHandler("logs", logs))
    application.add_handler(CommandHandler("exp", exp))
    application.add_handler(CommandHandler("games", games))
    application.add_handler(CommandHandler("puzzle", puzzle))
    application.add_handler(CommandHandler("2048", game_2048))
    application.add_handler(CallbackQueryHandler(callbacks))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_messages))
    application.add_error_handler(error_handler)

    if cfg.run_mode == "webhook":
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        base_url = cfg.webhook_url or ""
        if not base_url:
            import os

            base_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
        if not base_url:
            raise RuntimeError("Set WEBHOOK_URL or run on Render with RENDER_EXTERNAL_URL for webhook mode.")
        path = cfg.webhook_path or "telegram-webhook"
        webhook_url = base_url.rstrip("/")
        if not webhook_url.endswith(f"/{path}"):
            webhook_url = f"{webhook_url}/{path}"
        LOGGER.info("Starting webhook on port %s at /%s", cfg.port, path)
        application.run_webhook(
            listen="0.0.0.0",
            port=cfg.port,
            url_path=path,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        return

    LOGGER.info("Starting polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

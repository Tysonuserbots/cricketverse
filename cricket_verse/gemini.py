from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any


def _post_gemini(api_key: str, model: str, prompt: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": 4096,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {body}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        return "Gemini did not return a summary."
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    return text or "Gemini returned an empty summary."


async def summarize_player(api_key: str | None, model: str, stats: dict[str, Any], recent: list[dict[str, Any]]) -> str:
    if not api_key:
        return local_summary(stats, recent)

    prompt = f"""
You are the Cricket Verse match analyst. Explain how this Telegram cricket player has played.
Use funny English cricket style with light playful roast energy, but keep the cricket analysis useful.
Give a complete answer covering batting, bowling, fielding, recent form, and one improvement tip.
Do not use Hinglish or any non-English language. Do not invent numbers. Do not stop midway.

Career stats JSON:
{json.dumps(stats, indent=2)}

Recent match snapshots JSON:
{json.dumps(recent, indent=2)}
"""
    try:
        return await asyncio.to_thread(_post_gemini, api_key, model, prompt)
    except Exception as exc:
        fallback = local_summary(stats, recent)
        return f"{fallback}\n\nGemini summary failed: {exc}"


async def answer_player_question(
    api_key: str | None,
    model: str,
    question: str,
    stats: dict[str, Any],
    recent: list[dict[str, Any]],
    live_match: dict[str, Any] | None = None,
) -> str:
    if not api_key:
        return local_question_answer(question, stats, recent, live_match)

    prompt = f"""
You are the Cricket Verse Telegram match analyst.
Answer the user's exact question about the tagged/replied player using ONLY the database/live-match data below.
If the data is missing, say that clearly. Give a complete, friendly, cricket-focused answer.
Use funny English cricket banter when it fits, with playful roast energy, but do not roast harshly.
Do not invent stats, names, wickets, scores, or match events.
Do not use Hinglish or any non-English language. Do not stop midway or end with an unfinished sentence.

User question:
{question}

Career stats JSON:
{json.dumps(stats, indent=2)}

Recent match snapshots JSON:
{json.dumps(recent, indent=2)}

Live match/player snapshot JSON:
{json.dumps(live_match or {}, indent=2)}
"""
    try:
        return await asyncio.to_thread(_post_gemini, api_key, model, prompt)
    except Exception as exc:
        fallback = local_question_answer(question, stats, recent, live_match)
        return f"{fallback}\n\nGemini answer failed: {exc}"


def local_summary(stats: dict[str, Any], recent: list[dict[str, Any]]) -> str:
    runs = int(stats.get("runs") or 0)
    balls = int(stats.get("balls") or 0)
    wickets = int(stats.get("wickets") or 0)
    matches = int(stats.get("matches") or 0)
    sr = (runs * 100 / balls) if balls else 0.0
    avg = runs / max(1, int(stats.get("outs") or 0))
    return (
        f"{stats.get('display_name', stats.get('tg_id'))} report card is here, fresh from the scorebook: "
        f"{matches} match(es), "
        f"{runs} runs at SR {sr:.2f}, average {avg:.2f}, {wickets} wicket(s), "
        f"{stats.get('catches', 0)} catch(es), {stats.get('drops', 0)} drop(s). "
        f"Recent records found: {len(recent)}. Improvement tip: pick the length smarter and avoid panic-button shots."
    )


def local_question_answer(
    question: str,
    stats: dict[str, Any],
    recent: list[dict[str, Any]],
    live_match: dict[str, Any] | None,
) -> str:
    name = stats.get("display_name", stats.get("tg_id"))
    runs = int(stats.get("runs") or 0)
    balls = int(stats.get("balls") or 0)
    wickets = int(stats.get("wickets") or 0)
    matches = int(stats.get("matches") or 0)
    sr = (runs * 100 / balls) if balls else 0.0
    answer = (
        f"{name}: scorebook says {matches} match(es), {runs} runs from {balls} balls "
        f"(SR {sr:.2f}), {wickets} wicket(s), {stats.get('catches', 0)} catch(es)."
    )
    if live_match and live_match.get("player"):
        player = live_match["player"]
        batting = player.get("batting", {})
        bowling = player.get("bowling", {})
        answer += (
            f"\nLive match: {player.get('team', 'team unknown')} - "
            f"{batting.get('runs', 0)}({batting.get('balls', 0)}) with bat, "
            f"{bowling.get('wickets', 0)}W/{bowling.get('runs', 0)} with ball."
        )
    answer += f"\nRecent records found: {len(recent)}. Tiny analyst note: play the length, not the vibes."
    return answer

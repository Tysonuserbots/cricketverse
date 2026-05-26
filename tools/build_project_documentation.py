from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Cricket Verse Project Documentation.docx"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(text)
    run.bold = bold
    run.font.name = "Calibri"
    run.font.size = Pt(10)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_h(doc: Document, text: str, level: int = 1):
    return doc.add_heading(text, level=level)


def add_p(doc: Document, text: str = "", style: str | None = None):
    return doc.add_paragraph(text, style=style)


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        add_p(doc, item, "List Bullet")


def add_numbers(doc: Document, items: list[str]) -> None:
    for item in items:
        add_p(doc, item, "List Number")


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    hdr = table.rows[0].cells
    for idx, header in enumerate(headers):
        set_cell_text(hdr[idx], header, True)
        set_cell_shading(hdr[idx], "E8EEF5")
        hdr[idx].width = Inches(widths[idx])
    for row in rows:
        cells = table.add_row().cells
        for idx, value in enumerate(row):
            set_cell_text(cells[idx], value)
            cells[idx].width = Inches(widths[idx])
    doc.add_paragraph()


def add_code_block(doc: Document, lines: list[str]) -> None:
    para = doc.add_paragraph()
    for line in lines:
        run = para.add_run(line + "\n")
        run.font.name = "Consolas"
        run.font.size = Pt(9)


def style_doc(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.2

    for name, size, color in [
        ("Title", 22, "0B2545"),
        ("Heading 1", 16, "2E74B5"),
        ("Heading 2", 13, "2E74B5"),
        ("Heading 3", 12, "1F4D78"),
    ]:
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(6)


def build() -> None:
    doc = Document()
    style_doc(doc)

    title = doc.add_paragraph()
    title.style = "Title"
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("Cricket Verse Telegram Bot - Project Documentation").bold = True

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run("Updated local project guide for match flow, rules, AI replies, files, and Render deployment.")

    add_h(doc, "1. Current Project Snapshot")
    add_bullets(
        doc,
        [
            "Project folder: C:\\Users\\tyson\\OneDrive\\Documents\\Cricket Bot 2",
            "Main entry point: main.py",
            "Telegram framework: python-telegram-bot with job queue and webhooks extras",
            "Database: SQLite by default, DATABASE_PATH controls location",
            "AI model: gemini-flash-latest through GEMINI_MODEL",
            "Render free deploy: webhook mode with RUN_MODE=webhook",
        ],
    )

    add_h(doc, "2. Updated Files")
    add_table(
        doc,
        ["File", "Purpose", "Latest Important Changes"],
        [
            ["main.py", "Starts the bot", "Calls cricket_verse.bot.run()."],
            ["cricket_verse/bot.py", "Telegram commands, callback buttons, lobby, gameplay flow", "Start lock, admin start approval, /add, funny commentary, team-name reply validation, run + length batting flow, webhook support."],
            ["cricket_verse/engine.py", "Cricket scoring and wicket engine", "Secret actual length, hard-ball miss-run logic, extras, wickets, catches, scoring state."],
            ["cricket_verse/game_data.py", "Pacer/spinner delivery tables", "Contains delivery length, MLR, hard-ball, catch-ball, extras and spam percentages."],
            ["cricket_verse/formatting.py", "MPMM and scorecard text", "/myteam roster view, timeline last 8, RRR only in innings 2."],
            ["cricket_verse/database.py", "SQLite persistence", "Players, active matches, completed matches, career stats, username lookup."],
            ["cricket_verse/gemini.py", "Gemini stat answers", "Longer output, English funny style, fallback summaries, long Telegram reply splitting."],
            ["cricket_verse/config.py", "Environment settings", "RUN_MODE, PORT, webhook path/url, Gemini model, database path."],
            ["render.yaml", "Render deployment blueprint", "Free web service, Python 3.12.8, webhook env setup."],
            [".env.example", "Local env template", "Uses gemini-flash-latest and webhook/polling switches."],
            ["README.md", "Human quick guide", "Updated commands, Render setup, ball flow, latest behavior notes."],
        ],
        [1.7, 2.0, 2.8],
    )

    add_h(doc, "3. Commands And Lobby Flow")
    add_numbers(
        doc,
        [
            "Captain sends /playmatch <overs> in the group.",
            "Captain 2 joins through the Join button.",
            "Both captains must reply with team names. Only the requested captain's reply is accepted.",
            "Bot randomly selects one captain as toss winner.",
            "Toss winner chooses Bat or Bowl.",
            "Captains use /myteam to manage their own team only.",
            "Start remains locked until both teams have equal players and the opening batter and bowler are selected.",
            "Admin approval is required before the match can start after both captains press Start.",
        ],
    )

    add_h(doc, "4. /myteam And /add Behavior")
    add_bullets(
        doc,
        [
            "/myteam is captain-only and shows only that captain's roster.",
            "Add button remains available in /myteam.",
            "New /add support lets a captain add a tagged/replied/numeric-id player directly.",
            "Remove button remains serial-number based.",
            "Players show Telegram first name in team lists when available.",
            "Player list updates after add/remove/select operations.",
        ],
    )

    add_h(doc, "5. Live Arena MPMM UI")
    add_bullets(
        doc,
        [
            "MPMM updates every ball with score, wickets, overs, current batter, current bowler, and last delivery.",
            "CRR always appears.",
            "RRR appears only in the second innings.",
            "Timeline shows the last 8 events such as 1 | 4 | wd | W(c).",
            "Wrong-user button clicks show: You are not [Player Name]!",
            "Over complete pauses the arena and asks the bowling captain to select a new bowler.",
            "Wicket pauses the arena and asks the batting captain to select a new batter.",
        ],
    )

    add_h(doc, "6. Ball Physics And Hard-Ball Logic")
    add_numbers(
        doc,
        [
            "Bowler chooses a delivery type.",
            "Bot secretly picks the actual length from that delivery's allowed lengths.",
            "Batter selects a run.",
            "Batter selects a length guess.",
            "If the batter length matches the actual length, normal selected runs are awarded.",
            "If the length misses, the MLR/miss-run table gives miss-length runs.",
            "For the first 3 hard balls in an over, hard-ball protection applies: length miss gives miss-length runs.",
            "Bouncers count into the hard-ball cap. After 2 bouncers, only 1 more hard-ball slot remains.",
            "From the 4th hard ball onward, batter gets selected runs even if length logic would otherwise restrict it.",
        ],
    )

    add_h(doc, "7. Bowling Data Summary")
    add_table(
        doc,
        ["Style", "Hard Balls", "Catch Balls", "Bouncer Limit"],
        [
            ["Pacer", "Reverse Swing (0), Bouncer (1), Yorker (2)", "Bouncer, Short, Slower, Knuckle", "Max 2 bouncers per over"],
            ["Spinner", "Carrom (0), Doosra (1), Top Spin (3)", "Doosra, Leg Break, Top Spin, Googly", "No bouncer delivery"],
        ],
        [1.1, 2.5, 2.1, 1.0],
    )

    add_h(doc, "8. Wickets, Catches, Extras, And Commentary")
    add_bullets(
        doc,
        [
            "BFR = BR can trigger Bowled/LBW/Stumped, Catch Out type 1, Run Out, or survival depending on length result.",
            "BFR != BR can trigger Catch Out type 2 only on catch-ball deliveries and only on length mismatch.",
            "Catch system selects a random fielder and time window of 120, 150, or 180 seconds.",
            "Fielder guesses 0, 1, 2, 3, 4, or 6. Correct guess is out; wrong/timeout is drop catch.",
            "Drop-catch bonus runs depend on air time: 120s = 1, 150s = 2, 180s = 3.",
            "Extras include natural wide/no-ball/leg-bye and spam protocol for repeated deliveries.",
            "Commentary is English-only, funny, and sharper on wickets/catches/drops/random events.",
        ],
    )

    add_h(doc, "9. Innings And Finish")
    add_bullets(
        doc,
        [
            "First innings ends when overs finish or all players are out.",
            "Full batting and bowling scorecard is sent after innings completion.",
            "Second innings swaps batting and bowling roles.",
            "Target is first innings score + 1.",
            "Chasing team wins immediately after reaching target.",
            "If chase fails, defending team wins by runs.",
            "Completed match stats are saved to the database.",
        ],
    )

    add_h(doc, "10. AI Replies")
    add_bullets(
        doc,
        [
            "AI answers player-stat questions when the user replies to a player, tags a username, uses a Telegram user link, or includes a Telegram id.",
            "AI uses SQLite career stats, recent completed match snapshots, and live match state if the player is active.",
            "Gemini output uses gemini-flash-latest.",
            "AI replies are English-only and use funny cricket banter with light playful roast energy.",
            "Long AI answers are split into Telegram-safe chunks so the answer does not get cut off.",
            "Fallback local summaries work even without GEMINI_API_KEY.",
        ],
    )

    add_h(doc, "11. Render Free Deployment")
    add_p(doc, "Use Render Web Service on the Free plan. The bot runs in webhook mode.")
    add_table(
        doc,
        ["Setting", "Value"],
        [
            ["Build Command", "pip install -r requirements.txt"],
            ["Start Command", "python main.py"],
            ["RUN_MODE", "webhook"],
            ["WEBHOOK_PATH", "telegram-webhook"],
            ["PYTHON_VERSION", "3.12.8"],
            ["GEMINI_MODEL", "gemini-flash-latest"],
            ["DATABASE_PATH", "/tmp/cricket_verse.sqlite3"],
        ],
        [2.0, 4.5],
    )
    add_p(doc, "Add TELEGRAM_BOT_TOKEN and GEMINI_API_KEY manually in Render Environment. Do not commit .env.")
    add_p(doc, "Free Render storage is temporary. SQLite stats may reset after redeploy/restart unless you later use a persistent disk or external database.")

    add_h(doc, "12. GitHub Upload Checklist")
    add_bullets(
        doc,
        [
            "Upload/commit updated code files after each local change.",
            "Do not upload .env, SQLite databases, or __pycache__.",
            "If using GitHub website, drag updated files/folders and commit changes.",
            "If using GitHub Desktop, copy updated files into the cloned repo, commit, then push.",
            "After GitHub update, use Render Manual Deploy -> Deploy latest commit.",
        ],
    )

    add_h(doc, "13. Important Environment Variables")
    add_code_block(
        doc,
        [
            "TELEGRAM_BOT_TOKEN=your_real_bot_token",
            "GEMINI_API_KEY=your_real_gemini_key",
            "GEMINI_MODEL=gemini-flash-latest",
            "RUN_MODE=webhook",
            "WEBHOOK_PATH=telegram-webhook",
            "DATABASE_PATH=/tmp/cricket_verse.sqlite3",
            "PYTHON_VERSION=3.12.8",
        ],
    )

    add_h(doc, "14. Current Function Map")
    add_table(
        doc,
        ["Module", "Key Functions"],
        [
            ["bot.py", "playmatch, myteam, callbacks, handle_bowl, handle_bat, handle_length, handle_ready, handle_catch, event_commentary, run"],
            ["engine.py", "choose_length, make_pending_delivery, resolve_pending_delivery, score_runs_for_ball, wicket_check, finish_catch"],
            ["formatting.py", "scoreboard, team_roster_text, teams_text, innings_scorecard, match_summary"],
            ["database.py", "save_match, load_match, complete_match, apply_match_stats, player_stats, player_by_username"],
            ["gemini.py", "summarize_player, answer_player_question, local_summary, local_question_answer"],
            ["models.py", "Match, make_match, reset_score, new_player, new_player_stats, user_label"],
            ["game_data.py", "Delivery, PACER_DELIVERIES, SPIN_DELIVERIES, delivery_label"],
        ],
        [1.5, 5.0],
    )

    doc.add_section(WD_SECTION.NEW_PAGE)
    add_h(doc, "15. Final Notes")
    add_bullets(
        doc,
        [
            "The current local files compile successfully with bundled Python.",
            "Render should be redeployed after GitHub receives these updated files.",
            "The local machine does not currently expose a working git command in PowerShell, so GitHub Desktop or website upload is the easiest route.",
        ],
    )

    doc.save(OUT)


if __name__ == "__main__":
    build()
    print(OUT)

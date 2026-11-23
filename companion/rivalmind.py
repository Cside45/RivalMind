"""RivalMind local companion, alpha.

No HTTP client, sockets, analytics SDK, telemetry, auto-update, or Lua evaluation.
Reads only an explicitly chosen RivalMind SavedVariables file.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

# Allow the companion to load its reviewed, bundled local parser when imported
# by the existing tests via importlib.util.spec_from_file_location.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from telemetry import parse_telemetry_export, store_telemetry, summarize_telemetry
import re
import sqlite3
import sys
import time
from urllib.parse import unquote

VERSION = "0.4.0-alpha"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 100
MAX_QUEST_ROWS = 200
EXPORT_FIELD = re.compile(r'(?:\[\s*["\']export["\']\s*\]|\bexport)\s*=\s*"([^"\r\n]*)"')
QUEST_EXPORT_FIELD = re.compile(r'(?:\[\s*["\']questExport["\']\s*\]|\bquestExport)\s*=\s*"([^"\r\n]*)"')
INT_FIELD = re.compile(r"\d{1,12}\Z")
ZONE_FIELD = re.compile(r"(?:[A-Za-z0-9_.-]|%[0-9A-Fa-f]{2}){0,300}\Z")


class ImportErrorRM(ValueError):
    pass


def default_database() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return root / "RivalMind" / "rivalmind.sqlite3"


def parse_export(file_contents: str) -> list[dict]:
    """Decode ONLY RivalMind's limited data string, not the surrounding Lua."""
    matches = EXPORT_FIELD.findall(file_contents)
    if len(matches) != 1:
        raise ImportErrorRM("Could not find a unique RivalMind export. Use /reload in WoW, then try again.")
    encoded = matches[0]
    parts = encoded.split(";")
    if not parts or parts[0] != "RM1":
        raise ImportErrorRM("Unsupported RivalMind export format")
    if len(parts) - 1 > MAX_ROWS:
        raise ImportErrorRM("Too many sessions in the export")
    result: list[dict] = []
    seen_ids = set()
    for row in parts[1:]:
        fields = row.split(",")
        if len(fields) != 8:
            raise ImportErrorRM("Malformed export row")
        if not all(INT_FIELD.fullmatch(item) for item in fields[:7]):
            raise ImportErrorRM("Invalid numeric value in export")
        if not ZONE_FIELD.fullmatch(fields[7]):
            raise ImportErrorRM("Invalid zone encoding")
        ident, start, duration, xp, deaths, start_level, end_level = map(int, fields[:7])
        if ident in seen_ids:
            raise ImportErrorRM("Duplicate session identifier")
        seen_ids.add(ident)
        if not 0 < start < 5000000000 or duration > 365 * 24 * 3600 or deaths > 100000:
            raise ImportErrorRM("Unreasonable session values")
        if start_level > 1000 or end_level > 1000:
            raise ImportErrorRM("Unreasonable level value")
        result.append({
            "id": ident,
            "started": start,
            "duration_seconds": duration,
            "xp_earned": xp,
            "deaths": deaths,
            "start_level": start_level,
            "end_level": end_level,
            "last_zone": unquote(fields[7], encoding="utf-8", errors="replace"),
        })
    return result


def parse_quest_export(file_contents: str) -> list[dict]:
    """Return empty for v0.1 exports; parse strict v0.2 quest rows when present."""
    matches = QUEST_EXPORT_FIELD.findall(file_contents)
    if not matches:
        return []
    if len(matches) != 1:
        raise ImportErrorRM("Ambiguous quest export")
    parts = matches[0].split(";")
    if parts[0] != "RQ1" or len(parts) - 1 > MAX_QUEST_ROWS:
        raise ImportErrorRM("Unsupported quest export or too many quest events")
    result = []
    seen = set()
    for row in parts[1:]:
        fields = row.split(",")
        if len(fields) != 7:
            raise ImportErrorRM("Malformed quest event")
        if not all(INT_FIELD.fullmatch(x) for x in fields[:3]):
            raise ImportErrorRM("Invalid quest event identifier or timestamp")
        ident, qid, stamp = map(int, fields[:3])
        if ident < 1 or not 0 < qid < 100000000 or not 0 < stamp < 5000000000:
            raise ImportErrorRM("Invalid quest event values")
        if ident in seen or fields[3] not in ("A", "C", "T", "R"):
            raise ImportErrorRM("Duplicate quest event ID or unknown event kind")
        seen.add(ident)
        reward = fields[4]
        if reward and not INT_FIELD.fullmatch(reward):
            raise ImportErrorRM("Invalid quest reward")
        if reward and int(reward) > 100000000:
            raise ImportErrorRM("Unreasonable quest reward")
        if not ZONE_FIELD.fullmatch(fields[5]) or len(fields[6]) > 600:
            raise ImportErrorRM("Invalid quest text")
        if not re.fullmatch(r"(?:[A-Za-z0-9_.-]|%[0-9A-Fa-f]{2}){0,600}", fields[6]):
            raise ImportErrorRM("Invalid quest title encoding")
        result.append({
            "event_id": ident,
            "quest_id": qid,
            "stamp": stamp,
            "kind": fields[3],
            "reported_xp": int(reward) if reward else None,
            "zone": unquote(fields[5], encoding="utf-8", errors="replace"),
            "title": unquote(fields[6], encoding="utf-8", errors="replace"),
        })
    return result


def read_quest_events(file_path: Path) -> list[dict]:
    file_path = Path(file_path).expanduser().resolve(strict=True)
    if not file_path.is_file() or file_path.name.casefold() != "rivalmind.lua":
        raise ImportErrorRM("Select the WoW RivalMind.lua SavedVariables file")
    if file_path.stat().st_size > MAX_INPUT_BYTES:
        raise ImportErrorRM("File exceeds safe import limit")
    return parse_quest_export(file_path.read_text(encoding="utf-8-sig"))


def read_recent_quests(database_path: Path | None = None) -> list[tuple]:
    db_path = Path(database_path or default_database())
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        try:
            return connection.execute("""
                SELECT stamp, kind, quest_id, title, reported_xp, zone
                FROM quest_events ORDER BY stamp DESC, event_id DESC LIMIT 6
            """).fetchall()
        except sqlite3.OperationalError:
            return []


def count_quests(database_path: Path | None = None) -> int:
    db_path = Path(database_path or default_database())
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as connection:
        try:
            return connection.execute("SELECT COUNT(*) FROM quest_events").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


def read_sessions(file_path: Path) -> list[dict]:
    file_path = Path(file_path).expanduser().resolve(strict=True)
    if not file_path.is_file() or file_path.name.casefold() != "rivalmind.lua":
        raise ImportErrorRM("Select the RivalMind.lua file in the WoW WTF/SavedVariables directory")
    if file_path.stat().st_size > MAX_INPUT_BYTES:
        raise ImportErrorRM("File exceeds the safe import limit")
    content = file_path.read_text(encoding="utf-8-sig")
    return parse_export(content)


def import_sessions(file_path: Path, database_path: Path | None = None) -> tuple[int, int]:
    file_path = Path(file_path).expanduser().resolve(strict=True)
    sessions = read_sessions(file_path)
    quest_events = read_quest_events(file_path)
    telemetry_events = parse_telemetry_export(file_path.read_text(encoding="utf-8-sig"))
    db_path = Path(database_path or default_database()).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Hash the on-disk source path rather than storing an account/character path.
    source_key = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:24]
    timestamp = int(time.time())
    with sqlite3.connect(db_path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
            source_key TEXT NOT NULL,
            session_id INTEGER NOT NULL,
            started INTEGER NOT NULL,
            duration_seconds INTEGER NOT NULL,
            xp_earned INTEGER NOT NULL,
            deaths INTEGER NOT NULL,
            start_level INTEGER NOT NULL,
            end_level INTEGER NOT NULL,
            last_zone TEXT NOT NULL,
            imported_at INTEGER NOT NULL,
            PRIMARY KEY (source_key, session_id)
        )""")
        for session in sessions:
            connection.execute("""INSERT INTO sessions (
                source_key, session_id, started, duration_seconds,
                xp_earned, deaths, start_level, end_level, last_zone, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key, session_id) DO UPDATE SET
                duration_seconds = excluded.duration_seconds,
                xp_earned = excluded.xp_earned,
                deaths = excluded.deaths,
                end_level = excluded.end_level,
                last_zone = excluded.last_zone,
                imported_at = excluded.imported_at""", (
                source_key, session["id"], session["started"], session["duration_seconds"],
                session["xp_earned"], session["deaths"], session["start_level"],
                session["end_level"], session["last_zone"], timestamp
            ))
        connection.execute("""CREATE TABLE IF NOT EXISTS quest_events (
            source_key TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            quest_id INTEGER NOT NULL,
            stamp INTEGER NOT NULL,
            kind TEXT NOT NULL,
            reported_xp INTEGER,
            zone TEXT NOT NULL,
            title TEXT NOT NULL,
            imported_at INTEGER NOT NULL,
            PRIMARY KEY (source_key, event_id)
        )""")
        for quest in quest_events:
            connection.execute("""INSERT INTO quest_events (
                source_key, event_id, quest_id, stamp, kind, reported_xp, zone, title, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key, event_id) DO UPDATE SET
                quest_id = excluded.quest_id,
                stamp = excluded.stamp,
                kind = excluded.kind,
                reported_xp = excluded.reported_xp,
                zone = excluded.zone,
                title = excluded.title,
                imported_at = excluded.imported_at""", (
                source_key, quest["event_id"], quest["quest_id"], quest["stamp"],
                quest["kind"], quest["reported_xp"], quest["zone"], quest["title"], timestamp
            ))
        store_telemetry(connection, source_key, timestamp, telemetry_events)
        total = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return len(sessions), total


def read_recent(database_path: Path | None = None) -> list[tuple]:
    db_path = Path(database_path or default_database())
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        return connection.execute("""
            SELECT started, duration_seconds, xp_earned, deaths, last_zone
            FROM sessions ORDER BY started DESC LIMIT 8
        """).fetchall()



def analyze_quest_turnins(rows: list[tuple]) -> list[dict]:
    """Pair observed quest acceptances with turn-ins, within each local source.

    Input tuples: (source_key, event_id, quest_id, stamp, kind, reported_xp, title, zone).
    Elapsed time is wall-clock time between the two observed events, NOT active
    questing time. A quest without a recorded acceptance has unknown duration.
    QUEST_REMOVED must not clear an acceptance: turn-ins often also remove quests.
    """
    open_quests: dict[tuple[str, int], int] = {}
    completed = []
    for source, event_id, quest_id, stamp, kind, xp, title, zone in sorted(
        rows, key=lambda x: (x[0], x[3], x[1])
    ):
        key = (source, quest_id)
        if kind == "A":
            open_quests[key] = stamp
        elif kind == "T":
            started = open_quests.pop(key, None)
            elapsed = stamp - started if started is not None and stamp >= started else None
            # Zero-duration event pairs are valid but cannot yield an hourly rate.
            rate = (
                xp * 3600 // elapsed
                if elapsed is not None and elapsed > 0 and xp is not None
                else None
            )
            completed.append({
                "source_key": source, "quest_id": quest_id, "turnin_at": stamp,
                "title": title, "zone": zone, "reported_xp": xp,
                "accepted_at": started, "elapsed_seconds": elapsed,
                "elapsed_xp_per_hour": rate,
            })
        # A removal is not proof of abandonment; never infer one.
    return sorted(completed, key=lambda q: q["turnin_at"], reverse=True)


def read_quest_efficiency(database_path: Path | None = None) -> list[dict]:
    """Read a bounded sample of locally stored quest events; no network access."""
    db_path = Path(database_path or default_database())
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as connection:
        try:
            rows = connection.execute("""
                SELECT source_key, event_id, quest_id, stamp, kind,
                       reported_xp, title, zone
                FROM quest_events ORDER BY rowid DESC LIMIT 10000
            """).fetchall()
        except sqlite3.OperationalError:
            return []
    return analyze_quest_turnins(rows)

def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from datetime import datetime

    app = tk.Tk()
    app.title("RivalMind | Local Companion v0.4")
    app.geometry("590x400")
    app.minsize(530, 340)
    app.configure(padx=18, pady=16)

    ttk.Label(app, text="RivalMind", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(app, text="Local analytics preview  •  No AI requests  •  No network connections").pack(anchor="w", pady=(2, 14))
    ttk.Label(app, text="WoW SavedVariables file").pack(anchor="w")

    row = ttk.Frame(app)
    row.pack(fill="x", pady=(5, 9))
    chosen = tk.StringVar(value="Select a RivalMind.lua file after /reload or logout")
    ttk.Entry(row, textvariable=chosen, state="readonly").pack(side="left", fill="x", expand=True, padx=(0, 8))

    def choose() -> None:
        file = filedialog.askopenfilename(
            title="Find RivalMind.lua under _forever_/WTF/Account/.../SavedVariables/",
            filetypes=[("RivalMind SavedVariables", "RivalMind.lua"), ("Lua files", "*.lua")],
        )
        if file:
            chosen.set(file)
            import_button.state(["!disabled"])

    ttk.Button(row, text="Browse…", command=choose).pack(side="right")
    # Keep the primary action above the expanding history pane. It must remain
    # visible on smaller Windows displays and at higher DPI scaling.
    import_button = ttk.Button(app, text="Import saved sessions", state="disabled")
    import_button.pack(anchor="e", pady=(0, 8))
    status = tk.StringVar(value="Nothing is uploaded. Imports only touch files on your PC.")
    ttk.Label(app, textvariable=status, wraplength=540).pack(anchor="w", pady=(0, 10))
    ttk.Label(app, text="Recent sessions", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    history = tk.Text(app, height=10, wrap="none", state="disabled", relief="flat")
    history.pack(fill="both", expand=True, pady=(4, 4))

    def refresh() -> None:
        rows = read_recent()
        lines = []
        telemetry = summarize_telemetry(default_database())
        if telemetry.get("events"):
            character = telemetry.get("character")
            if character:
                lines.append(f"Character: {character[0]}  Level {character[1]}")
            balance = telemetry.get("last_observed_gold_copper")
            if balance is not None:
                lines.append(f"Last observed gold: {balance / 10000:.2f}g")
            lines.append(
                f"Gold net movement (NOT profit): {telemetry['gold_net_copper'] / 10000:+.2f}g"
            )
            lines.append(
                f"Observed: {telemetry['distinct_zones']} zones, "
                f"{telemetry['equipment_observations']} equipment changes/snapshots, "
                f"{telemetry['bag_quantity_changes']} bag-item changes"
            )
            lines.append("")
        for started, duration, xp, deaths, zone in rows:
            when = datetime.fromtimestamp(started).strftime("%b %d %H:%M")
            lines.append(f"{when:<15}  {duration // 60:>3} min   {xp:>7} XP   {deaths} deaths   {zone[:28]}")
        quests = read_quest_efficiency()
        if quests:
            lines.append("")
            lines.append("Quest turn-ins  |  elapsed since observed acceptance (includes downtime)")
            for quest in quests[:6]:
                when = datetime.fromtimestamp(quest["turnin_at"]).strftime("%b %d %H:%M")
                name = (quest["title"] or f'Quest #{quest["quest_id"]}')[:27]
                elapsed = quest["elapsed_seconds"]
                elapsed_text = (
                    f"{elapsed // 3600}h {(elapsed % 3600) // 60}m"
                    if elapsed is not None else "unknown"
                )
                reward = quest["reported_xp"]
                xp_text = f"{reward} XP" if reward is not None else "XP unknown"
                lines.append(f"{when}  {name:<27}  {elapsed_text:<9}  {xp_text}")
        history.configure(state="normal")
        history.delete("1.0", tk.END)
        history.insert(tk.END, "\n".join(lines) if lines else "No sessions imported yet.")
        history.configure(state="disabled")

    def import_file() -> None:
        try:
            imported, total = import_sessions(Path(chosen.get()))
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        count = summarize_telemetry(default_database()).get("events", 0)
        status.set(
            f"Imported {imported} sessions ({total} total); "
            f"{count_quests()} quest events and {count} telemetry observations."
        )
        refresh()

    import_button.configure(command=import_file)
    refresh()
    app.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RivalMind local-only telemetry importer")
    parser.add_argument("--import-file", type=Path, help="Path to WoW's RivalMind.lua SavedVariables file")
    parser.add_argument("--database", type=Path, help="Optional SQLite location (default: user local data dir)")
    args = parser.parse_args(argv)
    if args.import_file:
        try:
            imported, total = import_sessions(args.import_file, args.database)
            print(f"Imported/updated {imported} sessions; {total} sessions and {count_quests(args.database)} quest events in SQLite")
            return 0
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            return 1
    gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())

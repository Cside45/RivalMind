"""RivalMind local companion, alpha.

No HTTP client, sockets, analytics SDK, telemetry, auto-update, or Lua evaluation.
Reads only an explicitly chosen RivalMind SavedVariables file.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import unquote

VERSION = "0.1.0-alpha"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 100
EXPORT_FIELD = re.compile(r'(?:\[\s*["\']export["\']\s*\]|\bexport)\s*=\s*"([^"\r\n]*)"')
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


def gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from datetime import datetime

    app = tk.Tk()
    app.title("RivalMind | Local Companion")
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

    ttk.Button(row, text="Browse…", command=choose).pack(side="right")
    status = tk.StringVar(value="Nothing is uploaded. Imports only touch files on your PC.")
    ttk.Label(app, textvariable=status, wraplength=540).pack(anchor="w", pady=(0, 10))
    ttk.Label(app, text="Recent sessions", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    history = tk.Text(app, height=10, wrap="none", state="disabled", relief="flat")
    history.pack(fill="both", expand=True, pady=(4, 4))

    def refresh() -> None:
        rows = read_recent()
        lines = []
        for started, duration, xp, deaths, zone in rows:
            when = datetime.fromtimestamp(started).strftime("%b %d %H:%M")
            lines.append(f"{when:<15}  {duration // 60:>3} min   {xp:>7} XP   {deaths} deaths   {zone[:28]}")
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
        status.set(f"Imported/updated {imported} local sessions. {total} sessions in your database.")
        refresh()

    ttk.Button(app, text="Import saved sessions", command=import_file).pack(anchor="e", pady=(10, 2))
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
            print(f"Imported/updated {imported} sessions; {total} in SQLite")
            return 0
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            return 1
    gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())

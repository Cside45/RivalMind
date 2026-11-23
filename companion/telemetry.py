"""Strict, local-only v0.4 event parser and SQLite analytics.

Events are observations, not inferred causes. In particular gold delta is not
profit, and an inventory delta does not prove an item was looted or sold.
"""
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote

MAX_EVENTS = 600
FIELD = re.compile(r'(?:\[\s*["\']telemetryExport["\']\s*\]|\btelemetryExport)\s*=\s*"([^"\r\n]*)"')
UNSIGNED = re.compile(r'\d{1,12}\Z')
SIGNED = re.compile(r'-?\d{1,12}\Z')
ENCODED = re.compile(r'(?:[A-Za-z0-9_.-]|%[0-9A-Fa-f]{2})*\Z')
CLASSES = {'WARRIOR', 'PALADIN', 'HUNTER', 'ROGUE', 'PRIEST', 'SHAMAN', 'MAGE',
           'WARLOCK', 'DRUID', 'DEATHKNIGHT', 'MONK', 'DEMONHUNTER', 'EVOKER'}


def _int(raw: str, signed: bool = False) -> int:
    if not (SIGNED if signed else UNSIGNED).fullmatch(raw):
        raise ValueError('Invalid numeric telemetry field')
    value = int(raw)
    if abs(value) > 500_000_000_000:
        raise ValueError('Out-of-range telemetry field')
    return value


def _decode(raw: str, max_len: int = 240) -> str:
    if len(raw) > max_len or not ENCODED.fullmatch(raw):
        raise ValueError('Invalid encoded telemetry field')
    return unquote(raw, encoding='utf-8', errors='replace')


def parse_telemetry_export(source: str) -> list[dict]:
    """Read only the special ASCII export; never evaluate SavedVariables Lua."""
    matches = FIELD.findall(source)
    if not matches:
        return []  # compatible with v0.1/v0.2 exports
    if len(matches) != 1:
        raise ValueError('Ambiguous telemetry export')
    pieces = matches[0].split(';')
    if pieces[0] != 'RT1' or len(pieces) - 1 > MAX_EVENTS:
        raise ValueError('Unsupported or oversized telemetry export')
    result, seen = [], set()
    for raw in pieces[1:]:
        fields = raw.split(',')
        if len(fields) != 6:
            raise ValueError('Malformed telemetry record')
        event_id, timestamp = _int(fields[0]), _int(fields[1])
        if not 0 < event_id < 2_000_000_000 or not 0 < timestamp < 5_000_000_000:
            raise ValueError('Invalid telemetry event ID or timestamp')
        if event_id in seen:
            raise ValueError('Duplicate telemetry event ID')
        seen.add(event_id)
        kind, a, b, c = fields[2:]
        if c:
            raise ValueError('Unexpected telemetry field')
        if kind == 'C':
            a = _decode(a, 72)
            if a not in CLASSES or not 1 <= _int(b) <= 1000:
                raise ValueError('Invalid character snapshot')
            b = str(_int(b))
        elif kind == 'Z':
            a, b = _decode(a), _decode(b)
            if not a or len(a) > 80 or len(b) > 80:
                raise ValueError('Invalid location snapshot')
        elif kind == 'E':
            if not 1 <= _int(a) <= 19 or _int(b) > 100_000_000:
                raise ValueError('Invalid equipment snapshot')
            a, b = str(_int(a)), str(_int(b))
        elif kind == 'G':
            a = str(_int(a))
            b = str(_int(b, signed=True)) if b else ''  # baseline isn't earned gold
        elif kind == 'B':
            if not 0 < _int(a) <= 100_000_000 or abs(_int(b, signed=True)) > 100_000:
                raise ValueError('Invalid bag quantity change')
            a, b = str(_int(a)), str(_int(b, signed=True))
        else:
            raise ValueError('Unknown telemetry event type')
        result.append({'id': event_id, 'stamp': timestamp,
                       'kind': kind, 'a': a, 'b': b, 'c': c})
    return result


def store_telemetry(connection: sqlite3.Connection, source_key: str,
                    imported_at: int, events: list[dict]) -> None:
    connection.execute('''CREATE TABLE IF NOT EXISTS telemetry_events (
        source_key TEXT NOT NULL, event_id INTEGER NOT NULL,
        stamp INTEGER NOT NULL, kind TEXT NOT NULL,
        a TEXT NOT NULL, b TEXT NOT NULL, c TEXT NOT NULL,
        imported_at INTEGER NOT NULL,
        PRIMARY KEY(source_key, event_id))''')
    connection.executemany('''INSERT INTO telemetry_events
        (source_key,event_id,stamp,kind,a,b,c,imported_at)
        VALUES (:source_key,:id,:stamp,:kind,:a,:b,:c,:imported_at)
        ON CONFLICT(source_key,event_id) DO UPDATE SET
          stamp=excluded.stamp,kind=excluded.kind,a=excluded.a,b=excluded.b,
          c=excluded.c,imported_at=excluded.imported_at''',
        [dict(record, source_key=source_key, imported_at=imported_at)
         for record in events])


def summarize_telemetry(database_path: Path) -> dict:
    """Deterministic aggregates over observed events; no model involved."""
    path = Path(database_path)
    if not path.is_file():
        return {}
    with sqlite3.connect(path) as connection:
        try:
            rows = connection.execute('''SELECT source_key,event_id,stamp,kind,a,b
                FROM telemetry_events ORDER BY source_key,stamp,event_id''').fetchall()
        except sqlite3.OperationalError:
            return {}
    gold_net, bag_changes, zone_changes, gear_changes = 0, 0, 0, 0
    latest_char = None
    latest_balance = None
    zones = set()
    for _, _, _, kind, a, b in rows:
        if kind == 'C':
            latest_char = (a, int(b))
        elif kind == 'G':
            latest_balance = int(a)
            if b != '':
                gold_net += int(b)
        elif kind == 'Z':
            zones.add(a)
            zone_changes += 1
        elif kind == 'B':
            bag_changes += 1
        elif kind == 'E':
            gear_changes += 1
    return {'events': len(rows), 'character': latest_char,
            'gold_net_copper': gold_net, 'last_observed_gold_copper': latest_balance,
            'zone_observations': zone_changes, 'distinct_zones': len(zones),
            'equipment_observations': gear_changes,
            'bag_quantity_changes': bag_changes}

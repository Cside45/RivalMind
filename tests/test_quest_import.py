"""Quest export backward compatibility, validation, and import tests."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "companion" / "rivalmind.py"
spec = importlib.util.spec_from_file_location("rivalmind", MODULE)
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

SESSION = '["export"] = "RM1;1,1763800000,420,1300,1,16,16,The%20Barrens"'
QUESTS = '["questExport"] = "RQ1;1,804,1763800010,A,,The%20Barrens,Harpy%20Raiders;2,804,1763800420,T,1400,The%20Barrens,Harpy%20Raiders"'


class QuestExportTests(unittest.TestCase):
    def test_alpha_01_export_has_no_quests(self):
        self.assertEqual(rm.parse_quest_export('RivalMindDB = { ' + SESSION + ' }'), [])

    def test_parses_quests_and_unknown_xp(self):
        result = rm.parse_quest_export('RivalMindDB = { ' + QUESTS + ' }')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["title"], "Harpy Raiders")
        self.assertIsNone(result[0]["reported_xp"])
        self.assertEqual(result[1]["kind"], "T")
        self.assertEqual(result[1]["reported_xp"], 1400)

    def test_removed_not_assumed_abandoned(self):
        raw = '["questExport"] = "RQ1;9,804,1763800420,R,,The%20Barrens,Harpy%20Raiders"'
        self.assertEqual(rm.parse_quest_export(raw)[0]["kind"], "R")

    def test_rejects_malformed_and_duplicate_records(self):
        bad = [
            '["questExport"] = "RQ2"',
            '["questExport"] = "RQ1;1,804,1763800010,X,,Zone,Quest"',
            '["questExport"] = "RQ1;1,804,1763800010,T,-4,Zone,Quest"',
            '["questExport"] = "RQ1;1,804,1763800010,T,,Zone,<script>"',
            '["questExport"] = "RQ1;1,804,1763800010,T,,Zone,Quest;1,804,1763800020,T,,Zone,Quest"',
            '["questExport"] = "RQ1;1,804,1763800010,T,,Zone,Quest", ["questExport"] = "RQ1"',
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    rm.parse_quest_export(raw)

    def test_upserts_quests_without_duplicate_records(self):
        with tempfile.TemporaryDirectory() as folder:
            lua = Path(folder) / "RivalMind.lua"
            lua.write_text('RivalMindDB = {\n' + SESSION + ',\n' + QUESTS + '\n}')
            database = Path(folder) / "rivalmind.sqlite3"
            self.assertEqual(rm.import_sessions(lua, database), (1, 1))
            self.assertEqual(rm.import_sessions(lua, database), (1, 1))
            self.assertEqual(rm.count_quests(database), 2)
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT kind, reported_xp FROM quest_events ORDER BY event_id"
                ).fetchall()
            self.assertEqual(rows, [("A", None), ("T", 1400)])


if __name__ == "__main__":
    unittest.main()

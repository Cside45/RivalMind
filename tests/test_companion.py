import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "companion" / "rivalmind.py"
spec = importlib.util.spec_from_file_location("rivalmind", MODULE)
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)


class ParserTests(unittest.TestCase):
    def test_realistic_savedvariables_and_percent_escapes(self):
        raw = 'RivalMindDB = {\n  ["export"] = "RM1;1,1763800000,420,1300,1,16,16,Stonetalon%20Mountains",\n}'
        sessions = rm.parse_export(raw)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["xp_earned"], 1300)
        self.assertEqual(sessions[0]["last_zone"], "Stonetalon Mountains")

    def test_rejects_bad_inputs_without_executing(self):
        for raw in [
            'RivalMindDB = { ["export"] = "RM1;1,1750000000,1,10,-1,2,2,A" }',
            'RivalMindDB = { ["export"] = "RM1;1,1750000000,1,10,1,2,2,A,EXTRA" }',
            'RivalMindDB = { ["export"] = "RM2" }',
            'RivalMindDB = { ["export"] = "RM1;1,1750000000,1,10,1,2,2,<script>" }',
            'RivalMindDB = { ["export"] = "RM1;1,1750000000,1,10,1,2,2,A", ["export"] = "RM1" }',
        ]:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    rm.parse_export(raw)

    def test_import_upserts_instead_of_duplication(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "RivalMind.lua"
            p.write_text('RivalMindDB = { ["export"] = "RM1;1,1763800000,420,1300,1,16,16,The%20Barrens" }')
            db = Path(folder) / "test.sqlite3"
            self.assertEqual(rm.import_sessions(p, db), (1, 1))
            self.assertEqual(rm.import_sessions(p, db), (1, 1))
            with sqlite3.connect(db) as cx:
                self.assertEqual(cx.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_no_export_before_first_logout(self):
        with self.assertRaises(ValueError):
            rm.parse_export('RivalMindDB = { ["schema"] = 1 }')


if __name__ == "__main__":
    unittest.main()

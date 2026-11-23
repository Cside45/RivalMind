"""Test elapsed quest analytics with out-of-order removals and missing data."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "companion" / "rivalmind.py"
spec = importlib.util.spec_from_file_location("rivalmind", MODULE)
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)


def event(source, ident, quest, when, kind, xp=None, title="Test Quest"):
    return source, ident, quest, when, kind, xp, title, "The Barrens"


class QuestEfficiencyTests(unittest.TestCase):
    def test_matched_turnin_elapsed_and_reward(self):
        rows = [
            event("a", 1, 801, 1000, "A"),
            event("a", 2, 801, 1300, "C"),
            event("a", 3, 801, 1450, "T", 1400),
        ]
        result = rm.analyze_quest_turnins(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["elapsed_seconds"], 450)
        self.assertEqual(result[0]["reported_xp"], 1400)
        self.assertEqual(result[0]["elapsed_xp_per_hour"], 11200)

    def test_missing_acceptance_has_unknown_duration(self):
        result = rm.analyze_quest_turnins([event("a", 9, 90, 1400, "T", 900)])
        self.assertIsNone(result[0]["accepted_at"])
        self.assertIsNone(result[0]["elapsed_seconds"])
        self.assertIsNone(result[0]["elapsed_xp_per_hour"])

    def test_removed_before_turnin_does_not_erase_acceptance(self):
        rows = [
            event("a", 1, 91, 1000, "A"),
            event("a", 2, 91, 1300, "R"),
            event("a", 3, 91, 1400, "T", 1000),
        ]
        self.assertEqual(rm.analyze_quest_turnins(rows)[0]["elapsed_seconds"], 400)

    def test_player_sources_not_cross_paired(self):
        rows = [
            event("player_a", 1, 92, 1000, "A"),
            event("player_b", 2, 92, 1300, "T", 100),
        ]
        self.assertIsNone(rm.analyze_quest_turnins(rows)[0]["elapsed_seconds"])

    def test_new_acceptance_replaces_old_observation(self):
        rows = [
            event("a", 1, 93, 1000, "A"),
            event("a", 2, 93, 2000, "A"),
            event("a", 3, 93, 2200, "T", 100),
        ]
        self.assertEqual(rm.analyze_quest_turnins(rows)[0]["elapsed_seconds"], 200)

    def test_zero_duration_or_unknown_reward_does_not_estimate_rate(self):
        a = rm.analyze_quest_turnins([
            event("a", 1, 94, 1000, "A"),
            event("a", 2, 94, 1000, "T", 120),
        ])[0]
        self.assertEqual(a["elapsed_seconds"], 0)
        self.assertIsNone(a["elapsed_xp_per_hour"])
        b = rm.analyze_quest_turnins([
            event("a", 1, 95, 1000, "A"),
            event("a", 2, 95, 1200, "T"),
        ])[0]
        self.assertIsNone(b["elapsed_xp_per_hour"])

    def test_reads_imported_database_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            savedvars = Path(folder) / "RivalMind.lua"
            savedvars.write_text(
                'RivalMindDB = {\n'
                '["export"] = "RM1;1,1763800000,420,1300,1,16,16,The%20Barrens",\n'
                '["questExport"] = "RQ1;1,804,1763800010,A,,The%20Barrens,Harpy%20Raiders;'
                '2,804,1763800420,R,,The%20Barrens,Harpy%20Raiders;'
                '3,804,1763800450,T,1400,The%20Barrens,Harpy%20Raiders"\n}'
            )
            db = Path(folder) / "test.sqlite3"
            rm.import_sessions(savedvars, db)
            rm.import_sessions(savedvars, db)
            quests = rm.read_quest_efficiency(db)
            self.assertEqual(len(quests), 1)
            self.assertEqual(quests[0]["elapsed_seconds"], 440)
            self.assertEqual(quests[0]["reported_xp"], 1400)


if __name__ == "__main__":
    unittest.main()

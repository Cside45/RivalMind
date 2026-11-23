"""Live-data contract tests for the local-only v0.4 telemetry format."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / 'companion' / 'telemetry.py'
spec = importlib.util.spec_from_file_location('rivalmind_telemetry', FILE)
telemetry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(telemetry)

BASE = ('RT1;1,1763800000,C,WARRIOR,35,;'
        '2,1763800001,G,200000,,;'
        '3,1763800020,G,220000,20000,;'
        '4,1763800030,Z,Stonetalon%20Mountains,Stonetalon%20Peak,;'
        '5,1763800040,E,16,12254,;'
        '6,1763800050,B,2589,-2,')


class TelemetryTests(unittest.TestCase):
    def test_all_event_types(self):
        rows = telemetry.parse_telemetry_export('RivalMindDB = { ["telemetryExport"] = "' + BASE + '" }')
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[3]['a'], 'Stonetalon Mountains')
        self.assertEqual(rows[3]['b'], 'Stonetalon Peak')
        self.assertEqual(rows[5]['b'], '-2')

    def test_separates_new_snapshots_from_legacy_observations(self):
        raw = (
            'telemetryExport = "RT1;'
            '1,1763800000,S,11,4444,;'
            '2,1763800010,E,11,5555,;'
            '3,1763800015,E,12,7777,"'
        )
        events = telemetry.parse_telemetry_export(raw)
        self.assertEqual([e['kind'] for e in events], ['S', 'E', 'E'])
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'history.sqlite3'
            with sqlite3.connect(db) as conn:
                telemetry.store_telemetry(conn, 'test', 10, events)
            summary = telemetry.summarize_telemetry(db)
            self.assertEqual(summary['equipment_baseline_snapshots'], 1)
            # "E" from legacy saves cannot be distinguished from actual
            # changes, so do not claim any verified changes from old rows.
            self.assertEqual(summary['equipment_legacy_unclassified'], 2)
            self.assertEqual(summary['equipment_confirmed_changes'], 0)

    def test_backward_compatible(self):
        self.assertEqual(telemetry.parse_telemetry_export('RivalMindDB = { ["export"] = "RM1" }'), [])

    def test_rejects_malicious_or_invalid_data(self):
        cases = [
            'RT0', 'RT1;1,1763800000,X,1,2,',
            'RT1;1,1763800000,G,1,-1,;1,1763800001,G,1,-1,',
            'RT1;1,1763800000,C,foobar,35,',
            'RT1;1,1763800000,Z,<script>,foo,',
            'RT1;1,1763800000,E,23,123,',
            'RT1;1,1763800000,B,40,-999999,',
            'RT1;1,1763800000,G,123,\x00,',
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    telemetry.parse_telemetry_export('telemetryExport = "' + case + '"')

    def test_rejects_multiple_export_fields(self):
        with self.assertRaises(ValueError):
            telemetry.parse_telemetry_export('telemetryExport = "RT1"; telemetryExport = "RT1"')

    def test_bounded_count(self):
        many = 'RT1;' + ';'.join(f'{i},1763800000,G,1,,' for i in range(1, 602))
        with self.assertRaises(ValueError):
            telemetry.parse_telemetry_export('telemetryExport = "' + many + '"')

    def test_idempotent_import_and_aggregates(self):
        events = telemetry.parse_telemetry_export('telemetryExport = "' + BASE + '"')
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'rivalmind.sqlite3'
            with sqlite3.connect(db) as conn:
                telemetry.store_telemetry(conn, 'testhash', 1763800050, events)
                telemetry.store_telemetry(conn, 'testhash', 1763800060, events)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM telemetry_events').fetchone()[0], 6)
            summary = telemetry.summarize_telemetry(db)
            self.assertEqual(summary['character'], ('WARRIOR', 35))
            self.assertEqual(summary['last_observed_gold_copper'], 220000)
            self.assertEqual(summary['gold_net_copper'], 20000)
            self.assertEqual(summary['distinct_zones'], 1)
            self.assertEqual(summary['bag_quantity_changes'], 1)

    def test_baseline_is_not_earned_gold(self):
        events = telemetry.parse_telemetry_export('telemetryExport = "RT1;1,1763800000,G,250000,,"')
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'db.sqlite3'
            with sqlite3.connect(db) as conn:
                telemetry.store_telemetry(conn, 'test', 10, events)
            self.assertEqual(telemetry.summarize_telemetry(db)['gold_net_copper'], 0)


if __name__ == '__main__':
    unittest.main()

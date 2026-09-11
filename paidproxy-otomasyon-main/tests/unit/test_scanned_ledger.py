"""Unit tests for ScannedLedger (Duplicate prevention)."""

from pathlib import Path
import tempfile
import unittest

from services.agentd.scanned_ledger import ScannedLedger


class TestScannedLedger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_file = Path(self.tmpdir.name) / "ledger.json"
        self.ledger = ScannedLedger(self.ledger_file)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_record_and_is_scanned(self):
        self.assertFalse(self.ledger.is_scanned("193.233.75.0/24", 3128))
        self.ledger.record_scan(
            asn="AS209207",
            cidr="193.233.75.0/24",
            ports=[3128],
            agent_id="agent-001",
            found_open_count=5,
        )
        self.assertTrue(self.ledger.is_scanned("193.233.75.0/24", 3128))
        self.assertFalse(self.ledger.is_scanned("193.233.75.0/24", 8080))

    def test_filter_unscanned_ports(self):
        self.ledger.record_scan("AS209207", "10.0.0.0/24", [80, 443])
        unscanned = self.ledger.filter_unscanned_ports("10.0.0.0/24", [80, 443, 8080, 1080])
        self.assertEqual(unscanned, [8080, 1080])

    def test_filter_unscanned_cidrs(self):
        self.ledger.record_scan("AS1", "10.1.0.0/24", 3128)
        unscanned = self.ledger.filter_unscanned_cidrs(["10.1.0.0/24", "10.2.0.0/24"], 3128)
        self.assertEqual(unscanned, ["10.2.0.0/24"])

    def test_persistence_reload(self):
        self.ledger.record_scan("AS100", "1.2.3.0/24", [1080], found_open_count=2, live_proxies_count=1)
        # Reload from disk in a fresh instance
        reloaded = ScannedLedger(self.ledger_file)
        self.assertTrue(reloaded.is_scanned("1.2.3.0/24", 1080))
        stats = reloaded.get_stats()
        self.assertEqual(stats["total_scans"], 1)
        self.assertEqual(stats["total_open_ports_found"], 2)
        self.assertEqual(stats["total_live_proxies_found"], 1)


if __name__ == "__main__":
    unittest.main()

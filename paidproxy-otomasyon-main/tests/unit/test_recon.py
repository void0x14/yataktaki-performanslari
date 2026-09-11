"""Unit tests for services.agentd.recon module."""

import unittest
from unittest.mock import MagicMock, patch

from services.agentd.recon import (
    classify_target,
    clean_asn,
    fetch_bgp_announced_prefixes,
    plan_grounded_hunt,
    sample_reverse_dns,
)


class TestReconModule(unittest.TestCase):
    def test_clean_asn(self):
        self.assertEqual(clean_asn("AS209207"), 209207)
        self.assertEqual(clean_asn("as12345"), 12345)
        self.assertEqual(clean_asn(6789), 6789)

    def test_dead_ground_classification(self):
        # Cloudflare ASN
        cf = classify_target(13335, "Cloudflare, Inc.")
        self.assertFalse(cf["is_targetable"])
        self.assertEqual(cf["classification"], "dead_ground")

        # Google Org Name
        goog = classify_target(99999, "Google Cloud Infrastructure")
        self.assertFalse(goog["is_targetable"])
        self.assertEqual(goog["classification"], "dead_ground")

    def test_hosting_squid_classification(self):
        target = classify_target(209207, "Digital Hosting Solutions LLC")
        self.assertTrue(target["is_targetable"])
        self.assertEqual(target["classification"], "datacenter_high_yield")
        self.assertEqual(target["priority"], 1)
        self.assertEqual(target["recommended_tooth"], 3128)

    def test_residential_classification(self):
        target = classify_target(1234, "Turknet Broadband Dynamic PPPoE")
        self.assertTrue(target["is_targetable"])
        self.assertEqual(target["classification"], "residential_pool")
        self.assertEqual(target["priority"], 2)
        self.assertEqual(target["recommended_tooth"], 1080)

    @patch("urllib.request.urlopen")
    def test_fetch_bgp_announced_prefixes(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data": {"prefixes": [{"prefix": "138.124.79.0/24"}, {"prefix": "138.124.0.0/21"}]}}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        prefixes = fetch_bgp_announced_prefixes(209207)
        self.assertIn("138.124.79.0/24", prefixes)
        self.assertIn("138.124.0.0/21", prefixes)

    def test_plan_grounded_hunt(self):
        plan = plan_grounded_hunt(
            209207,
            "Digital Hosting Solutions LLC",
            prefixes=["138.124.0.0/21", "138.124.79.0/24"],
        )
        self.assertTrue(plan["is_targetable"])
        self.assertEqual(plan["pilot_prefix"], "138.124.79.0/24")
        self.assertEqual(plan["initial_tooth"], 3128)
        self.assertEqual(plan["masscan_rate"], 5000)
        self.assertEqual(plan["socket_timeout"], 1.5)


if __name__ == "__main__":
    unittest.main()

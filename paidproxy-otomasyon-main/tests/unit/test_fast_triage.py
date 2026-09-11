"""Unit tests for FastTriageEngine."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.agentd.fast_triage import FastTriageEngine, run_fast_triage


class TestFastTriageEngine(unittest.TestCase):
    def setUp(self):
        self.engine = FastTriageEngine(concurrency=50, connect_timeout=1.0, retries=1)

    def _create_mock_writer(self):
        writer = AsyncMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        return writer

    def test_http_connect_407_auth_detected(self):
        async def _test():
            fake_reader = AsyncMock()
            fake_writer = self._create_mock_writer()
            fake_reader.readuntil.return_value = b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"

            with patch("asyncio.open_connection", return_value=(fake_reader, fake_writer)):
                res = await self.engine.probe_http_connect("1.2.3.4", 8080)
                self.assertTrue(res.get("proxy_detected"))
                self.assertTrue(res.get("auth_required"))
                self.assertFalse(res.get("egress_confirmed"))
                self.assertEqual(res.get("http_status"), 407)

        asyncio.run(_test())

    def test_http_connect_200_with_egress(self):
        async def _test():
            fake_reader = AsyncMock()
            fake_writer = self._create_mock_writer()
            fake_reader.readuntil.return_value = b"HTTP/1.1 200 Connection established\r\n\r\n"
            fake_reader.read.return_value = b"fl=123\r\nh=1.1.1.1\r\nip=203.0.113.50\r\nts=1690000000\r\n"

            with patch("asyncio.open_connection", return_value=(fake_reader, fake_writer)):
                res = await self.engine.probe_http_connect("1.2.3.4", 8000)
                self.assertTrue(res.get("proxy_detected"))
                self.assertFalse(res.get("auth_required"))
                self.assertTrue(res.get("egress_confirmed"))
                self.assertEqual(res.get("exit_ip"), "203.0.113.50")

        asyncio.run(_test())

    def test_socks5_successful_handshake_and_egress(self):
        async def _test():
            fake_reader = AsyncMock()
            fake_writer = self._create_mock_writer()
            # Greeting response: version 5, no auth (0x00)
            fake_reader.readexactly.return_value = b"\x05\x00"
            # Connect response: success (rep=0x00)
            fake_reader.read.side_effect = [
                b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50",
                b"fl=123\r\nip=198.51.100.99\r\n",
            ]

            with patch("asyncio.open_connection", return_value=(fake_reader, fake_writer)):
                res = await self.engine.probe_socks5("1.2.3.4", 1080)
                self.assertTrue(res.get("proxy_detected"))
                self.assertTrue(res.get("egress_confirmed"))
                self.assertEqual(res.get("exit_ip"), "198.51.100.99")

        asyncio.run(_test())

    def test_connection_refused_or_timeout_handled_gracefully(self):
        async def _test():
            with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
                res = await self.engine.probe_http_connect("192.0.2.1", 9999)
                self.assertFalse(res.get("proxy_detected"))
                self.assertFalse(res.get("egress_confirmed"))
                self.assertIn("Connection refused", res.get("error", ""))

        asyncio.run(_test())

    def test_batch_triage_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "live.jsonl"
            with patch.object(
                FastTriageEngine,
                "probe_endpoint",
                return_value={
                    "host": "1.2.3.4",
                    "port": 8080,
                    "egress_confirmed": True,
                    "proxy_detected": True,
                    "exit_ip": "1.2.3.4",
                    "verified_protocols": ["http_connect"],
                },
            ):
                summary = run_fast_triage([("1.2.3.4", 8080)], concurrency=10, output_path=out_file)
                self.assertEqual(summary["live_count"], 1)
                self.assertTrue(out_file.exists())
                self.assertIn("1.2.3.4", out_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

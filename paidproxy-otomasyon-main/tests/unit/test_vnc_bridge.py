"""Unit tests for VNCWebSocketBridge (noVNC websockify bridge)."""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from services.agentd.vnc_bridge import VNCWebSocketBridge, is_port_listening


class TestVNCWebSocketBridge(unittest.TestCase):
    def test_is_port_listening_false(self):
        # 59999 should not be in use
        self.assertFalse(is_port_listening("127.0.0.1", 59999, timeout=0.1))

    @patch("services.agentd.vnc_bridge.is_port_listening", return_value=True)
    def test_start_already_listening(self, mock_listen):
        bridge = VNCWebSocketBridge(listen_port=5901, target_port=5900)
        started = bridge.start()
        self.assertTrue(started)
        self.assertIsNone(bridge.process)

    @patch("services.agentd.vnc_bridge.is_port_listening", return_value=False)
    @patch("shutil.which", return_value=None)
    @patch("pathlib.Path.is_file", return_value=False)
    def test_start_missing_binary(self, mock_file, mock_which, mock_listen):
        bridge = VNCWebSocketBridge(listen_port=5901, target_port=5900)
        started = bridge.start()
        self.assertFalse(started)

    @patch("services.agentd.vnc_bridge.is_port_listening")
    def test_status(self, mock_listen):
        mock_listen.side_effect = [True, True]
        bridge = VNCWebSocketBridge(listen_port=5901, target_port=5900)
        stat = bridge.status()
        self.assertEqual(stat["listen_endpoint"], "127.0.0.1:5901")
        self.assertEqual(stat["target_endpoint"], "127.0.0.1:5900")
        self.assertTrue(stat["is_listening"])
        self.assertTrue(stat["target_available"])


if __name__ == "__main__":
    unittest.main()

"""Unit tests for dataset_recorder (ScreenRecorder and TrajectoryLogger)."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services.agentd.dataset_recorder import ScreenRecorder, TrajectoryLogger


class TestDatasetRecorder(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.trajectory_file = self.tmp_path / "trajectory.jsonl"
        self.video_file = self.tmp_path / "screen.mp4"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_trajectory_logger_record_step(self):
        logger = TrajectoryLogger(self.trajectory_file, agent_id="agent-test-1")
        entry = logger.record_step(
            step=1,
            state={"target_asn": "AS209207", "cidr": "193.233.75.0/24"},
            thought="Pilot range has open squid port",
            action={"tool": "fast_triage", "ports": [3128]},
            pty_stdout="[L7 PROBE] 193.233.75.1:3128 -> HTTP CONNECT 200 OK",
            outcome={"egress_confirmed": True, "open_port_count": 1},
        )
        self.assertEqual(entry["step"], 1)
        self.assertEqual(entry["agent_id"], "agent-test-1")
        self.assertEqual(entry["reward"], 1.0)
        self.assertEqual(entry["video_timecode_ms"], 0)

        # Check JSONL on disk
        lines = self.trajectory_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        disk_data = json.loads(lines[0])
        self.assertEqual(disk_data["step"], 1)
        self.assertEqual(disk_data["reward"], 1.0)

        summary = logger.get_summary()
        self.assertEqual(summary["total_steps"], 1)
        self.assertEqual(summary["total_reward"], 1.0)
        self.assertEqual(summary["egress_confirmed_count"], 1)

    def test_trajectory_logger_reward_heuristics(self):
        logger = TrajectoryLogger(self.trajectory_file, agent_id="agent-test-2")

        # Open port without egress: +0.3
        e1 = logger.record_step(step=1, outcome={"open_port_count": 3})
        self.assertEqual(e1["reward"], 0.3)

        # L4 positive count: +0.1
        e2 = logger.record_step(step=2, outcome={"l4_positive_count": 10})
        self.assertEqual(e2["reward"], 0.1)

        # Error: -0.5
        e3 = logger.record_step(step=3, outcome={"error": "Connection refused"})
        self.assertEqual(e3["reward"], -0.5)

        # Custom explicit reward override: 2.5
        e4 = logger.record_step(step=4, outcome={}, reward=2.5)
        self.assertEqual(e4["reward"], 2.5)

    def test_screen_recorder_missing_binary(self):
        recorder = ScreenRecorder(self.video_file, binary_path="/nonexistent/wf-recorder")
        started = recorder.start()
        self.assertFalse(started)
        self.assertFalse(recorder.is_active())
        self.assertEqual(recorder.get_timecode_ms(), 0)
        recorder.stop()

    @patch("shutil.which", return_value="/usr/bin/wf-recorder")
    @patch("pathlib.Path.is_file", return_value=True)
    @patch("subprocess.Popen")
    def test_screen_recorder_mocked_lifecycle(self, mock_popen, mock_is_file, mock_which):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        recorder = ScreenRecorder(
            self.video_file,
            output_display="HEADLESS-1",
            fps=15,
            binary_path="/usr/bin/wf-recorder",
        )
        started = recorder.start()
        self.assertTrue(started)
        self.assertTrue(recorder.is_active())

        # Check timecode increases
        timecode = recorder.get_timecode_ms()
        self.assertGreaterEqual(timecode, 0)

        # Synchronized trajectory logging
        logger = TrajectoryLogger(self.trajectory_file, agent_id="agent-sync", screen_recorder=recorder)
        entry = logger.record_step(step=1, thought="Testing sync timecode", outcome={})
        self.assertGreaterEqual(entry["video_timecode_ms"], 0)

        # Clean stop
        recorder.stop()
        mock_proc.send_signal.assert_called_once()
        self.assertFalse(recorder.is_active())

    def test_agent_runtime_trajectory_integration(self):
        from services.agentd.ai_runtime import AgentRuntime
        emit = MagicMock()
        runtime = AgentRuntime(
            root=self.tmp_path,
            agent_id="test-agent-rec",
            job_id="test-job",
            kind="hunter",
            initial_input="",
            emit=emit,
            stopped=lambda: False,
        )
        runtime.step = 1
        runtime.last_decision = {"action": "fast_triage", "expected_value": "Testing triage"}
        runtime._record_outcome("fast_triage", {"host": "1.2.3.4", "ports": [8080]}, {"open_ports": [8080], "egress_hits": []}, 15.0)

        traj_file = runtime.agent_dir / "trajectory.jsonl"
        self.assertTrue(traj_file.exists())
        lines = traj_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["step"], 1)
        self.assertEqual(data["llm_thought"], "Testing triage")
        self.assertEqual(data["action"]["tool"], "fast_triage")
        self.assertEqual(data["reward"], 0.3)


if __name__ == "__main__":
    unittest.main()

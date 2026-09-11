"""Unit tests for Preemptive Operator Interruption (Section 4.C)."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from services.agentd.ai_runtime import AgentRuntime
from services.agentd.fast_triage import FastTriageEngine
from services.agentd.state import StateStore


class TestPreemptiveInterrupt(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.emit = MagicMock()
        self.runtime = AgentRuntime(
            root=self.root,
            agent_id="test-interrupt-agent",
            job_id="test-job",
            kind="hunter",
            initial_input="",
            emit=self.emit,
            stopped=lambda: False,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_check_and_consume_interrupt(self):
        self.assertFalse(self.runtime.check_interrupt())
        self.assertIsNone(self.runtime.consume_interrupt())

        sig_path = self.runtime.agent_dir / "interrupt.signal"
        sig_path.write_text(json.dumps({"instruction": "STOP SCANNING THIS ASN", "action": "pivot"}), encoding="utf-8")

        self.assertTrue(self.runtime.check_interrupt())
        consumed = self.runtime.consume_interrupt()
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed["instruction"], "STOP SCANNING THIS ASN")
        self.assertFalse(sig_path.exists())
        self.assertFalse(self.runtime.check_interrupt())

    def test_state_append_directive_creates_signal(self):
        store = StateStore(self.root)
        agent = store.create_agent("hunter", "Test Hunter")
        agent_id = agent["agent_id"]
        directive = store.append_operator_directive(
            agent_id=agent_id,
            instruction="GEÇ BU BLOĞU",
        )
        self.assertEqual(directive["instruction"], "GEÇ BU BLOĞU")

        sig_file = self.root / "agents" / agent_id / "interrupt.signal"
        self.assertTrue(sig_file.exists())
        data = json.loads(sig_file.read_text(encoding="utf-8"))
        self.assertEqual(data["instruction"], "GEÇ BU BLOĞU")

    def test_fast_triage_cancels_immediately(self):
        engine = FastTriageEngine(concurrency=2, connect_timeout=1.0)
        is_canceled = False

        def cancel_check():
            return is_canceled

        loop = asyncio.new_event_loop()
        try:
            # Cancel immediately
            is_canceled = True
            results = loop.run_until_complete(
                engine.triage_cluster(
                    [("127.0.0.1", 1234), ("127.0.0.1", 1235)],
                    check_cancel=cancel_check,
                )
            )
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.get("canceled") for r in results))
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()

"""Multimodal Field Dataset Harvesting & Screen Recording Engine.

Enforces Section 5 (Saha Verisi Hasadı):
Continuously records:
1. Headless Sway video surface via wf-recorder (H.264 720p 15fps MP4).
2. Synchronized State-Action-Reward JSONL trajectory dataset with exact video timecodes.

Allows offline post-training, behavioral cloning, and fine-tuning of autonomous agent models.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger("agentd.recorder")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_wayland_env() -> dict[str, str]:
    """Resolve Wayland display and runtime environment for wf-recorder."""
    env = dict(os.environ)
    runtime_dir = Path("/run/paidproxy-wayland")
    if runtime_dir.is_dir():
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        socket_file = runtime_dir / "wayland-1"
        if socket_file.exists():
            env["WAYLAND_DISPLAY"] = "wayland-1"
        elif (runtime_dir / "wayland-0").exists():
            env["WAYLAND_DISPLAY"] = "wayland-0"
    return env


class ScreenRecorder:
    """Manages continuous background video capture of the Wayland headless display."""

    def __init__(
        self,
        output_path: Path | str,
        output_display: str = "HEADLESS-1",
        fps: int = 15,
        binary_path: str = "/usr/bin/wf-recorder",
    ) -> None:
        self.output_path = Path(output_path).resolve()
        self.output_display = str(os.environ.get("WF_RECORDER_OUTPUT") or output_display)
        self.fps = max(5, min(60, int(fps)))
        self.binary_path = binary_path if Path(binary_path).is_file() else (shutil.which("wf-recorder") or binary_path)
        self.process: subprocess.Popen | None = None
        self.start_time: float | None = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Start wf-recorder subprocess. Returns True if started successfully."""
        with self._lock:
            if self.is_active():
                return True
            if not Path(self.binary_path).is_file() and not shutil.which(self.binary_path):
                logger.warning(f"wf-recorder binary not found at {self.binary_path}; video capture disabled.")
                return False

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                self.binary_path,
                "-o",
                self.output_display,
                "-f",
                str(self.output_path),
                "-c",
                "libx264",
                "-p",
                "preset=ultrafast",
                "-p",
                "crf=26",
                "-r",
                str(self.fps),
            ]
            env = _resolve_wayland_env()
            try:
                self.process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                self.start_time = time.monotonic()
                # Give process a brief moment to catch immediate startup errors
                time.sleep(0.05)
                if self.process.poll() is not None:
                    stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
                    logger.warning(f"wf-recorder failed to start (exit code {self.process.returncode}): {stderr.strip()[:500]}")
                    self.process = None
                    self.start_time = None
                    return False
                logger.info(f"ScreenRecorder started: recording {self.output_display} to {self.output_path}")
                return True
            except Exception as exc:
                logger.warning(f"Exception starting ScreenRecorder: {exc}")
                self.process = None
                self.start_time = None
                return False

    def is_active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def get_timecode_ms(self) -> int:
        """Return elapsed milliseconds since recording started."""
        if not self.is_active() or self.start_time is None:
            return 0
        return int((time.monotonic() - self.start_time) * 1000)

    def stop(self, timeout_sec: float = 4.0) -> None:
        """Gracefully stop recording. SIGINT allows MP4 trailer to be finalized."""
        with self._lock:
            if not self.is_active() or self.process is None:
                self.process = None
                return
            proc = self.process
            self.process = None
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=timeout_sec)
                logger.info(f"ScreenRecorder stopped cleanly: {self.output_path}")
            except subprocess.TimeoutExpired:
                logger.warning(f"ScreenRecorder SIGINT timed out after {timeout_sec}s; sending SIGTERM.")
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as exc:
                logger.warning(f"Error stopping ScreenRecorder: {exc}")


class TrajectoryLogger:
    """Logs multimodal State-Action-Reward steps for agent dataset training."""

    def __init__(
        self,
        trajectory_path: Path | str,
        agent_id: str,
        screen_recorder: ScreenRecorder | None = None,
    ) -> None:
        self.trajectory_path = Path(trajectory_path).resolve()
        self.agent_id = str(agent_id).strip()
        self.screen_recorder = screen_recorder
        self._lock = threading.Lock()
        self.total_steps = 0
        self.total_reward = 0.0
        self.egress_confirmed_count = 0
        self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)

    def _compute_default_reward(self, outcome: dict[str, Any]) -> float:
        """Compute objective reward signal based on operational outcome."""
        if not isinstance(outcome, dict):
            return 0.0
        if outcome.get("egress_confirmed"):
            return 1.0
        if int(outcome.get("open_port_count", 0)) > 0 or outcome.get("open_ports"):
            return 0.3
        if int(outcome.get("l4_positive_count", 0)) > 0 or outcome.get("discovered"):
            return 0.1
        if outcome.get("error") or outcome.get("error_class"):
            return -0.5
        return 0.0

    def record_step(
        self,
        *,
        step: int,
        state: dict[str, Any] | None = None,
        thought: str = "",
        action: dict[str, Any] | None = None,
        pty_stdout: str = "",
        outcome: dict[str, Any] | None = None,
        reward: float | None = None,
    ) -> dict[str, Any]:
        """Record a single multimodal decision step with synchronized video timecode."""
        timecode_ms = self.screen_recorder.get_timecode_ms() if self.screen_recorder else 0
        outcome_data = dict(outcome or {})

        if reward is None:
            assigned_reward = self._compute_default_reward(outcome_data)
        else:
            assigned_reward = float(reward)

        assigned_reward = round(assigned_reward, 2)

        entry = {
            "timestamp": _utc_iso(),
            "agent_id": self.agent_id,
            "step": int(step),
            "video_timecode_ms": timecode_ms,
            "state": state or {},
            "llm_thought": str(thought or "").strip(),
            "action": action or {},
            "terminal_pty_stdout": str(pty_stdout or "")[-2000:],
            "outcome": outcome_data,
            "reward": assigned_reward,
        }

        with self._lock:
            self.total_steps += 1
            self.total_reward += assigned_reward
            if outcome_data.get("egress_confirmed"):
                self.egress_confirmed_count += 1
            with self.trajectory_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def get_summary(self) -> dict[str, Any]:
        """Return dataset harvesting metrics."""
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "trajectory_file": str(self.trajectory_path),
                "total_steps": self.total_steps,
                "total_reward": round(self.total_reward, 2),
                "egress_confirmed_count": self.egress_confirmed_count,
                "video_timecode_ms": self.screen_recorder.get_timecode_ms() if self.screen_recorder else 0,
            }

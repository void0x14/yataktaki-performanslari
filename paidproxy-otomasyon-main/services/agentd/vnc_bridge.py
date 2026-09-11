"""VDS WebSocket RFB Bridge (websockify bridge for wayvnc).

Enforces Section 4.B (Kesintisiz Video vs İsteğe Bağlı Ekran Ayrımı):
Decouples live screen streaming from agent execution:
- wf-recorder continuously records H.264 video to disk.
- websockify runs on 127.0.0.1:5901 proxying to wayvnc (127.0.0.1:5900).
- When Cockpit operator opens the screen tab, a native WebSocket connection connects on-demand.
- Zero Base64 / PNG overhead, 0 bytes/sec when tab is closed.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger("agentd.vnc_bridge")


def is_port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is currently listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except (OSError, ConnectionRefusedError):
            return False


class VNCWebSocketBridge:
    """Manages the websockify bridge daemon connecting WebSockets to wayvnc RFB."""

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 5901,
        target_host: str = "127.0.0.1",
        target_port: int = 5900,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.target_host = target_host
        self.target_port = int(target_port)
        self.process: subprocess.Popen | None = None

    def start(self) -> bool:
        """Start websockify if not already running."""
        if is_port_listening(self.listen_host, self.listen_port):
            logger.info(f"WebSocket bridge already listening on {self.listen_host}:{self.listen_port}")
            return True

        websockify_bin = shutil.which("websockify")
        if not websockify_bin:
            venv_bin = Path(sys.prefix) / "bin" / "websockify"
            if venv_bin.is_file():
                websockify_bin = str(venv_bin)

        if not websockify_bin:
            logger.warning("websockify binary not found; WebSocket VNC bridge unavailable.")
            return False

        cmd = [
            websockify_bin,
            f"{self.listen_host}:{self.listen_port}",
            f"{self.target_host}:{self.target_port}",
        ]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if is_port_listening(self.listen_host, self.listen_port):
                    logger.info(f"websockify started on {self.listen_host}:{self.listen_port} -> {self.target_host}:{self.target_port}")
                    return True
                time.sleep(0.1)
            return is_port_listening(self.listen_host, self.listen_port)
        except Exception as exc:
            logger.warning(f"Failed to start websockify: {exc}")
            return False

    def stop(self) -> None:
        """Stop the websockify process."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def status(self) -> dict[str, Any]:
        return {
            "listen_endpoint": f"{self.listen_host}:{self.listen_port}",
            "target_endpoint": f"{self.target_host}:{self.target_port}",
            "is_listening": is_port_listening(self.listen_host, self.listen_port),
            "target_available": is_port_listening(self.target_host, self.target_port),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Start websockify RFB bridge for wayvnc")
    parser.add_argument("--listen-port", type=int, default=5901)
    parser.add_argument("--target-port", type=int, default=5900)
    args = parser.parse_args()

    bridge = VNCWebSocketBridge(listen_port=args.listen_port, target_port=args.target_port)
    success = bridge.start()
    if not success:
        sys.stderr.write("Failed to start websockify bridge\n")
        return 1
    print(f"websockify bridge active: {bridge.status()}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()
        return 0


if __name__ == "__main__":
    sys.exit(main())

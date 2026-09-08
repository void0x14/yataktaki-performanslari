"""VDS bağlantı taşıyıcısı.

Ağ taraması ve ajan operasyonu burada çalışmaz. Bu modül yalnız SSH komutu
ve VDS loopback agentd için güvenilir port-forward prosesini yönetir.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import re
import socket
import subprocess
import time
from pathlib import Path


@dataclass
class VDSConfig:
    host: str = os.environ.get("PAIDPROXY_VDS_HOST", "20.207.198.170")
    user: str = os.environ.get("PAIDPROXY_VDS_USER", "mani")
    key: str = os.environ.get("PAIDPROXY_VDS_KEY", str(Path.home() / ".ssh" / "paidproxy_vds"))
    remote_dir: str = os.environ.get("PAIDPROXY_VDS_DIR", "~/paidproxy-otomasyon")
    remote_agentd_port: int = int(os.environ.get("PAIDPROXY_VDS_AGENTD_PORT", "8787") or 8787)
    wayvnc_loopback_port: int = int(os.environ.get("PAIDPROXY_WAYVNC_LOOPBACK_PORT", "5900") or 5900)
    connect_timeout: int = int(os.environ.get("PAIDPROXY_VDS_CONNECT_TIMEOUT", "10") or 10)
    local_agentd_port: int = int(os.environ.get("PAIDPROXY_LOCAL_AGENTD_PORT", "28787") or 28787)


def ssh_cmd(cfg: VDSConfig, remote: str) -> list[str]:
    return [
        "ssh",
        "-i",
        str(Path(cfg.key).expanduser()),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(cfg.connect_timeout)}",
        f"{cfg.user}@{cfg.host}",
        remote,
    ]


def run_remote(cfg: VDSConfig, remote: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Salt tanı/okuma çağrısı; bütün çıktıyı çağırana bırakır."""
    return subprocess.run(ssh_cmd(cfg, remote), capture_output=True, text=True, timeout=timeout)


def artifact_parts(ref: str, agent_id: str) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(agent_id)):
        raise ValueError("agent id contains unsafe characters")
    prefix = f"agent://{agent_id}/"
    if not str(ref).startswith(prefix):
        raise ValueError("artifact ref is outside the selected agent namespace")
    relative = str(ref)[len(prefix):]
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact ref contains an unsafe path")
    if path.parts[0] not in {"frames", "video", "outputs"} and path.name != "manifest.json":
        raise ValueError("artifact ref is not a permitted agent artifact")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", relative):
        raise ValueError("artifact ref contains unsafe characters")
    return agent_id, relative


def copy_artifact(
    cfg: VDSConfig,
    ref: str,
    destination: Path,
    *,
    agent_id: str,
    timeout: int = 30,
) -> Path:
    _agent_id, relative = artifact_parts(ref, agent_id)
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    remote_path = f"{cfg.remote_dir.rstrip('/')}/var/agentd/agents/{agent_id}/{relative}"
    command = [
        "scp",
        "-q",
        "-i",
        str(Path(cfg.key).expanduser()),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(cfg.connect_timeout)}",
        f"{cfg.user}@{cfg.host}:{remote_path}",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"scp exit {completed.returncode}").strip()
        raise ConnectionError(f"VDS artifact alınamadı: {detail[:1000]}")
    return destination


class SSHPortForward:
    """Masaüstünden VDS loopback agentd'e giden tek SSH tüneli."""

    def __init__(self, cfg: VDSConfig, remote_port: int | None = None) -> None:
        self.cfg = cfg
        self.remote_port = int(remote_port or cfg.remote_agentd_port)
        self.process: subprocess.Popen[str] | None = None
        self.local_port: int | None = None
        self.last_error = ""

    @staticmethod
    def _free_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def start(self, timeout: float = 15.0) -> int:
        if self.process is not None and self.process.poll() is None and self.local_port:
            return self.local_port
        local_port = self.cfg.local_agentd_port
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=1.0):
                self.local_port = local_port
                return local_port
        except OSError as exc:
            raise ConnectionError(
                f"Kalıcı yerel agentd tüneli hazır değil: 127.0.0.1:{local_port} ({exc})"
            ) from exc
        key = str(Path(self.cfg.key).expanduser())
        destination = f"{local_port}:127.0.0.1:{self.remote_port}"
        command = [
            "ssh",
            "-N",
            "-T",
            "-i",
            key,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={int(self.cfg.connect_timeout)}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=20",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "LogLevel=ERROR",
            "-L",
            destination,
            f"{self.cfg.user}@{self.cfg.host}",
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.local_port = local_port
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.last_error = (self.process.stderr.read() if self.process.stderr else "").strip()
                raise ConnectionError(
                    f"SSH port-forward exited with code {self.process.returncode}: {self.last_error}"
                )
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                    return local_port
            except OSError:
                time.sleep(0.15)
        self.last_error = (self.process.stderr.read(4000) if self.process.stderr else "").strip()
        self.stop()
        raise TimeoutError(f"SSH port-forward did not open local port: {self.last_error}")

    def set_remote_port(self, remote_port: int) -> None:
        remote_port = int(remote_port)
        if remote_port == self.remote_port:
            return
        if self.process is not None and self.process.poll() is None:
            self.stop()
        self.remote_port = remote_port

    def stop(self) -> None:
        process, self.process = self.process, None
        self.local_port = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if process.stderr:
            try:
                self.last_error = process.stderr.read(4000).strip()
            except (OSError, ValueError):
                pass


class WayVNCForward(SSHPortForward):
    """VDS'de yalnız 127.0.0.1'e bağlı wayvnc'i SSH ile yerel canlı görünüme taşır."""

    def __init__(self, cfg: VDSConfig, remote_port: int | None = None) -> None:
        super().__init__(cfg, remote_port or cfg.wayvnc_loopback_port)

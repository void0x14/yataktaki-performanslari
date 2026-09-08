"""Worker stdout/stderr FD handover primitives for a controlled agentd cutover.

Probe mode is read-only with respect to worker pipes: it maps and duplicates
read ends, verifies inode identity, and closes the duplicate without reading.
Serve/receive mode is opt-in and exists for a future cutover only.
"""
from __future__ import annotations

import argparse
import array
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
import time
from typing import Any


PROTOCOL_VERSION = 2
_AGENT_ID_RE = re.compile(r"[A-Za-z0-9._-]+")
_STREAMS = (("stdout", 1), ("stderr", 2))


class HandoverError(RuntimeError):
    """A handover cannot be proven safe and must fail closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_agent_id(agent_id: str) -> str:
    value = str(agent_id).strip()
    if not value or not _AGENT_ID_RE.fullmatch(value):
        raise HandoverError(f"unsafe agent id: {agent_id!r}")
    return value

def _worker_cmdline(pid: int) -> list[str]:
    path = Path(f"/proc/{int(pid)}/cmdline")
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise HandoverError(f"worker {pid} cmdline cannot be read") from exc
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _validate_worker_cmdline(pid: int, agent_id: str) -> None:
    argv = _worker_cmdline(pid)
    is_worker = any(
        item == "services.agentd.worker" or item.endswith("/services/agentd/worker.py")
        for item in argv
    )
    if not is_worker:
        raise HandoverError(f"process {pid} is not a PaidProxy worker")
    indexes = [index for index, item in enumerate(argv) if item == "--agent-id"]
    if len(indexes) != 1 or indexes[0] + 1 >= len(argv):
        raise HandoverError(f"worker {pid} has no unique --agent-id")
    if argv[indexes[0] + 1] != agent_id:
        raise HandoverError(f"worker {pid} agent id mismatch")


def _reject_unexpected_live_terminal_workers(persisted_agents: list[dict[str, Any]]) -> None:
    for agent in persisted_agents:
        state = str(agent.get("state", ""))
        if state in {"running", "paused", "stopping"}:
            continue
        pid = agent.get("pid")
        if not pid:
            continue
        agent_id = _safe_agent_id(str(agent.get("agent_id", "")))
        try:
            _validate_worker_cmdline(int(pid), agent_id)
        except HandoverError:
            continue
        raise HandoverError(
            f"terminal persisted worker is still alive as PaidProxy worker: {agent_id}"
        )


def _proc_stat(pid: int) -> dict[str, Any]:
    pid = int(pid)
    if pid <= 0:
        raise HandoverError(f"invalid pid: {pid}")
    path = Path(f"/proc/{pid}/stat")
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise HandoverError(f"process {pid} is not readable: {type(exc).__name__}") from exc
    close = raw.rfind(")")
    if close < 0:
        raise HandoverError(f"process {pid} stat is malformed")
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        raise HandoverError(f"process {pid} stat is incomplete")
    try:
        return {
            "pid": pid,
            "state": fields[0],
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "starttime_ticks": int(fields[19]),
        }
    except (TypeError, ValueError) as exc:
        raise HandoverError(f"process {pid} stat fields are malformed") from exc


def process_identity(
    pid: int,
    *,
    expected_starttime_ticks: int | None = None,
    expected_pgid: int | None = None,
    expected_ppid: int | None = None,
) -> dict[str, Any]:
    info = _proc_stat(pid)
    if info["state"] == "Z":
        raise HandoverError(f"process {pid} is zombie")
    if expected_starttime_ticks is not None and info["starttime_ticks"] != int(expected_starttime_ticks):
        raise HandoverError(f"process {pid} starttime mismatch")
    if expected_pgid is not None and info["pgid"] != int(expected_pgid):
        raise HandoverError(f"process {pid} process-group mismatch")
    if expected_ppid is not None and info["ppid"] != int(expected_ppid):
        raise HandoverError(f"process {pid} parent mismatch")
    return info


def process_identity_alive(pid: int, expected_starttime_ticks: int) -> bool:
    try:
        process_identity(pid, expected_starttime_ticks=expected_starttime_ticks)
    except HandoverError:
        return False
    return True


def open_pidfd(pid: int) -> int | None:
    opener = getattr(os, "pidfd_open", None)
    if opener is None:
        return None
    try:
        return int(opener(int(pid), 0))
    except (OSError, ValueError):
        return None


def wait_for_pid_exit(
    pid: int,
    expected_starttime_ticks: int,
    *,
    pidfd: int | None = None,
    timeout: float | None = None,
) -> bool:
    """Wait for disappearance of the exact process identity, never infer exit code."""
    deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
    if pidfd is not None:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        events = poller.poll(None if remaining is None else int(remaining * 1000))
        if events:
            return not process_identity_alive(pid, expected_starttime_ticks)
    while process_identity_alive(pid, expected_starttime_ticks):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _pipe_inode(pid: int, fd_number: int) -> int:
    path = Path(f"/proc/{int(pid)}/fd/{int(fd_number)}")
    try:
        target = os.readlink(path)
    except (FileNotFoundError, OSError) as exc:
        raise HandoverError(f"worker {pid} fd {fd_number} cannot be read") from exc
    match = re.fullmatch(r"pipe:\[(\d+)\]", target)
    if not match:
        raise HandoverError(f"worker {pid} fd {fd_number} is not a pipe: {target}")
    return int(match.group(1))


def _matching_agentd_fd(agentd_pid: int, inode: int) -> int:
    matches: list[int] = []
    directory = Path(f"/proc/{int(agentd_pid)}/fd")
    try:
        entries = sorted(directory.iterdir(), key=lambda item: int(item.name))
    except (FileNotFoundError, OSError) as exc:
        raise HandoverError(f"agentd {agentd_pid} fd directory is unreadable") from exc
    for entry in entries:
        try:
            if stat.S_ISFIFO(entry.stat().st_mode) and int(entry.stat().st_ino) == int(inode):
                matches.append(int(entry.name))
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    if len(matches) != 1:
        raise HandoverError(
            f"pipe inode {inode} maps to {len(matches)} agentd read FDs, expected exactly one"
        )
    return matches[0]


def _duplicate_pipe_fd(agentd_pid: int, agentd_fd: int, inode: int, *, nonblocking: bool) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if nonblocking:
        flags |= os.O_NONBLOCK
    path = f"/proc/{int(agentd_pid)}/fd/{int(agentd_fd)}"
    try:
        duplicate = os.open(path, flags)
        duplicate_inode = int(os.fstat(duplicate).st_ino)
    except (FileNotFoundError, PermissionError, OSError, ValueError) as exc:
        raise HandoverError(
            f"agentd fd {agentd_fd} could not be duplicated for pipe {inode}"
        ) from exc
    if duplicate_inode != int(inode):
        try:
            os.close(duplicate)
        except OSError:
            pass
        raise HandoverError(f"duplicated fd inode mismatch for pipe {inode}")
    return duplicate


def _persisted_workers(persisted_agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    workers: list[dict[str, Any]] = []
    for agent in persisted_agents:
        if agent.get("state") not in {"running", "paused", "stopping"}:
            continue
        agent_id = _safe_agent_id(str(agent.get("agent_id", "")))
        pid = agent.get("pid")
        process_group = agent.get("process_group")
        if not pid or not process_group:
            raise HandoverError(f"persisted worker {agent_id} lacks PID/PGID")
        workers.append(
            {
                "agent_id": agent_id,
                "pid": int(pid),
                "process_group": int(process_group),
                "state": str(agent.get("state")),
            }
        )
    return sorted(workers, key=lambda item: item["agent_id"])

def _live_persisted_workers(persisted_agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live: list[dict[str, Any]] = []
    for worker in _persisted_workers(persisted_agents):
        stat_path = Path(f"/proc/{worker['pid']}/stat")
        try:
            process_identity(worker["pid"], expected_pgid=worker["process_group"])
            _validate_worker_cmdline(worker["pid"], worker["agent_id"])
        except HandoverError:
            if not stat_path.exists():
                continue
            raise
        live.append(worker)
    return live


def _validated_worker_rows(
    *,
    root: Path,
    old_agentd_pid: int,
    persisted_agents: list[dict[str, Any]],
    duplicate: bool,
    nonblocking: bool,
) -> tuple[list[dict[str, Any]], list[int]]:
    root = Path(root).expanduser().resolve()
    old_agentd_pid = int(old_agentd_pid)
    process_identity(old_agentd_pid)
    _reject_unexpected_live_terminal_workers(persisted_agents)
    workers = _live_persisted_workers(persisted_agents)
    rows: list[dict[str, Any]] = []
    held_fds: list[int] = []
    seen_pipes: set[int] = set()
    for worker in workers:
        identity = process_identity(
            worker["pid"],
            expected_pgid=worker["process_group"],
            expected_ppid=old_agentd_pid,
        )
        _validate_worker_cmdline(worker["pid"], worker["agent_id"])
        streams: dict[str, dict[str, Any]] = {}
        for stream_name, worker_fd in _STREAMS:
            inode = _pipe_inode(worker["pid"], worker_fd)
            if inode in seen_pipes:
                raise HandoverError(f"duplicate worker pipe inode: {inode}")
            seen_pipes.add(inode)
            agentd_fd = _matching_agentd_fd(old_agentd_pid, inode)
            stream_info: dict[str, Any] = {
                "worker_fd": worker_fd,
                "pipe_inode": inode,
                "old_agentd_fd": agentd_fd,
                "fd_index": None,
                "duplicate_verified": False,
            }
            if duplicate:
                duplicate_fd = _duplicate_pipe_fd(
                    old_agentd_pid,
                    agentd_fd,
                    inode,
                    nonblocking=nonblocking,
                )
                stream_info["duplicate_verified"] = int(os.fstat(duplicate_fd).st_ino) == inode
                if not stream_info["duplicate_verified"]:
                    os.close(duplicate_fd)
                    raise HandoverError(f"duplicate verification failed for pipe {inode}")
                stream_info["fd_index"] = len(held_fds)
                held_fds.append(duplicate_fd)
            streams[stream_name] = stream_info
        rows.append(
            {
                **worker,
                "starttime_ticks": identity["starttime_ticks"],
                "stdout": streams["stdout"],
                "stderr": streams["stderr"],
            }
        )
    return rows, held_fds


def build_probe_manifest(
    root: Path,
    old_agentd_pid: int,
    persisted_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    rows, held_fds = _validated_worker_rows(
        root=root,
        old_agentd_pid=old_agentd_pid,
        persisted_agents=persisted_agents,
        duplicate=True,
        nonblocking=True,
    )
    for fd in held_fds:
        os.close(fd)
    persisted_candidate_ids = {
        _safe_agent_id(str(agent.get("agent_id", "")))
        for agent in persisted_agents
        if agent.get("state") in {"running", "paused", "stopping"} and agent.get("pid")
    }
    mapped_ids = {str(row["agent_id"]) for row in rows}
    return {
        "manifest_version": PROTOCOL_VERSION,
        "mode": "probe",
        "manifest_id": f"probe-{os.getpid()}-{time.time_ns()}",
        "root": str(Path(root).expanduser().resolve()),
        "old_agentd_pid": int(old_agentd_pid),
        "created_at": utc_now(),
        "workers": rows,
        "persisted_state_candidate_count": len(persisted_candidate_ids),
        "live_process_candidate_count": len(rows),
        "omitted_persisted_candidates": sorted(persisted_candidate_ids - mapped_ids),
        "stream_count": len(rows) * len(_STREAMS),
        "duplicate_fds_closed": True,
    }


def _manifest_worker_ids(manifest: dict[str, Any]) -> set[str]:
    workers = manifest.get("workers")
    if not isinstance(workers, list):
        raise HandoverError("handover manifest workers is not a list")
    ids: set[str] = set()
    for worker in workers:
        if not isinstance(worker, dict):
            raise HandoverError("handover worker entry is not an object")
        agent_id = _safe_agent_id(str(worker.get("agent_id", "")))
        if agent_id in ids:
            raise HandoverError(f"duplicate handover agent: {agent_id}")
        ids.add(agent_id)
    return ids


def _validate_received_manifest(
    manifest: dict[str, Any],
    *,
    root: Path,
    persisted_agents: list[dict[str, Any]],
    expected_old_agentd_pid: int,
    received_fds: list[int],
) -> list[dict[str, Any]]:
    if int(manifest.get("manifest_version", -1)) != PROTOCOL_VERSION:
        raise HandoverError("unsupported handover manifest version")
    if manifest.get("mode") != "serve":
        raise HandoverError("received handover is not serve mode")
    expected_root = str(Path(root).expanduser().resolve())
    if str(manifest.get("root", "")) != expected_root:
        raise HandoverError("handover root mismatch")
    if int(manifest.get("old_agentd_pid", -1)) != int(expected_old_agentd_pid):
        raise HandoverError("old agentd identity mismatch")
    _reject_unexpected_live_terminal_workers(persisted_agents)
    persisted = _live_persisted_workers(persisted_agents)
    expected_by_id = {item["agent_id"]: item for item in persisted}
    if _manifest_worker_ids(manifest) != set(expected_by_id):
        raise HandoverError("handover worker set is not complete")
    workers = list(manifest["workers"])
    expected_fd_count = len(workers) * len(_STREAMS)
    if len(received_fds) != expected_fd_count:
        raise HandoverError(f"handover delivered {len(received_fds)} FDs, expected {expected_fd_count}")
    fd_indexes: set[int] = set()
    adopted: list[dict[str, Any]] = []
    for worker in workers:
        agent_id = _safe_agent_id(str(worker.get("agent_id", "")))
        expected = expected_by_id[agent_id]
        pid = int(worker.get("pid", -1))
        pgid = int(worker.get("process_group", -1))
        if pid != expected["pid"] or pgid != expected["process_group"]:
            raise HandoverError(f"PID/PGID mismatch for {agent_id}")
        manifest_state = worker.get("state")
        if manifest_state not in {"running", "paused", "stopping"}:
            raise HandoverError(f"invalid manifest state for {agent_id}")
        if manifest_state != expected["state"]:
            raise HandoverError(f"manifest state mismatch for {agent_id}")
        starttime = int(worker.get("starttime_ticks", -1))
        process_identity(
            pid,
            expected_starttime_ticks=starttime,
            expected_pgid=pgid,
        )
        _validate_worker_cmdline(pid, agent_id)
        adopted_streams: dict[str, Any] = {}
        for stream_name, _worker_fd in _STREAMS:
            stream = worker.get(stream_name)
            if not isinstance(stream, dict):
                raise HandoverError(f"missing {stream_name} handover stream for {agent_id}")
            inode = int(stream.get("pipe_inode", -1))
            fd_index = int(stream.get("fd_index", -1))
            if fd_index in fd_indexes or not 0 <= fd_index < len(received_fds):
                raise HandoverError(f"invalid or duplicate fd index for {agent_id}/{stream_name}")
            fd_indexes.add(fd_index)
            duplicate_inode = int(os.fstat(received_fds[fd_index]).st_ino)
            if duplicate_inode != inode:
                raise HandoverError(f"received {stream_name} inode mismatch for {agent_id}")
            adopted_streams[stream_name] = os.fdopen(
                received_fds[fd_index],
                "r",
                buffering=1,
                encoding="utf-8",
                errors="replace",
                closefd=True,
            )
        adopted.append(
            {
                "agent_id": agent_id,
                "pid": pid,
                "process_group": pgid,
                "state": manifest_state,
                "starttime_ticks": starttime,
                "stdout": adopted_streams["stdout"],
                "stderr": adopted_streams["stderr"],
                "pidfd": open_pidfd(pid),
            }
        )
    return adopted



@dataclass
class HandoverSession:
    manifest: dict[str, Any]
    adopted: list[dict[str, Any]]
    connection: socket.socket
    committed: bool = False

    def commit(self) -> None:
        if self.committed:
            raise HandoverError("handover adoption_commit was already sent")
        payload = (
            json.dumps(
                {
                    "type": "adoption_commit",
                    "manifest_id": self.manifest["manifest_id"],
                    "protocol_version": PROTOCOL_VERSION,
                },
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self.connection.sendall(payload)
        self.connection.close()
        self.committed = True

    def close_without_commit(self) -> None:
        if self.committed:
            return
        try:
            self.connection.close()
        finally:
            _close_received_adopted(self.adopted)


def serve_handover(
    root: Path,
    old_agentd_pid: int,
    persisted_agents: list[dict[str, Any]],
    socket_path: Path,
    *,
    lease_seconds: float = 60.0,
) -> dict[str, Any]:
    rows, held_fds = _validated_worker_rows(
        root=root,
        old_agentd_pid=old_agentd_pid,
        persisted_agents=persisted_agents,
        duplicate=True,
        nonblocking=False,
    )
    manifest = {
        "manifest_version": PROTOCOL_VERSION,
        "mode": "serve",
        "manifest_id": f"handover-{os.getpid()}-{time.time_ns()}",
        "root": str(Path(root).expanduser().resolve()),
        "old_agentd_pid": int(old_agentd_pid),
        "created_at": utc_now(),
        "workers": rows,
    }
    socket_path = Path(socket_path).expanduser().resolve()
    if socket_path.exists():
        for fd in held_fds:
            os.close(fd)
        raise HandoverError(f"handover socket already exists: {socket_path}")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    committed = False
    deadline = time.monotonic() + max(0.1, float(lease_seconds))
    try:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(4)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HandoverError("handover adoption_commit deadline expired")
            server.settimeout(remaining)
            try:
                connection, _ = server.accept()
            except socket.timeout as exc:
                raise HandoverError("handover adoption_commit deadline expired") from exc
            try:
                connection.settimeout(remaining)
                payload = (
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8")
                fd_array = array.array("i", held_fds)
                connection.sendmsg(
                    [payload],
                    [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fd_array.tobytes())],
                )
                raw = connection.recv(4096)
                lines = raw.splitlines()
                message = json.loads(lines[0].decode("utf-8")) if lines else {}
                if (
                    message.get("type") != "adoption_commit"
                    or message.get("manifest_id") != manifest["manifest_id"]
                    or int(message.get("protocol_version", -1)) != PROTOCOL_VERSION
                ):
                    continue
                committed = True
                return manifest
            except socket.timeout:
                continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            finally:
                connection.close()
    finally:
        for fd in held_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        server.close()
        try:
            socket_path.unlink()
        except OSError:
            pass
        if not committed:
            pass


def _receive_handover_once(
    root: Path,
    socket_path: Path,
    persisted_agents: list[dict[str, Any]],
    expected_old_agentd_pid: int,
) -> HandoverSession:
    socket_path = Path(socket_path).expanduser().resolve()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    received_fds: list[int] = []
    keep_connection = False
    try:
        connection.settimeout(30.0)
        connection.connect(str(socket_path))
        raw, ancdata, _flags, _address = connection.recvmsg(
            1024 * 1024,
            socket.CMSG_SPACE(256 * array.array("i").itemsize),
        )
        for level, message_type, data in ancdata:
            if level == socket.SOL_SOCKET and message_type == socket.SCM_RIGHTS:
                values = array.array("i")
                usable = len(data) - (len(data) % values.itemsize)
                values.frombytes(data[:usable])
                received_fds.extend(int(value) for value in values)
        lines = raw.splitlines()
        line = lines[0] if lines else b""
        manifest = json.loads(line.decode("utf-8")) if line else {}
        adopted = _validate_received_manifest(
            manifest,
            root=root,
            persisted_agents=persisted_agents,
            expected_old_agentd_pid=expected_old_agentd_pid,
            received_fds=received_fds,
        )
        session = HandoverSession(manifest=manifest, adopted=adopted, connection=connection)
        keep_connection = True
        received_fds = []
        return session
    except (HandoverError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HandoverError(f"handover receive failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if not keep_connection:
            connection.close()
        for fd in received_fds:
            try:
                os.close(fd)
            except OSError:
                pass


def receive_handover(
    root: Path,
    socket_path: Path,
    persisted_agents: list[dict[str, Any]],
    expected_old_agentd_pid: int,
) -> HandoverSession:
    return _receive_handover_once(
        root,
        socket_path,
        persisted_agents,
        expected_old_agentd_pid,
    )


def _close_received_adopted(adopted: list[dict[str, Any]]) -> None:
    for item in adopted:
        for stream_name in ("stdout", "stderr"):
            stream = item.get(stream_name)
            if stream is None:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        pidfd = item.get("pidfd")
        if pidfd is not None:
            try:
                os.close(int(pidfd))
            except OSError:
                pass


def _probe_summary(session: HandoverSession) -> dict[str, Any]:
    return {
        "manifest_version": session.manifest.get("manifest_version"),
        "mode": "receive-probe",
        "manifest_id": session.manifest.get("manifest_id"),
        "validated": True,
        "committed": session.committed,
        "worker_count": len(session.adopted),
        "stream_count": len(session.adopted) * len(_STREAMS),
        "stream_bytes_read": 0,
        "inode_validation": True,
        "workers": [
            {
                "agent_id": item["agent_id"],
                "pid": item["pid"],
                "process_group": item["process_group"],
                "state": item["state"],
                "streams_validated": len(_STREAMS),
            }
            for item in session.adopted
        ],
    }


def receive_handover_probe(
    root: Path,
    socket_path: Path,
    persisted_agents: list[dict[str, Any]],
    expected_old_agentd_pid: int,
    *,
    hold_seconds: float = 0.5,
) -> dict[str, Any]:
    session = receive_handover(
        root,
        socket_path,
        persisted_agents,
        expected_old_agentd_pid,
    )
    try:
        time.sleep(min(30.0, max(0.0, float(hold_seconds))))
        session.commit()
        return _probe_summary(session)
    finally:
        if session.committed:
            _close_received_adopted(session.adopted)
        else:
            session.close_without_commit()


def receive_handover_abort_probe(
    root: Path,
    socket_path: Path,
    persisted_agents: list[dict[str, Any]],
    expected_old_agentd_pid: int,
) -> dict[str, Any]:
    session = receive_handover(
        root,
        socket_path,
        persisted_agents,
        expected_old_agentd_pid,
    )
    try:
        summary = _probe_summary(session)
        summary["mode"] = "receive-abort-probe"
        return summary
    finally:
        session.close_without_commit()
def _load_persisted_agents(root: Path) -> list[dict[str, Any]]:
    agents_path = Path(root).expanduser().resolve() / "agents.json"
    try:
        payload = json.loads(agents_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise HandoverError(f"agents.json cannot be read: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise HandoverError("agents.json is not an object")
    return [dict(agent) for agent in payload.values() if isinstance(agent, dict)]


def probe(root: Path, old_agentd_pid: int) -> dict[str, Any]:
    return build_probe_manifest(Path(root), int(old_agentd_pid), _load_persisted_agents(Path(root)))


def main() -> int:
    parser = argparse.ArgumentParser(description="PaidProxy worker FD handover")
    parser.add_argument("--root", default="var/agentd")
    parser.add_argument("--agentd-pid", type=int, required=True)
    parser.add_argument("--mode", choices=("probe", "serve", "receive-probe", "receive-abort-probe"), default="probe")
    parser.add_argument("--socket")
    parser.add_argument("--lease-seconds", type=float, default=60.0)
    parser.add_argument("--hold-seconds", type=float, default=0.5)
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    try:
        if args.mode == "probe":
            print(json.dumps(probe(root, args.agentd_pid), ensure_ascii=False))
            return 0
        if args.mode == "receive-probe":
            if not args.socket:
                raise HandoverError("receive-probe mode requires --socket")
            summary = receive_handover_probe(
                root,
                Path(args.socket),
                _load_persisted_agents(root),
                args.agentd_pid,
                hold_seconds=args.hold_seconds,
            )
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        if args.mode == "receive-abort-probe":
            if not args.socket:
                raise HandoverError("receive-abort-probe mode requires --socket")
            summary = receive_handover_abort_probe(
                root,
                Path(args.socket),
                _load_persisted_agents(root),
                args.agentd_pid,
            )
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        if not args.socket:
            raise HandoverError("serve mode requires --socket")
        manifest = serve_handover(
            root,
            args.agentd_pid,
            _load_persisted_agents(root),
            Path(args.socket),
            lease_seconds=args.lease_seconds,
        )
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    except HandoverError as exc:
        print(json.dumps({"error": str(exc), "mode": args.mode}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

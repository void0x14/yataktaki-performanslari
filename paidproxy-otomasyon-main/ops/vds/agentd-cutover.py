#!/usr/bin/env python3
"""Read-only preflight for the future PaidProxy agentd cutover transaction.

This command intentionally has no execute path. It reads effective systemd,
/proc, the production loopback listener, and the existing zero-read handover
probe, then renders the future transaction without writing it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


CANONICAL_ROOT = Path("/home/mani/paidproxy-otomasyon")
STATE_ROOT = CANONICAL_ROOT / "var" / "agentd"
UNIT_NAME = "paidproxy-agentd.service"
SERVICE_USER = "mani"
PRODUCTION_HOST = "127.0.0.1"
PRODUCTION_PORT = 8787
RUNTIME_DROPIN = Path("/run/systemd/system/paidproxy-agentd.service.d/90-paidproxy-handover.conf")
PLANNED_HANDOVER_SOCKET = "/run/paidproxy-agentd-handover/paidproxy-agentd.sock"
EXPECTED_LIVE_WORKERS = 10
WORKER_IO_SLOTS_PER_WORKER = 3


class PreflightError(RuntimeError):
    pass


def _readonly_run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"read-only command failed: {' '.join(command)}: {exc}") from exc


def _systemd_properties() -> dict[str, str]:
    properties = [
        "MainPID",
        "ActiveState",
        "SubState",
        "ExecStart",
        "Restart",
        "KillMode",
        "FragmentPath",
        "DropInPaths",
        "ControlGroup",
        "User",
    ]
    result = _readonly_run(
        [
            "systemctl",
            "show",
            UNIT_NAME,
            "--property=" + ",".join(properties),
            "--no-pager",
            "--plain",
        ]
    )
    if result.returncode != 0:
        raise PreflightError(result.stderr.strip() or "systemctl show returned non-zero")
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    return parsed


def _proc_identity(pid: int) -> dict[str, Any]:
    stat_path = Path(f"/proc/{int(pid)}/stat")
    try:
        raw_stat = stat_path.read_text(encoding="utf-8")
        cmdline_raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        cgroup_raw = Path(f"/proc/{int(pid)}/cgroup").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return {
            "process_present": False,
            "identity_error": f"{type(exc).__name__}: {exc}",
        }

    try:
        stat_tail = raw_stat.rsplit(")", 1)[1].split()
        ppid = int(stat_tail[1])
        process_group = int(stat_tail[2])
        starttime_ticks = int(stat_tail[19])
    except (IndexError, ValueError) as exc:
        return {
            "process_present": True,
            "identity_error": f"invalid /proc stat: {exc}",
        }

    cgroup_paths = []
    for line in cgroup_raw.splitlines():
        if "::" in line:
            cgroup_paths.append(line.split("::", 1)[1])
        else:
            parts = line.split(":", 2)
            if len(parts) == 3:
                cgroup_paths.append(parts[2])
    return {
        "process_present": True,
        "ppid": ppid,
        "process_group": process_group,
        "starttime_ticks": starttime_ticks,
        "argv": [item for item in cmdline_raw.decode("utf-8", "replace").split("\0") if item],
        "cgroup_paths": cgroup_paths,
        "cgroup": cgroup_paths[-1] if cgroup_paths else None,
    }


def _persisted_workers() -> list[dict[str, Any]]:
    agents_dir = STATE_ROOT / "agents"
    records: list[dict[str, Any]] = []
    if not agents_dir.is_dir():
        raise PreflightError(f"state agents directory missing: {agents_dir}")
    for manifest_path in sorted(agents_dir.glob("*/manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PreflightError(f"manifest unreadable: {manifest_path}: {exc}") from exc
        state = str(payload.get("state", ""))
        if state not in {"running", "paused", "stopping"}:
            continue
        records.append(
            {
                "agent_id": str(payload.get("agent_id", manifest_path.parent.name)),
                "state": state,
                "pid": payload.get("pid"),
                "process_group": payload.get("process_group"),
                "manifest": str(manifest_path),
            }
        )
    return records


def _worker_inventory(main_pid: int, control_group: str) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for record in _persisted_workers():
        agent_id = record["agent_id"]
        pid = int(record["pid"]) if record.get("pid") else None
        observed = _proc_identity(pid) if pid else {"process_present": False}
        argv = observed.get("argv", [])
        agent_id_index = argv.index("--agent-id") if "--agent-id" in argv else -1
        cmdline_match = bool(
            observed.get("process_present", False)
            and "services.agentd.worker" in argv
            and agent_id_index >= 0
            and len(argv) > agent_id_index + 1
            and argv[agent_id_index + 1] == agent_id
        )
        expected_pgid = int(record["process_group"]) if record.get("process_group") else None
        identity_ok = bool(
            observed.get("process_present")
            and observed.get("ppid") == main_pid
            and observed.get("process_group") == expected_pgid
            and cmdline_match
        )
        inventory.append(
            {
                "agent_id": agent_id,
                "state": record["state"],
                "pid": pid,
                "persisted_process_group": expected_pgid,
                "process_present": bool(observed.get("process_present")),
                "ppid": observed.get("ppid"),
                "process_group": observed.get("process_group"),
                "starttime_ticks": observed.get("starttime_ticks"),
                "cmdline_match": cmdline_match,
                "identity_ok": identity_ok,
                "cgroup": observed.get("cgroup"),
                "same_unit_cgroup": bool(
                    observed.get("process_present")
                    and control_group
                    and observed.get("cgroup") == control_group
                ),
            }
        )
    return inventory


def _port_owner() -> dict[str, Any]:
    result = _readonly_run(["ss", "-ltnp"])
    matching_lines = [
        line for line in result.stdout.splitlines()
        if f"{PRODUCTION_HOST}:{PRODUCTION_PORT}" in line
    ]
    owner_pids = sorted(
        {
            int(pid)
            for line in matching_lines
            for pid in re.findall(r"pid=(\d+)", line)
        }
    )
    return {
        "command_returncode": result.returncode,
        "matching_listener_count": len(matching_lines),
        "owner_pids": owner_pids,
        "raw_listener_lines": matching_lines,
    }


def _source_facts() -> dict[str, Any]:
    handover_path = CANONICAL_ROOT / "services" / "agentd" / "handover.py"
    supervisor_path = CANONICAL_ROOT / "services" / "agentd" / "supervisor.py"
    handover_source = handover_path.read_text(encoding="utf-8")
    supervisor_source = supervisor_path.read_text(encoding="utf-8")

    protocol_match = re.search(r"^\s*PROTOCOL_VERSION\s*=\s*(\d+)", handover_source, re.MULTILINE)
    constants = {}
    for name in ("WORKER_IO_THREADS", "WORKER_IO_RESERVED_SLOTS", "WORKER_IO_SLOTS_PER_WORKER"):
        match = re.search(rf"^\s*{name}\s*=\s*(\d+)", supervisor_source, re.MULTILINE)
        constants[name] = int(match.group(1)) if match else None
    return {
        "paths": {
            "handover": str(handover_path),
            "supervisor": str(supervisor_path),
        },
        "sha256": {
            "handover": hashlib.sha256(handover_path.read_bytes()).hexdigest(),
            "supervisor": hashlib.sha256(supervisor_path.read_bytes()).hexdigest(),
        },
        "protocol_version": int(protocol_match.group(1)) if protocol_match else None,
        "worker_io": constants,
    }


def _handover_probe(main_pid: int) -> dict[str, Any]:
    environment = os.environ.copy()
    pythonpath = [str(CANONICAL_ROOT), str(CANONICAL_ROOT / "src")]
    if environment.get("PYTHONPATH"):
        pythonpath.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-m",
                "services.agentd.handover",
                "--mode",
                "probe",
                "--root",
                str(STATE_ROOT),
                "--agentd-pid",
                str(main_pid),
            ],
            cwd=str(CANONICAL_ROOT),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"handover probe failed: {exc}") from exc
    if result.returncode != 0:
        raise PreflightError(result.stderr.strip() or "handover probe returned non-zero")
    try:
        manifest = json.loads(result.stdout)
    except ValueError as exc:
        raise PreflightError(f"handover probe output is not JSON: {exc}") from exc

    mappings: list[dict[str, Any]] = []
    complete = True
    for worker in manifest.get("workers", []):
        for channel in ("stdout", "stderr"):
            info = worker.get(channel) or {}
            mapping = {
                "agent_id": worker.get("agent_id"),
                "pid": worker.get("pid"),
                "state": worker.get("state"),
                "channel": channel,
                "pipe_inode": info.get("pipe_inode"),
                "old_agentd_fd": info.get("old_agentd_fd"),
                "duplicate_verified": bool(info.get("duplicate_verified")),
            }
            mappings.append(mapping)
            complete = complete and bool(
                mapping["pipe_inode"]
                and mapping["old_agentd_fd"]
                and mapping["duplicate_verified"]
            )
    return {
        "manifest_version": manifest.get("manifest_version"),
        "manifest_id": manifest.get("manifest_id"),
        "persisted_state_candidate_count": manifest.get("persisted_state_candidate_count"),
        "live_process_candidate_count": manifest.get("live_process_candidate_count"),
        "omitted_persisted_candidates": manifest.get("omitted_persisted_candidates", []),
        "worker_count": len(manifest.get("workers", [])),
        "stream_count": manifest.get("stream_count"),
        "mapping_count": len(mappings),
        "mapping_complete": complete and len(mappings) == 20,
        "mappings": mappings,
    }


def _future_dropin(old_pid: int) -> str:
    exec_start = (
        "/usr/bin/python3 -m services.agentd "
        f"--root {CANONICAL_ROOT / 'var' / 'agentd'} "
        f"--host {PRODUCTION_HOST} --port {PRODUCTION_PORT} "
        f"--handover-socket {PLANNED_HANDOVER_SOCKET} "
        f"--old-agentd-pid {old_pid}"
    )
    return "\n".join(
        [
            "[Service]",
            "Restart=no",
            "KillMode=process",
            "ExecStart=",
            f"ExecStart={exec_start}",
        ]
    )


def _capacity_facts(source: dict[str, Any], live_count: int) -> dict[str, Any]:
    io = source["worker_io"]
    threads = io.get("WORKER_IO_THREADS")
    reserve = io.get("WORKER_IO_RESERVED_SLOTS")
    slots = io.get("WORKER_IO_SLOTS_PER_WORKER")
    safe_capacity = (
        (threads - reserve) // slots
        if all(isinstance(value, int) and value > 0 for value in (threads, slots))
        and isinstance(reserve, int)
        else None
    )
    return {
        "worker_io_threads": threads,
        "worker_io_reserved_slots": reserve,
        "worker_io_slots_per_worker": slots,
        "worker_io_safe_live_capacity": safe_capacity,
        "worker_io_live_handles": live_count,
        "worker_io_expected_persistent_slots": live_count * slots if isinstance(slots, int) else None,
    }


def _preflight(expected_old_pid: int) -> int:
    errors: list[str] = []
    service = _systemd_properties()
    main_pid = int(service.get("MainPID", "0") or 0)
    main_process = _proc_identity(main_pid) if main_pid else {"process_present": False}
    control_group = service.get("ControlGroup", "")
    inventory = _worker_inventory(main_pid, control_group)
    live_workers = [item for item in inventory if item["identity_ok"]]
    source = _source_facts()
    capacity = _capacity_facts(source, len(live_workers))
    port = _port_owner()
    probe = None
    if main_pid == expected_old_pid:
        probe = _handover_probe(main_pid)
    else:
        errors.append(f"systemd MainPID {main_pid} != expected old PID {expected_old_pid}")

    if service.get("ActiveState") != "active" or service.get("SubState") != "running":
        errors.append(
            f"service not active/running: {service.get('ActiveState')}/{service.get('SubState')}"
        )
    if service.get("Restart") != "on-failure":
        errors.append(f"unexpected Restart={service.get('Restart')!r}")
    if service.get("KillMode") != "control-group":
        errors.append(f"unexpected KillMode={service.get('KillMode')!r}")
    exec_start = service.get("ExecStart", "")
    if "services.agentd" not in exec_start or "--port 8787" not in exec_start:
        errors.append("effective ExecStart is not the canonical production agentd command")
    if "--handover-socket" in exec_start or "--old-agentd-pid" in exec_start:
        errors.append("effective production ExecStart already contains handover arguments")
    if service.get("User") != SERVICE_USER:
        errors.append(f"unexpected service User={service.get('User')!r}")
    if RUNTIME_DROPIN.exists():
        errors.append(f"stale runtime drop-in exists: {RUNTIME_DROPIN}")
    if len(live_workers) != EXPECTED_LIVE_WORKERS:
        errors.append(f"live persisted worker count {len(live_workers)} != {EXPECTED_LIVE_WORKERS}")
    for worker in live_workers:
        if not worker["same_unit_cgroup"]:
            errors.append(f"live worker is outside agentd cgroup: {worker['agent_id']}/{worker['pid']}")
    if port["matching_listener_count"] != 1 or port["owner_pids"] != [main_pid]:
        errors.append(
            f"8787 listener mismatch: count={port['matching_listener_count']} owners={port['owner_pids']}"
        )
    if source["protocol_version"] != 2:
        errors.append(f"handover protocol version is {source['protocol_version']!r}, expected 2")
    io = source["worker_io"]
    if io.get("WORKER_IO_THREADS") != 128 or io.get("WORKER_IO_RESERVED_SLOTS") != 8:
        errors.append(f"unexpected worker IO constants: {io}")
    if capacity["worker_io_safe_live_capacity"] is None or capacity["worker_io_safe_live_capacity"] < len(live_workers):
        errors.append(f"worker IO capacity insufficient: {capacity}")
    if probe is not None:
        if probe["manifest_version"] != 2:
            errors.append(f"probe protocol version is {probe['manifest_version']!r}")
        if probe["worker_count"] != EXPECTED_LIVE_WORKERS:
            errors.append(f"handover probe worker count {probe['worker_count']} != {EXPECTED_LIVE_WORKERS}")
        if probe["stream_count"] != 20 or probe["mapping_count"] != 20 or not probe["mapping_complete"]:
            errors.append(f"handover probe mapping incomplete: {probe}")
    result = {
        "status": "PASS" if not errors else "STOP",
        "mode": "preflight",
        "project": "paidproxy-otomasyon-main",
        "canonical_root": str(CANONICAL_ROOT),
        "state_root": str(STATE_ROOT),
        "unit": UNIT_NAME,
        "service_user": SERVICE_USER,
        "expected_old_pid": expected_old_pid,
        "mutation_performed": False,
        "daemon_reload": False,
        "runtime_dropin_written": False,
        "broker_serve_started": False,
        "old_main_signalled": False,
        "service_start_stop_restart": False,
        "systemd_mutation": False,
        "unit_properties": service,
        "main_process": {
            "pid": main_pid,
            "identity": main_process,
            "control_group": control_group,
        },
        "workers": inventory,
        "live_worker_count": len(live_workers),
        "source": source,
        "capacity": capacity,
        "production_port": port,
        "handover_probe": probe,
        "runtime_dropin_path": str(RUNTIME_DROPIN),
        "runtime_dropin_exists": RUNTIME_DROPIN.exists(),
        "future_dropin_rendered": _future_dropin(expected_old_pid),
        "future_transaction_states": [
            "BASELINE_VALIDATED",
            "BROKER_READY",
            "RUNTIME_OVERRIDE_LOADED",
            "OLD_MAIN_TERMINATED",
            "WORKERS_PRESERVED",
            "NEW_MAIN_STARTED",
            "HANDOVER_COMMITTED",
            "PRODUCTION_8787_READY",
            "ACCEPTANCE_PENDING",
            "FINALIZED",
        ],
        "errors": errors,
        "no_mutation_guarantee": [
            "preflight reads only systemd/proc/ss/source and runs the existing zero-read handover probe",
            "no file under /run/systemd was written",
            "no cutover journal was created",
            "no broker was started",
            "no service-manager action was invoked",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="PaidProxy agentd cutover preflight")
    parser.add_argument("mode", choices=("preflight",))
    parser.add_argument("--expected-old-pid", type=int, default=63887)
    args = parser.parse_args()
    if str(args.mode) != "preflight":
        raise PreflightError("only preflight is implemented")
    try:
        return _preflight(args.expected_old_pid)
    except (PreflightError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "STOP",
                    "mode": "preflight",
                    "mutation_performed": False,
                    "systemd_mutation": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

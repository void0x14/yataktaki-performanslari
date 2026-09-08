"""VDS headless Sway kanıt yüzeyi ve gerçek ekran capture yardımcıları.

Sway, wayvnc ve terminal yüzeyi VDS'de tek bir kalıcı oturum olarak yaşar.
Worker yalnız mevcut ajan olayını yüzeye yazar ve grim ile aynı Wayland
çıktısından still capture alır. Grafik yığını yoksa bu modül sahte görüntü
üretmez.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4


_STOP = False
_LAST_CAPTURE_AT = 0.0
_CAPTURE_ACK_TIMEOUT_SECONDS = 2.0
_AGENT_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def capture_settings() -> dict[str, Any]:
    values: dict[str, Any] = {}
    config_path = _repo_root() / "config" / "defaults.toml"
    try:
        import tomllib
        values = dict((tomllib.loads(config_path.read_text(encoding="utf-8")).get("evidence") or {}))
    except (ImportError, OSError, ValueError):
        pass

    def read(env_name: str, key: str, default: Any, convert: Any) -> Any:
        raw = os.environ.get(env_name, values.get(key, default))
        try:
            return convert(raw)
        except (TypeError, ValueError):
            return convert(default)

    output = str(os.environ.get("PAIDPROXY_HEADLESS_OUTPUT", values.get("headless_output", "HEADLESS-1")))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", output):
        output = "HEADLESS-1"
    return {
        "headless_width": max(640, read("PAIDPROXY_HEADLESS_WIDTH", "headless_width", 1280, int)),
        "headless_height": max(360, read("PAIDPROXY_HEADLESS_HEIGHT", "headless_height", 720, int)),
        "headless_output": output,
        "frame_interval_seconds": max(
            0.1,
            read("PAIDPROXY_FRAME_INTERVAL_SECONDS", "frame_interval_seconds", 2.0, float),
        ),
        "frame_retention": max(1, read("PAIDPROXY_FRAME_RETENTION", "frame_retention", 240, int)),
        "video_segment_seconds": max(
            5.0,
            read("PAIDPROXY_VIDEO_SEGMENT_SECONDS", "video_segment_seconds", 30.0, float),
        ),
        "video_retention": max(1, read("PAIDPROXY_VIDEO_RETENTION", "video_retention", 8, int)),
        "video_fairness_cooldown_seconds": max(
            0.0,
            read("PAIDPROXY_VIDEO_FAIRNESS_COOLDOWN_SECONDS", "video_fairness_cooldown_seconds", 1.0, float),
        ),
        "capture_queue_timeout_seconds": max(
            0.0,
            read("PAIDPROXY_CAPTURE_QUEUE_TIMEOUT_SECONDS", "capture_queue_timeout_seconds", 0.2, float),
        ),
        "operator_view_lease_seconds": max(
            10.0,
            read("PAIDPROXY_OPERATOR_VIEW_LEASE_SECONDS", "operator_view_lease_seconds", 90.0, float),
        ),
        "evidence_control_timeout_seconds": max(
            5.0,
            read("PAIDPROXY_EVIDENCE_CONTROL_TIMEOUT_SECONDS", "evidence_control_timeout_seconds", 20.0, float),
        ),
        "still_capture_queue_limit": max(
            1,
            min(1000, read("PAIDPROXY_STILL_CAPTURE_QUEUE_LIMIT", "still_capture_queue_limit", 128, int)),
        ),
        "wayvnc_loopback_port": max(
            1,
            min(65535, read("PAIDPROXY_WAYVNC_LOOPBACK_PORT", "wayvnc_loopback_port", 5900, int)),
        ),
        "wayland_display": str(
            os.environ.get("PAIDPROXY_WAYLAND_DISPLAY", values.get("wayland_display", "paidproxy-wayland"))
        ),
        "runtime_dir": str(
            os.environ.get("PAIDPROXY_WAYLAND_RUNTIME_DIR", values.get("runtime_dir", "/run/paidproxy-wayland"))
        ),
        "surface_refresh_seconds": max(
            0.2,
            read("PAIDPROXY_SURFACE_REFRESH_SECONDS", "surface_refresh_seconds", 0.5, float),
        ),
        "surface_render_settle_seconds": max(
            0.05,
            read("PAIDPROXY_SURFACE_RENDER_SETTLE_SECONDS", "surface_render_settle_seconds", 0.25, float),
        ),
        "surface_program": str(values.get("surface_program", "foot")),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def capability_path(root: Path) -> Path:
    return Path(root).resolve() / "display-capability.json"


def read_capability(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(capability_path(root).read_text(encoding="utf-8"))
        capability = dict(payload) if isinstance(payload, dict) else {}
        heartbeat = capability.get("heartbeat_at")
        if capability.get("ready"):
            stale = True
            if heartbeat:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(str(heartbeat))
                    stale = age.total_seconds() > 5.0
                except ValueError:
                    stale = True
            if stale:
                for key in (
                    "ready",
                    "sway_running",
                    "wayland_socket",
                    "wayvnc_running",
                    "wayvnc_loopback_ready",
                    "surface_running",
                    "surface_available",
                    "real_frame_available",
                    "video_capture_available",
                ):
                    capability[key] = False
                capability["reason"] = "evidence service heartbeat stale"
        return capability
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {
            "capture_kind": "sway-headless",
            "headless": True,
            "ready": False,
            "reason": "paidproxy-evidence.service capability kaydı yok",
        }


def _safe_agent_dir(root: Path, agent_id: str) -> Path:
    if not _AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError("agent id contains unsafe characters")
    return Path(root).resolve() / "agents" / agent_id


def _control_dir(root: Path) -> Path:
    path = Path(root).resolve() / "display-control"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _video_owner_path(root: Path) -> Path:
    return _control_dir(root) / "video-owner.json"


def _pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def read_video_owner(root: Path) -> dict[str, Any] | None:
    owner = _read_json(_video_owner_path(root))
    if not owner:
        return None
    if _pid_is_alive(owner.get("pid")):
        try:
            if float(owner.get("expires_at", 0.0) or 0.0) <= time.time():
                owner["lease_expired"] = True
        except (TypeError, ValueError):
            owner["lease_expired"] = True
        return owner
    try:
        _video_owner_path(root).unlink()
    except OSError:
        pass
    return None


def _video_request_path(root: Path, agent_id: str) -> Path:
    return _control_dir(root) / f"video-request-{agent_id}.json"


def _video_result_path(root: Path, agent_id: str) -> Path:
    return _control_dir(root) / f"video-result-{agent_id}.json"
def _video_result_request_path(root: Path, agent_id: str, request_id: str) -> Path:
    if not _AGENT_ID_RE.fullmatch(agent_id) or not re.fullmatch(r"[A-Za-z0-9._-]+", request_id):
        raise ValueError("video result identity contains unsafe characters")
    return _control_dir(root) / f"video-result-{agent_id}-{request_id}.json"
def _video_suppression_path(root: Path, agent_id: str) -> Path:
    return _control_dir(root) / f"video-suppressed-{agent_id}.json"


def _suppress_video_demand(root: Path, agent_id: str, reason: str) -> None:
    _atomic_json(
        _video_suppression_path(root, agent_id),
        {"agent_id": agent_id, "reason": reason, "created_at": utc_now()},
    )


def _clear_video_suppression(root: Path, agent_id: str) -> None:
    try:
        _video_suppression_path(root, agent_id).unlink()
    except OSError:
        pass


def _video_demand_suppressed(root: Path, agent_id: str) -> bool:
    return _video_suppression_path(root, agent_id).is_file()


def _service_rearm_video_request(root: Path, request: dict[str, Any]) -> None:
    agent_id = str(request.get("agent_id", "")).strip()
    pid = request.get("pid")
    if not agent_id or not _pid_is_alive(pid) or _video_demand_suppressed(root, agent_id):
        return
    path = _video_request_path(root, agent_id)
    existing = _read_json(path)
    if existing and existing.get("status", "pending") == "pending":
        return
    _atomic_json(
        path,
        {
            "request_id": uuid4().hex,
            "agent_id": agent_id,
            "pid": int(pid),
            "requested_at": time.time(),
            "requested_at_iso": utc_now(),
            "status": "pending",
            "source": "evidence_service_rotation",
        },
    )
def restore_video_demand(root: Path, agent_id: str, worker_pid: int) -> str:
    _safe_agent_dir(root, agent_id)
    pid = int(worker_pid)
    if not _pid_is_alive(pid):
        raise RuntimeError(f"worker PID is not alive: {pid}")
    _clear_video_suppression(root, agent_id)
    path = _video_request_path(root, agent_id)
    existing = _read_json(path)
    if existing and existing.get("status", "pending") == "pending":
        return str(existing.get("request_id"))
    request_id = uuid4().hex
    _atomic_json(
        path,
        {
            "request_id": request_id,
            "agent_id": agent_id,
            "pid": pid,
            "requested_at": time.time(),
            "requested_at_iso": utc_now(),
            "status": "pending",
            "source": "supervisor_resume",
        },
    )
    return request_id


def request_video_lease(root: Path, agent_id: str) -> str:
    _safe_agent_dir(root, agent_id)
    _clear_video_suppression(root, agent_id)
    path = _video_request_path(root, agent_id)
    existing = _read_json(path)
    if existing and existing.get("status", "pending") == "pending":
        return str(existing.get("request_id"))
    request_id = uuid4().hex
    _atomic_json(
        path,
        {
            "request_id": request_id,
            "agent_id": agent_id,
            "pid": os.getpid(),
            "requested_at": time.time(),
            "requested_at_iso": utc_now(),
            "status": "pending",
        },
    )
    return request_id


def poll_video_lease(root: Path, agent_id: str, request_id: str) -> dict[str, Any] | None:
    try:
        request_result = _read_json(_video_result_request_path(root, agent_id, request_id))
    except ValueError:
        request_result = None
    if request_result and request_result.get("request_id") == request_id:
        return request_result
    result = _read_json(_video_result_path(root, agent_id))
    if result and result.get("request_id") == request_id:
        return result
    return None


def consume_video_lease_result(root: Path, agent_id: str, request_id: str) -> None:
    try:
        _video_result_request_path(root, agent_id, request_id).unlink()
    except (OSError, ValueError):
        pass
    path = _video_result_path(root, agent_id)
    result = _read_json(path)
    if result and result.get("request_id") == request_id:
        try:
            path.unlink()
        except OSError:
            pass


def _video_requests(root: Path) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for path in _control_dir(root).glob("video-request-*.json"):
        request = _read_json(path)
        if not request or request.get("status", "pending") != "pending":
            continue
        agent_id = str(request.get("agent_id", "")).strip()
        if not agent_id:
            continue
        try:
            _safe_agent_dir(root, agent_id)
        except ValueError:
            continue
        requests.append(request)
    return sorted(requests, key=lambda item: float(item.get("requested_at", 0.0) or 0.0))


def _operator_request_path(root: Path) -> Path:
    return _control_dir(root) / "operator-display-request.json"


def _operator_ack_path(root: Path, request_id: str) -> Path:
    return _control_dir(root) / f"operator-display-ack-{request_id}.json"


def _still_capture_dir(root: Path) -> Path:
    path = _control_dir(root) / "still-captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _completion_dir(root: Path) -> Path:
    path = _control_dir(root) / "completions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_completion(root: Path, event_type: str, **fields: Any) -> dict[str, Any]:
    completion_id = uuid4().hex
    record = {
        "completion_id": completion_id,
        "event_type": event_type,
        "created_at": utc_now(),
        **fields,
    }
    _atomic_json(_completion_dir(root) / f"completion-{completion_id}.json", record)
    return record


def read_evidence_completion(root: Path, completion_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(completion_id)):
        return None
    return _read_json(_completion_dir(root) / f"completion-{completion_id}.json")


def read_evidence_completions(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    directory = _completion_dir(root)
    for path in sorted(directory.glob("completion-*.json")):
        record = _read_json(path)
        completion_id = str((record or {}).get("completion_id", "")).strip()
        if not record or not completion_id:
            continue
        if (directory / f"consumed-{completion_id}.json").exists():
            continue
        records.append(record)
    return sorted(records, key=lambda item: str(item.get("created_at", "")))


def ack_evidence_completion(root: Path, completion_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(completion_id)):
        return
    _atomic_json(
        _completion_dir(root) / f"consumed-{completion_id}.json",
        {"completion_id": completion_id, "consumed_at": utc_now()},
    )


def _operator_selection(root: Path) -> dict[str, Any] | None:
    path = _control_dir(root) / "operator-selection.json"
    selection = _read_json(path)
    if not selection:
        return None
    try:
        if float(selection.get("expires_at", 0.0) or 0.0) <= time.time():
            path.unlink()
            return None
    except (OSError, TypeError, ValueError):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return selection


def _video_selection(root: Path) -> dict[str, Any] | None:
    return _read_json(_control_dir(root) / "video-selection.json")


def read_display_state(root: Path) -> dict[str, Any]:
    control_dir = _control_dir(root)
    operator = _operator_selection(root)
    active_capture = _read_json(control_dir / "capture-request.json")
    queued_capture = next(iter(sorted(_still_capture_dir(root).glob("still-request-*.json"))), None)
    queued_payload = _read_json(queued_capture) if queued_capture else None
    video_lease = read_video_owner(root)
    return {
        "operator_selected_agent": (operator or {}).get("selected_agent_id"),
        "operator_selection": operator,
        "pending_operator_selection": _read_json(_operator_request_path(root)),
        "capture_request_agent": (active_capture or queued_payload or {}).get("agent_id"),
        "video_lease_agent": (video_lease or {}).get("agent_id"),
        "video_lease": video_lease,
        "video_selected_agent": (_video_selection(root) or {}).get("selected_agent_id"),
    }


def reserve_video_owner(root: Path, agent_id: str, request_id: str, duration_seconds: float) -> dict[str, Any]:
    owner = read_video_owner(root)
    if owner and owner.get("agent_id") != agent_id:
        raise RuntimeError(f"video surface reserved by agent {owner.get('agent_id')}")
    payload = {
        "agent_id": agent_id,
        "request_id": request_id,
        "pid": os.getpid(),
        "state": "starting",
        "claimed_at": time.time(),
        "expires_at": time.time() + max(5.0, float(duration_seconds)),
    }
    _atomic_json(_video_owner_path(root), payload)
    return payload


def claim_video_owner(root: Path, agent_id: str, video_ref: str, duration_seconds: float) -> dict[str, Any]:
    owner = read_video_owner(root)
    if owner and owner.get("agent_id") != agent_id:
        raise RuntimeError(f"video surface reserved by agent {owner.get('agent_id')}")
    payload = {
        "agent_id": agent_id,
        "request_id": owner.get("request_id") if owner and owner.get("agent_id") == agent_id else None,
        "video_ref": video_ref,
        "pid": os.getpid(),
        "state": "active",
        "claimed_at": time.time(),
        "expires_at": time.time() + max(5.0, float(duration_seconds)),
    }
    _atomic_json(_video_owner_path(root), payload)
    return payload


def clear_video_owner(root: Path, agent_id: str) -> None:
    owner = read_video_owner(root)
    if owner and owner.get("agent_id") == agent_id and owner.get("pid") == os.getpid():
        try:
            _video_owner_path(root).unlink()
        except OSError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def select_display_agent(
    root: Path,
    agent_id: str | None,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    cleaned = str(agent_id or "").strip()
    if cleaned and not _AGENT_ID_RE.fullmatch(cleaned):
        raise ValueError("agent id contains unsafe characters")
    settings = capture_settings()
    request_id = uuid4().hex
    selection_id = uuid4().hex
    request = {
        "request_id": request_id,
        "selection_id": selection_id,
        "selected_agent_id": cleaned or None,
        "requested_at": utc_now(),
        "lease_seconds": settings["operator_view_lease_seconds"],
    }
    _atomic_json(_operator_request_path(root), request)
    deadline = time.monotonic() + float(
        timeout_seconds
        if timeout_seconds is not None
        else settings["evidence_control_timeout_seconds"]
    )
    ack_path = _operator_ack_path(root, request_id)
    while time.monotonic() < deadline:
        ack = _read_json(ack_path)
        if ack and ack.get("request_id") == request_id:
            if ack.get("status") == "rejected":
                try:
                    ack_path.unlink()
                except OSError:
                    pass
                raise RuntimeError(str(ack.get("error") or "operator display selection rejected"))
            result = dict(request)
            result.update(ack)
            try:
                ack_path.unlink()
            except OSError:
                pass
            return result
        time.sleep(0.1)
    raise TimeoutError("operator display selection acknowledgement timeout")


def request_video_revoke(root: Path, agent_id: str, reason: str) -> dict[str, Any]:
    owner = read_video_owner(root)
    request_path = _video_request_path(root, agent_id)
    if not owner or owner.get("agent_id") != agent_id:
        pending = _read_json(request_path)
        if pending and pending.get("status", "pending") == "pending":
            _write_video_result(
                root,
                pending,
                "cancelled",
                error="video lease operator müdahalesiyle iptal edildi",
                reason=reason,
            )
            _suppress_video_demand(root, agent_id, reason)
            return {"status": "cancelled", "agent_id": agent_id, "reason": reason}
        _suppress_video_demand(root, agent_id, reason)
        return {"status": "not_owned", "agent_id": agent_id, "reason": reason}
    _suppress_video_demand(root, agent_id, reason)
    control_dir = _control_dir(root)
    request_id = uuid4().hex
    revoke_path = control_dir / "video-revoke-request.json"
    ack_path = control_dir / f"video-revoke-ack-{request_id}.json"
    _atomic_json(
        revoke_path,
        {
            "request_id": request_id,
            "agent_id": agent_id,
            "reason": reason,
            "requested_at": utc_now(),
        },
    )
    deadline = time.monotonic() + capture_settings()["evidence_control_timeout_seconds"]
    while time.monotonic() < deadline:
        ack = _read_json(ack_path)
        if ack and ack.get("request_id") == request_id:
            try:
                ack_path.unlink()
            except OSError:
                pass
            return ack
        time.sleep(0.1)
    raise TimeoutError("video lease revoke acknowledgement timeout")


def _render_sway_config(runtime_dir: Path, settings: dict[str, Any]) -> Path:
    template_path = _repo_root() / "config" / "sway" / "paidproxy-headless.conf"
    template = template_path.read_text(encoding="utf-8")
    rendered = (
        template.replace("@HEADLESS_OUTPUT@", str(settings["headless_output"]))
        .replace("@HEADLESS_WIDTH@", str(settings["headless_width"]))
        .replace("@HEADLESS_HEIGHT@", str(settings["headless_height"]))
    )
    rendered_path = runtime_dir / "paidproxy-headless.conf"
    rendered_path.write_text(rendered, encoding="utf-8")
    try:
        os.chmod(rendered_path, 0o600)
    except OSError:
        pass
    return rendered_path


def _load_agent_view(root: Path, agent_id: str) -> dict[str, Any] | None:
    try:
        return _read_json(_safe_agent_dir(root, agent_id) / "current-view.json")
    except ValueError:
        return None


def _render_capture_request(root: Path, agent_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    control_dir = _control_dir(root)
    request_path = control_dir / "capture-request.json"
    event_id = str(payload.get("event_id") or uuid4().hex)
    render_revision = str(payload.get("render_revision") or event_id)
    payload["event_id"] = event_id
    payload["render_revision"] = render_revision
    request_id = uuid4().hex
    ack_path = control_dir / f"capture-ack-{request_id}.json"
    view = _load_agent_view(root, agent_id) or dict(payload)
    request = {
        "request_id": request_id,
        "agent_id": agent_id,
        "event_id": event_id,
        "render_revision": render_revision,
        "requested_at": utc_now(),
        "view": view,
    }
    try:
        _atomic_json(request_path, request)
        deadline = time.monotonic() + _CAPTURE_ACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            ack = _read_json(ack_path)
            if (
                ack
                and ack.get("request_id") == request_id
                and ack.get("agent_id") == agent_id
                and ack.get("event_id") == event_id
                and ack.get("render_revision") == render_revision
            ):
                return ack, None
            time.sleep(0.1)
        return None, "Sway evidence surface render acknowledgement timeout"
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"[:500]


def _capture_grim(
    root: Path,
    agent_id: str,
    payload: dict[str, Any],
    grim: str,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    control_dir = _control_dir(root)
    lock_path = control_dir / "capture.lock"
    request_path = control_dir / "capture-request.json"
    ack_path: Path | None = None
    owner = read_video_owner(root)
    if owner and (owner.get("agent_id") != agent_id or owner.get("lease_expired")):
        return None, None, "başka ajanın bounded video lease'i aktif; frame capture sıraya alındı"
    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            deadline = time.monotonic() + capture_settings()["capture_queue_timeout_seconds"]
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return None, None, "capture scheduler busy; this event remains in the durable event stream"
                    time.sleep(0.02)
            try:
                acknowledgement, render_error = _render_capture_request(root, agent_id, payload)
                request = _read_json(request_path) or {}
                request_id = str((acknowledgement or request).get("request_id", "")).strip()
                if request_id:
                    ack_path = control_dir / f"capture-ack-{request_id}.json"
                if render_error:
                    return None, None, render_error
                environment, socket_path, _settings = _wayland_environment(root)
                if not socket_path.exists():
                    return None, None, f"Wayland socket bulunamadı: {socket_path.name}"
                agent_dir = _safe_agent_dir(root, agent_id)
                frames_dir = agent_dir / "frames"
                frames_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
                frame_path = frames_dir / f"frame-{stamp}-{os.getpid()}.png"
                completed = subprocess.run(
                    [grim, "-t", "png", str(frame_path)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if completed.returncode != 0 or not frame_path.is_file():
                    try:
                        frame_path.unlink()
                    except OSError:
                        pass
                    return None, None, (completed.stderr or "grim gerçek Sway çıktısını yakalayamadı").strip()[:500]
                return frame_path, acknowledgement, None
            finally:
                try:
                    request_path.unlink()
                except OSError:
                    pass
                if ack_path is not None:
                    try:
                        ack_path.unlink()
                    except OSError:
                        pass
    finally:
        pass


def wait_for_display_render(root: Path, agent_id: str) -> str | None:
    control_dir = _control_dir(root)
    lock_path = control_dir / "capture.lock"
    request_path = control_dir / "capture-request.json"
    with lock_path.open("a+", encoding="utf-8") as lock:
        deadline = time.monotonic() + capture_settings()["capture_queue_timeout_seconds"]
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return "capture scheduler busy; display render deferred"
                time.sleep(0.02)
        payload = _load_agent_view(root, agent_id) or {
            "agent_id": agent_id,
            "event_type": "display_selection_pending",
            "working_note": "Seçilen ajanın ilk gerçek olayı bekleniyor.",
        }
        payload["event_id"] = f"display-selection-{uuid4().hex}"
        payload["render_revision"] = payload["event_id"]
        acknowledgement, render_error = _render_capture_request(root, agent_id, payload)
        request = _read_json(request_path) or {}
        request_id = str((acknowledgement or request).get("request_id", "")).strip()
        try:
            return render_error
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass
            if request_id:
                try:
                    (control_dir / f"capture-ack-{request_id}.json").unlink()
                except OSError:
                    pass
                    pass


def write_current_view(root: Path, agent_id: str, payload: dict[str, Any]) -> str:
    agent_dir = _safe_agent_dir(root, agent_id)
    view = dict(payload)
    view["agent_id"] = agent_id
    view["capture_kind"] = "sway-headless"
    view["updated_at"] = utc_now()
    try:
        manifest = json.loads((agent_dir / "manifest.json").read_text(encoding="utf-8"))
        view["pet_name"] = str((manifest.get("pet") or {}).get("name", "adsız-yoldaş"))
    except (OSError, json.JSONDecodeError, AttributeError):
        view["pet_name"] = "adsız-yoldaş"
    path = agent_dir / "current-view.json"
    _atomic_json(path, view)
    return f"agent://{agent_id}/current-view.json"


def _wayland_environment(root: Path | None = None) -> tuple[dict[str, str], Path, dict[str, Any]]:
    settings = capture_settings()
    environment = os.environ.copy()
    runtime_dir = Path(settings["runtime_dir"]).expanduser()
    display = str(settings["wayland_display"])
    if root is not None:
        capability = read_capability(root)
        discovered = str(capability.get("wayland_display", "")).strip()
        if (
            re.fullmatch(r"[A-Za-z0-9._-]+", discovered)
            and (runtime_dir / discovered).is_socket()
        ):
            display = discovered
    environment["XDG_RUNTIME_DIR"] = str(runtime_dir)
    environment["WAYLAND_DISPLAY"] = display
    return environment, runtime_dir / display, settings


def _capture_frame_artifact(
    root: Path,
    agent_id: str,
    payload: dict[str, Any],
    frame_path: Path,
    acknowledgement: dict[str, Any] | None,
    capability: dict[str, Any],
) -> tuple[str, str]:
    os.chmod(frame_path, 0o600)
    frame_ref = f"agent://{agent_id}/frames/{frame_path.name}"
    provenance_ref = f"agent://{agent_id}/frames/{frame_path.with_suffix('.json').name}"
    event_id = str(payload.get("event_id") or uuid4().hex)
    render_revision = str(payload.get("render_revision") or event_id)
    _atomic_json(
        frame_path.with_suffix(".json"),
        {
            "frame_ref": frame_ref,
            "provenance_ref": provenance_ref,
            "agent_id": agent_id,
            "event_id": event_id,
            "render_revision": render_revision,
            "acknowledged_at": (acknowledgement or {}).get("acknowledged_at"),
            "captured_at": utc_now(),
            "capture_kind": "sway-headless",
            "display_capability": capability,
        },
    )
    settings = capture_settings()
    old_frames = sorted(frame_path.parent.glob("frame-*.png"))
    for old in old_frames[:-settings["frame_retention"]]:
        try:
            old.unlink()
        except OSError:
            pass
        try:
            old.with_suffix(".json").unlink()
        except OSError:
            pass
    return frame_ref, provenance_ref


def capture_event(root: Path, agent_id: str, payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Worker olayını günceller ve gerçek capture için evidence-service kuyruğuna bırakır."""
    global _LAST_CAPTURE_AT
    root = Path(root).resolve()
    event_id = str(payload.get("event_id") or uuid4().hex)
    render_revision = str(payload.get("render_revision") or event_id)
    payload["event_id"] = event_id
    payload["render_revision"] = render_revision
    write_current_view(root, agent_id, payload)
    now = time.monotonic()
    settings = capture_settings()
    if _LAST_CAPTURE_AT and now - _LAST_CAPTURE_AT < settings["frame_interval_seconds"]:
        return None, None
    capability = read_capability(root)
    if not capability.get("ready") or not capability.get("sway_running") or not capability.get("wayland_socket"):
        return None, str(capability.get("reason", "Sway headless capture hazır değil"))
    grim = shutil.which("grim")
    if not grim or not capability.get("grim_available"):
        return None, "grim VDS'de yok veya capability hazır değil"
    queue_dir = _still_capture_dir(root)
    queued = list(queue_dir.glob("still-request-*.json"))
    if len(queued) >= settings["still_capture_queue_limit"]:
        return None, "still capture kuyruğu dolu; olay kalıcı event akışında tutuldu"
    request_id = uuid4().hex
    view = _load_agent_view(root, agent_id) or dict(payload)
    _atomic_json(
        queue_dir / f"still-request-{request_id}.json",
        {
            "request_id": request_id,
            "agent_id": agent_id,
            "event_id": event_id,
            "render_revision": render_revision,
            "enqueued_at": utc_now(),
            "requested_at": time.time(),
            "pid": os.getpid(),
            "view": view,
            "payload": dict(payload),
        },
    )
    _LAST_CAPTURE_AT = now
    return None, None


def _service_capture_one(root: Path, settings: dict[str, Any]) -> None:
    requests = sorted(_still_capture_dir(root).glob("still-request-*.json"))
    if not requests:
        return
    operator_agent = str((_operator_selection(root) or {}).get("selected_agent_id") or "").strip()
    for request_path in requests:
        request = _read_json(request_path)
        if not request:
            continue
        if not _pid_is_alive(request.get("pid")):
            try:
                request_path.unlink()
            except OSError:
                pass
            continue
        agent_id = str(request.get("agent_id", "")).strip()
        if not agent_id or (operator_agent and agent_id != operator_agent):
            continue
        payload = dict(request.get("payload") or request.get("view") or {})
        payload["event_id"] = request.get("event_id") or payload.get("event_id") or uuid4().hex
        payload["render_revision"] = request.get("render_revision") or payload.get("render_revision") or payload["event_id"]
        grim = shutil.which("grim")
        if not grim:
            return
        frame_path, acknowledgement, capture_error = _capture_grim(root, agent_id, payload, grim)
        if capture_error or frame_path is None:
            attempts = int(request.get("attempts", 0) or 0) + 1
            if attempts >= 3 and "başka ajanın" not in str(capture_error):
                try:
                    request_path.unlink()
                except OSError:
                    pass
                _write_completion(
                    root,
                    "evidence_capture_unavailable",
                    agent_id=agent_id,
                    state="degraded",
                    tool="evidence_recorder",
                    target="vds://agent/evidence",
                    working_note="Gerçek Sway frame kuyruğu üç denemede tamamlanamadı; sahte frame üretilmedi.",
                    error=str(capture_error or "grim capture başarısız")[:500],
                    next_action="Sway/wayland/grim capability inspect",
                    capture_kind="sway-headless",
                )
            else:
                request["attempts"] = attempts
                _atomic_json(request_path, request)
            return
        capability = read_capability(root)
        frame_ref, provenance_ref = _capture_frame_artifact(
            root,
            agent_id,
            payload,
            frame_path,
            acknowledgement,
            capability,
        )
        _write_completion(
            root,
            "frame_captured",
            agent_id=agent_id,
            state="running",
            tool="evidence_recorder",
            target="vds://agent/evidence",
            working_note="Gerçek Sway headless yüzeyinden grim frame kuyruğu tamamlandı.",
            frame_ref=frame_ref,
            frame_provenance_ref=provenance_ref,
            frame_event_id=payload["event_id"],
            frame_render_revision=payload["render_revision"],
            evidence_refs=[frame_ref, provenance_ref],
            output_ref=frame_ref,
            capture_kind="sway-headless",
            display_capability=capability,
        )
        try:
            request_path.unlink()
        except OSError:
            pass
        return


def start_wf_recorder(root: Path, agent_id: str) -> tuple[subprocess.Popen[str], str] | None:
    capability = read_capability(root)
    if not capability.get("ready") or not capability.get("sway_running") or not capability.get("wayland_socket"):
        return None
    recorder = shutil.which("wf-recorder")
    if not recorder or not capability.get("wf_recorder_available"):
        return None
    environment, socket_path, settings = _wayland_environment(root)
    if not socket_path.exists():
        return None
    agent_dir = _safe_agent_dir(root, agent_id)
    video_dir = agent_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    old_videos = sorted(video_dir.glob("wf-*.mkv"))
    for old in old_videos[:-settings["video_retention"]]:
        try:
            old.unlink()
        except OSError:
            pass
        try:
            old.with_suffix(".json").unlink()
        except OSError:
            pass
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    video_path = video_dir / f"wf-{stamp}.mkv"
    process = subprocess.Popen(
        [recorder, "-f", str(video_path)],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, f"agent://{agent_id}/video/{video_path.name}"


def stop_wf_recorder(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _stop_wf_recorder_for_operator(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Bounded stop used only while handing the surface to the operator."""
    started = time.monotonic()
    stop_error: str | None = None

    def metadata(mode: str, graceful: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "mode": mode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "graceful": bool(graceful),
            "final_pid_dead": process.poll() is not None,
        }
        if stop_error:
            result["stop_error"] = stop_error
        return result

    if process.poll() is not None:
        return metadata("already_exited", True)
    for mode, signum, timeout, graceful in (
        ("sigint", signal.SIGINT, 3.0, True),
        ("terminate", signal.SIGTERM, 2.0, False),
        ("kill", signal.SIGKILL, 1.0, False),
    ):
        try:
            if signum == signal.SIGKILL:
                process.kill()
            else:
                process.send_signal(signum)
        except ProcessLookupError:
            return metadata("already_exited", True)
        except OSError as exc:
            stop_error = f"{type(exc).__name__}: {exc}"[:500]
            continue
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        return metadata(mode, graceful)
    return metadata("kill", False)


def finalize_wf_recorder(root: Path, agent_id: str, video_ref: str | None) -> tuple[str | None, str | None]:
    if not video_ref:
        return None, None
    prefix = f"agent://{agent_id}/video/"
    if not video_ref.startswith(prefix):
        return None, "wf-recorder ref ajan namespace dışına çıktı"
    try:
        path = _safe_agent_dir(root, agent_id) / "video" / video_ref[len(prefix):]
    except ValueError as exc:
        return None, str(exc)
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return None, "wf-recorder segmenti boş veya kapanmış dosya olarak bulunamadı"
        provenance_ref = f"agent://{agent_id}/video/{path.with_suffix('.json').name}"
        _atomic_json(
            path.with_suffix(".json"),
            {
                "video_ref": video_ref,
                "provenance_ref": provenance_ref,
                "agent_id": agent_id,
                "capture_kind": "sway-headless",
                "recording_state": "finalized",
                "finalized_at": utc_now(),
                "size_bytes": path.stat().st_size,
            },
        )
        return video_ref, None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"[:500]


def _video_provenance_ref(video_ref: str) -> str:
    return video_ref.rsplit("/", 1)[0] + "/" + Path(video_ref).with_suffix(".json").name


def _write_video_result(
    root: Path,
    request: dict[str, Any],
    status: str,
    *,
    video_ref: str | None = None,
    error: str | None = None,
    reason: str = "",
) -> None:
    agent_id = str(request.get("agent_id", "")).strip()
    if not agent_id:
        return
    result: dict[str, Any] = {
        "request_id": request.get("request_id"),
        "agent_id": agent_id,
        "status": status,
        "reason": reason,
        "finished_at": utc_now(),
    }
    if video_ref:
        result["video_ref"] = video_ref
        result["video_provenance_ref"] = _video_provenance_ref(video_ref)
    if error:
        result["error"] = error
    request_id = str(request.get("request_id", "")).strip()
    if request_id:
        try:
            _atomic_json(_video_result_request_path(root, agent_id, request_id), result)
        except ValueError:
            pass
    _atomic_json(_video_result_path(root, agent_id), result)
    request_path = _video_request_path(root, agent_id)
    current = _read_json(request_path)
    if current and current.get("request_id") == request.get("request_id"):
        current["status"] = status
        current["result"] = result
        _atomic_json(request_path, current)


def _clear_video_selection(root: Path, agent_id: str | None = None) -> None:
    path = _control_dir(root) / "video-selection.json"
    selection = _read_json(path)
    if not selection or agent_id is None or selection.get("selected_agent_id") == agent_id:
        try:
            path.unlink()
        except OSError:
            pass


def _service_finalize_active(root: Path, scheduler: dict[str, Any], reason: str) -> str | None:
    process = scheduler.get("process")
    agent_id = str(scheduler.get("agent_id", "")).strip()
    video_ref = scheduler.get("video_ref")
    request = dict(scheduler.get("request") or {})
    operator_preemption = reason in {"operator_live_view", "operator_selection"}
    preempt_stop: dict[str, Any] | None = None
    if process is not None:
        if operator_preemption:
            preempt_stop = _stop_wf_recorder_for_operator(process)
            scheduler["last_preempt_stop"] = preempt_stop
            if not preempt_stop.get("final_pid_dead"):
                scheduler["operator_preempt_blocked_request_id"] = request.get("request_id")
                return None
        else:
            stop_wf_recorder(process)

    completion: dict[str, Any] | None = None
    finalized_ref: str | None = None
    finalize_error: str | None = None
    forced_interrupt = bool(
        operator_preemption
        and preempt_stop
        and preempt_stop.get("mode") in {"terminate", "kill"}
    )
    if forced_interrupt:
        finalize_error = (
            "wf-recorder operator preemption required "
            f"{preempt_stop.get('mode')}; partial segment is explicitly not finalized"
        )
    else:
        finalized_ref, finalize_error = finalize_wf_recorder(root, agent_id, video_ref)
    if finalized_ref:
        provenance_ref = _video_provenance_ref(finalized_ref)
        _write_video_result(
            root,
            request,
            "finalized",
            video_ref=finalized_ref,
            reason=reason,
        )
        completion = _write_completion(
            root,
            "video_segment_finalized",
            agent_id=agent_id,
            state="running",
            tool="evidence_recorder",
            target="vds://agent/video",
            working_note="wf-recorder Sway headless video segmenti finalize edilip immutable kanıt kuyruğuna yazıldı.",
            video_ref=finalized_ref,
            video_provenance_ref=provenance_ref,
            evidence_refs=[finalized_ref, provenance_ref],
            output_ref=finalized_ref,
            capture_kind="sway-headless",
            reason=reason,
            display_capability=read_capability(root),
        )
    elif request:
        _write_video_result(
            root,
            request,
            "error",
            error=finalize_error or "video segmenti finalize edilemedi",
            reason=reason,
        )
    clear_video_owner(root, agent_id)
    _clear_video_selection(root, agent_id)
    scheduler.clear()
    scheduler["last_agent"] = agent_id
    scheduler["last_finalized_at"] = time.monotonic()
    if preempt_stop:
        scheduler["last_preempt_stop"] = preempt_stop
    if completion:
        scheduler["last_completion"] = completion
    if request and reason != "evidence_service_stop":
        if operator_preemption or completion:
            _service_rearm_video_request(root, request)
    return finalized_ref


def _operator_request_age_seconds(request: dict[str, Any]) -> float:
    raw_requested_at = request.get("requested_at")
    try:
        if isinstance(raw_requested_at, (int, float)):
            requested_at = float(raw_requested_at)
        else:
            requested_at = datetime.fromisoformat(str(raw_requested_at)).timestamp()
        return max(0.0, time.time() - requested_at)
    except (TypeError, ValueError, OverflowError):
        return float("inf")


def _service_handle_operator_selection(
    root: Path,
    settings: dict[str, Any],
    scheduler: dict[str, Any],
) -> None:
    request_path = _operator_request_path(root)
    request = _read_json(request_path)
    if not request:
        return
    request_id = str(request.get("request_id", "")).strip()
    if not request_id:
        return
    control_timeout = float(settings["evidence_control_timeout_seconds"])

    def reject_if_current(
        current_age: float,
        preempt_stop: dict[str, Any] | None,
        error: str,
    ) -> bool:
        current = _read_json(request_path)
        if not current or str(current.get("request_id", "")).strip() != request_id:
            return False
        ack_path = _operator_ack_path(root, request_id)
        _atomic_json(
            ack_path,
            {
                "request_id": request_id,
                "selection_id": current.get("selection_id"),
                "status": "rejected",
                "selected_agent_id": None,
                "request_age_seconds": round(current_age, 3),
                "preempt_stop_mode": (preempt_stop or {}).get("mode"),
                "preempt_elapsed_seconds": (preempt_stop or {}).get("elapsed_seconds"),
                "preempt_graceful": (preempt_stop or {}).get("graceful"),
                "preempt_final_pid_dead": (preempt_stop or {}).get("final_pid_dead"),
                "error": error,
                "acknowledged_at": utc_now(),
            },
        )
        latest = _read_json(request_path)
        if latest and str(latest.get("request_id", "")).strip() == request_id:
            try:
                request_path.unlink()
            except OSError:
                pass
        return True

    request_age = _operator_request_age_seconds(request)
    if request_age > control_timeout:
        reject_if_current(request_age, None, "operator display request expired before preemption")
        return
    if scheduler.get("operator_preempt_blocked_request_id") == request_id:
        return

    preempted_ref = None
    completion = None
    preempt_stop: dict[str, Any] | None = None
    if scheduler.get("process") is not None:
        preempted_ref = _service_finalize_active(root, scheduler, "operator_live_view")
        preempt_stop = scheduler.get("last_preempt_stop")
        if scheduler.get("process") is not None:
            return
        completion = scheduler.get("last_completion")
    else:
        _clear_video_selection(root)

    latest = _read_json(request_path)
    if not latest or str(latest.get("request_id", "")).strip() != request_id:
        return
    request = latest
    request_age = _operator_request_age_seconds(request)
    if request_age > control_timeout:
        reject_if_current(request_age, preempt_stop, "operator display request expired before selection commit")
        return

    selected_agent_id = str(request.get("selected_agent_id") or "").strip() or None
    expires_at = None
    if selected_agent_id:
        expires_at = time.time() + float(settings["operator_view_lease_seconds"])
        _atomic_json(
            _control_dir(root) / "operator-selection.json",
            {
                "request_id": request_id,
                "selected_agent_id": selected_agent_id,
                "selected_at": utc_now(),
                "selection_id": request.get("selection_id"),
                "request_age_seconds": round(request_age, 3),
                "preempt_stop_mode": (preempt_stop or {}).get("mode"),
                "preempt_elapsed_seconds": (preempt_stop or {}).get("elapsed_seconds"),
                "preempt_graceful": (preempt_stop or {}).get("graceful"),
                "preempt_final_pid_dead": (preempt_stop or {}).get("final_pid_dead"),
                "expires_at": expires_at,
                "expires_at_iso": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            },
        )
    else:
        try:
            (_control_dir(root) / "operator-selection.json").unlink()
        except OSError:
            pass
    ack_path = _operator_ack_path(root, request_id)
    _atomic_json(
        ack_path,
        {
            "request_id": request_id,
            "selection_id": request.get("selection_id"),
            "status": "acknowledged",
            "selected_agent_id": selected_agent_id,
            "expires_at": expires_at,
            "preempted_video_ref": preempted_ref,
            "completion": completion,
            "request_age_seconds": round(request_age, 3),
            "preempt_stop_mode": (preempt_stop or {}).get("mode"),
            "preempt_elapsed_seconds": (preempt_stop or {}).get("elapsed_seconds"),
            "preempt_graceful": (preempt_stop or {}).get("graceful"),
            "preempt_final_pid_dead": (preempt_stop or {}).get("final_pid_dead"),
            "acknowledged_at": utc_now(),
        },
    )
    current = _read_json(request_path)
    if current and str(current.get("request_id", "")).strip() == request_id:
        try:
            request_path.unlink()
        except OSError:
            pass


def _service_handle_video_revoke(root: Path, scheduler: dict[str, Any]) -> None:
    request_path = _control_dir(root) / "video-revoke-request.json"
    request = _read_json(request_path)
    if not request:
        return
    agent_id = str(request.get("agent_id", "")).strip()
    finalized_ref = None
    completion = None
    if scheduler.get("process") is not None and scheduler.get("agent_id") == agent_id:
        finalized_ref = _service_finalize_active(root, scheduler, str(request.get("reason", "operator_revoke")))
        completion = scheduler.get("last_completion")
    else:
        pending_path = _video_request_path(root, agent_id)
        pending = _read_json(pending_path)
        if pending and pending.get("status", "pending") == "pending":
            _write_video_result(
                root,
                pending,
                "cancelled",
                error="video lease operator müdahalesiyle iptal edildi",
                reason=str(request.get("reason", "operator_revoke")),
            )
    ack_path = _control_dir(root) / f"video-revoke-ack-{request.get('request_id', '')}.json"
    _atomic_json(
        ack_path,
        {
            "request_id": request.get("request_id"),
            "agent_id": agent_id,
            "video_ref": finalized_ref,
            "video_provenance_ref": (
                _video_provenance_ref(finalized_ref) if finalized_ref else None
            ),
            "completion": completion,
            "acknowledged_at": utc_now(),
        },
    )
    try:
        request_path.unlink()
    except OSError:
        pass

def _service_retry_video_request(root: Path, request: dict[str, Any]) -> None:
    _service_rearm_video_request(root, request)


def _service_start_video(root: Path, settings: dict[str, Any], scheduler: dict[str, Any], request: dict[str, Any]) -> None:
    agent_id = str(request.get("agent_id", "")).strip()
    request_id = str(request.get("request_id", "")).strip()
    try:
        reserve_video_owner(root, agent_id, request_id, settings["video_segment_seconds"])
    except (OSError, RuntimeError, ValueError) as exc:
        _write_video_result(root, request, "error", error=f"{type(exc).__name__}: {exc}"[:500], reason="reserve")
        _service_retry_video_request(root, request)
        return
    _atomic_json(
        _control_dir(root) / "video-selection.json",
        {
            "selected_agent_id": agent_id,
            "request_id": request_id,
            "selected_at": utc_now(),
        },
    )
    render_error = wait_for_display_render(root, agent_id)
    if render_error:
        clear_video_owner(root, agent_id)
        _clear_video_selection(root, agent_id)
        _write_video_result(root, request, "error", error=render_error, reason="render")
        _service_retry_video_request(root, request)
        return
    try:
        started = start_wf_recorder(root, agent_id)
    except (OSError, RuntimeError, ValueError) as exc:
        clear_video_owner(root, agent_id)
        _clear_video_selection(root, agent_id)
        _write_video_result(root, request, "error", error=f"{type(exc).__name__}: {exc}"[:500], reason="start")
        _service_retry_video_request(root, request)
        return
    if started is None:
        clear_video_owner(root, agent_id)
        _clear_video_selection(root, agent_id)
        _write_video_result(root, request, "error", error="wf-recorder gerçek Sway çıktısı için başlatılamadı", reason="start")
        _service_retry_video_request(root, request)
        return
    process, video_ref = started
    try:
        claim_video_owner(root, agent_id, video_ref, settings["video_segment_seconds"])
    except (OSError, RuntimeError, ValueError) as exc:
        stop_wf_recorder(process)
        clear_video_owner(root, agent_id)
        _clear_video_selection(root, agent_id)
        _write_video_result(root, request, "error", error=f"{type(exc).__name__}: {exc}"[:500], reason="claim")
        _service_retry_video_request(root, request)
        return
    scheduler.update(
        {
            "process": process,
            "agent_id": agent_id,
            "request": dict(request),
            "request_id": request_id,
            "video_ref": video_ref,
            "started_at": time.monotonic(),
        }
    )


def _service_video_tick(root: Path, settings: dict[str, Any], scheduler: dict[str, Any]) -> None:
    _service_handle_video_revoke(root, scheduler)
    _service_handle_operator_selection(root, settings, scheduler)
    _service_capture_one(root, settings)
    operator = _operator_selection(root) or {}
    operator_agent = str(operator.get("selected_agent_id") or "").strip()
    if scheduler.get("process") is not None:
        active_agent = str(scheduler.get("agent_id", ""))
        process = scheduler["process"]
        owner = read_video_owner(root)
        if operator_agent:
            _service_finalize_active(root, scheduler, "operator_selection")
        elif not owner or owner.get("agent_id") != active_agent:
            _service_finalize_active(root, scheduler, "video_owner_lost")
        elif owner.get("lease_expired"):
            _service_finalize_active(root, scheduler, "lease_expired")
        elif not _pid_is_alive((scheduler.get("request") or {}).get("pid")):
            _service_finalize_active(root, scheduler, "worker_exit")
        elif process.poll() is not None or time.monotonic() - float(scheduler.get("started_at", 0.0)) >= settings["video_segment_seconds"]:
            _service_finalize_active(root, scheduler, "segment_rotation")
        else:
            return
    if scheduler.get("process") is not None:
        return
    if operator_agent:
        _clear_video_selection(root)
        return
    requests = [request for request in _video_requests(root) if _pid_is_alive(request.get("pid"))]
    for request in _video_requests(root):
        if not _pid_is_alive(request.get("pid")):
            try:
                _video_request_path(root, str(request.get("agent_id", ""))).unlink()
            except (OSError, ValueError):
                pass
    if not requests:
        _clear_video_selection(root)
        return
    if (
        scheduler.get("last_agent")
        and time.monotonic() - float(scheduler.get("last_finalized_at", 0.0)) < settings["video_fairness_cooldown_seconds"]
    ):
        return
    last_agent = str(scheduler.get("last_agent", ""))
    if len(requests) > 1 and last_agent:
        fair = [request for request in requests if str(request.get("agent_id")) != last_agent]
        if fair:
            requests = fair
    _service_start_video(root, settings, scheduler, requests[0])


def _on_signal(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True


def _wait_for_socket(socket_path: Path, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not _STOP:
        if socket_path.exists():
            return True
        time.sleep(0.2)
    return socket_path.exists()


def _discover_wayland_socket(runtime_dir: Path, timeout: float = 15.0) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not _STOP:
        sockets = sorted(
            path for path in runtime_dir.glob("wayland-*") if path.is_socket()
        )
        if sockets:
            return sockets[0]
        time.sleep(0.2)
    sockets = sorted(
        path for path in runtime_dir.glob("wayland-*") if path.is_socket()
    )
    return sockets[0] if sockets else None


def _port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not _STOP:
        if _port_ready(port):
            return True
        time.sleep(0.1)
    return _port_ready(port)


def _terminate(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_service(root: Path) -> int:
    settings = capture_settings()
    runtime_dir = Path(settings["runtime_dir"]).expanduser()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    socket_path = runtime_dir / settings["wayland_display"]
    sway = shutil.which("sway")
    wayvnc = shutil.which("wayvnc")
    grim = shutil.which("grim")
    wf_recorder = shutil.which("wf-recorder")
    capability: dict[str, Any] = {
        "capture_kind": "sway-headless",
        "headless": True,
        "ready": False,
        "started_at": utc_now(),
        "wayland_display": settings["wayland_display"],
        "runtime_dir": str(runtime_dir),
        "output": settings["headless_output"],
        "wayvnc_loopback_port": settings["wayvnc_loopback_port"],
        "sway_available": bool(sway),
        "wayvnc_available": bool(wayvnc),
        "grim_available": bool(grim),
        "wf_recorder_available": bool(wf_recorder),
        "sway_running": False,
        "wayland_socket": False,
        "wayvnc_running": False,
        "wayvnc_loopback_ready": False,
        "surface_running": False,
        "surface_available": False,
        "real_frame_available": False,
        "video_capture_available": False,
        "wayvnc_stream_ref": "vds://wayvnc/loopback",
    }
    if not sway or not wayvnc or not grim or not wf_recorder:
        capability["reason"] = "Sway/wayvnc/grim/wf-recorder eksik"
        _atomic_json(capability_path(root), capability)
        return 2
    sway_template = _repo_root() / "config" / "sway" / "paidproxy-headless.conf"
    if not sway_template.is_file():
        capability["reason"] = f"Sway headless config yok: {sway_template}"
        _atomic_json(capability_path(root), capability)
        return 2
    sway_config = _render_sway_config(runtime_dir, settings)
    environment = os.environ.copy()
    environment.update({
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "WAYLAND_DISPLAY": settings["wayland_display"],
        "WLR_BACKENDS": "headless",
        "WLR_HEADLESS_OUTPUTS": "1",
        "WLR_RENDERER": "pixman",
        "WLR_LIBINPUT_NO_DEVICES": "1",
    })
    sway_process: subprocess.Popen[str] | None = None
    wayvnc_process: subprocess.Popen[str] | None = None
    surface_process: subprocess.Popen[str] | None = None
    scheduler: dict[str, Any] = {}
    try:
        sway_process = subprocess.Popen(
            [sway, "--unsupported-gpu", "-c", str(sway_config)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        socket_path = _discover_wayland_socket(runtime_dir)
        if socket_path is None:
            capability["reason"] = "Sway headless Wayland socket açılmadı"
            capability["sway_running"] = False
            _atomic_json(capability_path(root), capability)
            return 3
        settings["wayland_display"] = socket_path.name
        environment["WAYLAND_DISPLAY"] = socket_path.name
        capability["wayland_display"] = socket_path.name
        capability["wayland_socket_path"] = str(socket_path)
        wayvnc_process = subprocess.Popen(
            [wayvnc, f"--output={settings['headless_output']}", "127.0.0.1", str(settings["wayvnc_loopback_port"])],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        surface_program = shutil.which(settings["surface_program"])
        if surface_program:
            surface_process = subprocess.Popen(
                [
                    surface_program,
                    "--title",
                    "PaidProxy VDS Headless / Sway",
                    sys.executable,
                    "-m",
                    "services.agentd.evidence_display",
                    "--surface",
                    "--root",
                    str(root),
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        capability.update({
            "sway_running": sway_process.poll() is None,
            "wayland_socket": socket_path.exists(),
            "wayvnc_running": wayvnc_process.poll() is None,
            "wayvnc_loopback_ready": _wait_for_port(settings["wayvnc_loopback_port"]),
            "surface_running": bool(surface_process and surface_process.poll() is None),
            "sway_pid": sway_process.pid,
            "wayvnc_pid": wayvnc_process.pid,
            "surface_pid": surface_process.pid if surface_process else None,
            "heartbeat_at": utc_now(),
        })
        capability["wayvnc_loopback_ready"] = bool(
            capability["wayvnc_running"] and capability["wayvnc_loopback_ready"]
        )
        capability["surface_available"] = bool(capability["surface_running"])
        capability["real_frame_available"] = bool(
            capability["sway_running"]
            and capability["wayland_socket"]
            and capability["grim_available"]
            and capability["surface_available"]
        )
        capability["video_capture_available"] = bool(
            capability["real_frame_available"] and capability["wf_recorder_available"]
        )
        capability["ready"] = bool(
            capability["real_frame_available"] and capability["wayvnc_loopback_ready"]
        )
        if not capability["ready"]:
            missing = [
                name for name, available in (
                    ("Sway", capability["sway_running"]),
                    ("Wayland socket", capability["wayland_socket"]),
                    ("surface", capability["surface_available"]),
                    ("wayvnc loopback", capability["wayvnc_loopback_ready"]),
                ) if not available
            ]
            capability["reason"] = "Kanıt yığını hazır değil: " + ", ".join(missing)
        _atomic_json(capability_path(root), capability)
        while not _STOP:
            try:
                _service_video_tick(root, settings, scheduler)
            except (OSError, RuntimeError, ValueError) as exc:
                capability["video_scheduler_error"] = f"{type(exc).__name__}: {exc}"[:500]
            if (
                sway_process.poll() is not None
                or wayvnc_process.poll() is not None
                or surface_process is None
                or surface_process.poll() is not None
            ):
                for key in (
                    "ready",
                    "sway_running",
                    "wayland_socket",
                    "wayvnc_running",
                    "wayvnc_loopback_ready",
                    "surface_running",
                    "surface_available",
                    "real_frame_available",
                    "video_capture_available",
                ):
                    capability[key] = False
                capability["reason"] = "Sway, wayvnc veya gerçek evidence surface prosesi durdu"
                _atomic_json(capability_path(root), capability)
                return 4
            capability["heartbeat_at"] = utc_now()
            _atomic_json(capability_path(root), capability)
            time.sleep(1.0)
        return 0
    finally:
        try:
            if scheduler.get("process") is not None:
                _service_finalize_active(root, scheduler, "evidence_service_stop")
        except (OSError, RuntimeError, ValueError):
            pass
        for key in (
            "ready",
            "sway_running",
            "wayland_socket",
            "wayvnc_running",
            "wayvnc_loopback_ready",
            "surface_running",
            "surface_available",
            "real_frame_available",
            "video_capture_available",
        ):
            capability[key] = False
        capability["stopped_at"] = utc_now()
        _atomic_json(capability_path(root), capability)
        _terminate(surface_process)
        _terminate(wayvnc_process)
        _terminate(sway_process)


def _load_views(root: Path) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    agents_dir = Path(root).resolve() / "agents"
    if not agents_dir.is_dir():
        return views
    for view_path in agents_dir.glob("*/current-view.json"):
        try:
            payload = json.loads(view_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                views.append(payload)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(views, key=lambda item: str(item.get("updated_at", "")), reverse=True)


def _surface_text(root: Path, views: list[dict[str, Any]], mode: str) -> str:
    lines = [
        "\033[2J\033[H\033[1;36mPAIDPROXY / VDS HEADLESS / SWAY\033[0m",
        "Gercek Wayland yuzeyi | wayvnc: VDS loopback | Kaynak: agentd olaylari",
        f"Gorunum modu: {mode}",
        f"Yenilendi: {utc_now()}",
        "",
    ]
    if not views:
        lines.append("Ajan kaniti bekleniyor; sahte aktivite uretilmiyor.")
        return "\n".join(lines)
    for view in views[:5]:
        lines.extend([
            f"\033[1;32m[{view.get('agent_id', '-')} / pet={view.get('pet_name', '-')}] "
            f"{view.get('event_type', 'event')} [{view.get('tool', '-')}] \033[0m",
            f"Hedef: {view.get('target', '-')}",
            f"Not: {view.get('working_note', '-')}",
            f"Hipotez: {view.get('hypothesis', '-')}",
            f"Karsi hipotez: {view.get('counter_hypothesis', '-')}",
            f"Sonraki: {view.get('next_action', '-')}",
            f"Event ID: {view.get('event_id', '-')}",
            f"Render revision: {view.get('render_revision', '-')}",
            f"Kanıt: {'; '.join(str(item) for item in (view.get('evidence_refs') or [])[:3]) or '-'}",
            f"Operator: {view.get('operator_action', '-')}",
            "",
        ])
    return "\n".join(lines)


def run_surface(root: Path) -> int:
    global _STOP
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    settings = capture_settings()
    while not _STOP:
        request_path = _control_dir(root) / "capture-request.json"
        request = _read_json(request_path)
        operator = _operator_selection(root)
        operator_agent = str((operator or {}).get("selected_agent_id") or "").strip()
        request_agent = str((request or {}).get("agent_id") or "").strip()
        capture_request = request if request and (
            not operator_agent or request_agent == operator_agent
        ) else None
        if capture_request:
            view = dict(capture_request.get("view") or {})
            view.setdefault("agent_id", capture_request.get("agent_id", "-"))
            view.setdefault("event_id", capture_request.get("event_id", "-"))
            view.setdefault("render_revision", capture_request.get("render_revision", "-"))
            views = [view]
            mode = "capture-handshake"
        else:
            selection = operator
            selection_mode = "operator-selected"
            if selection is None:
                selection = _video_selection(root)
                selection_mode = "passive-video"
            if selection is None:
                selection_mode = "global-dashboard"
            elif not selection.get("selected_agent_id"):
                selection_mode = "operator-dashboard"
            selection = selection or {}
            selected_agent_id = str(selection.get("selected_agent_id") or "").strip()
            if selected_agent_id:
                selected_view = _load_agent_view(root, selected_agent_id)
                if selected_view is None:
                    selected_view = {
                        "agent_id": selected_agent_id,
                        "pet_name": "bekleniyor",
                        "event_type": "display_selection_pending",
                        "working_note": "Seçilen ajanın ilk gerçek olayı bekleniyor.",
                    }
                views = [selected_view]
                mode = selection_mode
            else:
                views = _load_views(root)[:5]
                mode = selection_mode
        sys.stdout.write(_surface_text(root, views, mode) + "\n")
        sys.stdout.flush()
        if capture_request:
            ack_path = _control_dir(root) / f"capture-ack-{capture_request.get('request_id', '')}.json"
            if not ack_path.exists():
                time.sleep(settings["surface_render_settle_seconds"])
                _atomic_json(
                    ack_path,
                    {
                        "request_id": capture_request.get("request_id"),
                        "agent_id": capture_request.get("agent_id"),
                        "event_id": capture_request.get("event_id"),
                        "render_revision": capture_request.get("render_revision"),
                        "acknowledged_at": utc_now(),
                    },
                )
        time.sleep(settings["surface_refresh_seconds"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="var/agentd")
    parser.add_argument("--surface", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    root = Path(args.root).expanduser().resolve()
    return run_surface(root) if args.surface else run_service(root)


if __name__ == "__main__":
    raise SystemExit(main())

"""Tek uzak ajan worker'ı.

Worker gerçek child process olarak VDS'de yaşar. Bu katman sahte ilerleme
üretmez; gerçek runtime gözlemi ve supervisor'a JSONL event verir.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from services.agentd.protocol import encode_message, make_event
from services.agentd.ai_runtime import AgentRuntime
from services.agentd.evidence_display import (
    capture_event,
    consume_video_lease_result,
    poll_video_lease,
    read_capability,
    read_display_state,
    request_video_lease,
    write_current_view,
)

_STOP = threading.Event()
_STOP_REASON = "operator"
_CONTEXT: dict[str, Any] = {}
_EMIT_LOCK = threading.RLock()
_LAST_CAPTURE_ERROR = ""


def _persist_display_capability(capability: dict[str, Any]) -> str | None:
    agent_id = str(_CONTEXT.get("agent_id", "")).strip()
    root = Path(str(_CONTEXT.get("root", "")))
    if not agent_id or not root:
        return None
    outputs_dir = root / "agents" / agent_id / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    path = outputs_dir / "display-capability.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(capability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return f"agent://{agent_id}/outputs/display-capability.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def emit_worker_event(event_type: str, working_note: str, **fields: Any) -> None:
    global _LAST_CAPTURE_ERROR
    capture_enabled = bool(fields.pop("_capture", True))
    video_enabled = bool(fields.pop("_video", True))
    capture_error = None
    video_error = None
    with _EMIT_LOCK:
        payload = make_event(
            event_type,
            agent_id=str(_CONTEXT.get("agent_id", "")),
            job_id=str(_CONTEXT.get("job_id", "")),
            pid=os.getpid(),
            process_group=os.getpgid(0),
            state=str(fields.pop("state", "running")),
            working_note=working_note,
            **fields,
        )
        capability = read_capability(Path(str(_CONTEXT.get("root", ""))))
        try:
            capability_ref = _persist_display_capability(capability)
        except OSError:
            capability_ref = _CONTEXT.get("display_capability_ref")
        payload["capture_kind"] = "sway-headless"
        payload["display_capability"] = capability
        payload["wayvnc_stream_ref"] = capability.get("wayvnc_stream_ref")
        payload["display_control"] = read_display_state(Path(str(_CONTEXT.get("root", ""))))
        if capability_ref and not _CONTEXT.get("display_capability_ref"):
            _CONTEXT["display_capability_ref"] = capability_ref
        if capture_enabled:
            try:
                frame_ref, capture_error = capture_event(
                    Path(str(_CONTEXT.get("root", ""))),
                    str(_CONTEXT.get("agent_id", "")),
                    payload,
                )
            except (OSError, ValueError) as exc:
                frame_ref = None
                capture_error = f"{type(exc).__name__}: {exc}"[:500]
        else:
            frame_ref = None
            try:
                write_current_view(
                    Path(str(_CONTEXT.get("root", ""))),
                    str(_CONTEXT.get("agent_id", "")),
                    payload,
                )
            except (OSError, ValueError):
                pass
        if frame_ref:
            payload["frame_ref"] = frame_ref
            evidence_refs = list(payload.get("evidence_refs") or [])
            if frame_ref not in evidence_refs:
                evidence_refs.append(frame_ref)
            if payload.get("frame_provenance_ref") and payload["frame_provenance_ref"] not in evidence_refs:
                evidence_refs.append(payload["frame_provenance_ref"])
            payload["evidence_refs"] = evidence_refs[-8:]
        if video_enabled:
            try:
                _maintain_video()
            except (OSError, ValueError) as exc:
                video_error = f"{type(exc).__name__}: {exc}"[:500]
        sys.stdout.write(encode_message(payload))
        sys.stdout.flush()
    if (
        capture_error
        and _CONTEXT.get("preflight_done")
        and event_type != "evidence_capture_unavailable"
        and capture_error != _LAST_CAPTURE_ERROR
    ):
        _LAST_CAPTURE_ERROR = capture_error
        emit_worker_event(
            "evidence_capture_unavailable",
            "Gerçek Sway headless ekranı grim ile yakalanamadı; sahte frame üretilmedi.",
            state="degraded",
            tool="evidence_recorder",
            target="vds://agent/evidence",
            error=capture_error,
            evidence_refs=[
                str(
                    _CONTEXT.get(
                        "display_capability_ref",
                        f"agent://{_CONTEXT.get('agent_id', '')}/outputs/display-capability.json",
                    )
                )
            ],
            next_action="Sway/wayland/grim capability inspect",
            _capture=False,
            _video=False,
        )
    elif frame_ref:
        _LAST_CAPTURE_ERROR = ""
    if video_error and event_type != "video_capture_unavailable":
        emit_worker_event(
            "video_capture_unavailable",
            "wf-recorder gerçek Sway görüntüsü için başlatılamadı; video sahte kabul edilmedi.",
            state="degraded",
            tool="evidence_recorder",
            target="vds://agent/video",
            error=video_error,
            next_action="wf-recorder/Sway capability inspect",
            _capture=False,
            _video=False,
        )




_VIDEO_REQUEST_ID: str | None = None
_VIDEO_LAST_FINALIZED_AT = 0.0
_LAST_VIDEO_ERROR = ""


def _maintain_video() -> tuple[str | None, str | None]:
    global _VIDEO_REQUEST_ID, _VIDEO_LAST_FINALIZED_AT, _LAST_VIDEO_ERROR
    root = Path(str(_CONTEXT.get("root", "")))
    agent_id = str(_CONTEXT.get("agent_id", ""))
    if _VIDEO_REQUEST_ID:
        result = poll_video_lease(root, agent_id, _VIDEO_REQUEST_ID)
        if result is None:
            return None, None
        request_id = _VIDEO_REQUEST_ID
        consume_video_lease_result(root, agent_id, request_id)
        _VIDEO_REQUEST_ID = None
        if result.get("status") == "finalized" and result.get("video_ref"):
            _VIDEO_LAST_FINALIZED_AT = time.monotonic()
            _LAST_VIDEO_ERROR = ""
            return str(result["video_ref"]), None
        error = str(result.get("error", "VDS evidence service video lease başarısız"))[:500]
        _LAST_VIDEO_ERROR = error
        return None, error
    if time.monotonic() - _VIDEO_LAST_FINALIZED_AT < 1.0:
        return None, None
    try:
        _VIDEO_REQUEST_ID = request_video_lease(root, agent_id)
    except (OSError, ValueError) as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        if error == _LAST_VIDEO_ERROR:
            return None, None
        _LAST_VIDEO_ERROR = error
        return None, error
    return None, None



def _on_signal(signum: int, _frame: Any) -> None:
    global _STOP_REASON
    _STOP_REASON = signal.Signals(signum).name
    if not _STOP.is_set():
        emit_worker_event(
            "agent_stopping",
            f"Worker sonlandırma sinyali aldı: {_STOP_REASON}.",
            state="stopping",
            operator_action=_STOP_REASON,
            next_action="worker exit",
            _video=False,
        )
        _STOP.set()


def _preflight(root: Path) -> None:
    masscan = shutil.which("masscan")
    python = sys.executable
    try:
        child_count = sum(1 for _ in root.glob("*")) if root.exists() else 0
    except OSError:
        child_count = -1
    capability = read_capability(root)
    report = {
        "observed_at": utc_now(),
        "workspace_exists": root.exists(),
        "workspace_entry_count": child_count,
        "python": Path(python).name,
        "masscan_available": bool(masscan),
        "masscan_binary": Path(masscan).name if masscan else None,
        "evidence_display": capability,
    }
    agent_dir = root / "agents" / str(_CONTEXT["agent_id"])
    agent_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir = agent_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    capability_path = outputs_dir / "display-capability.json"
    temporary_capability = capability_path.with_suffix(".json.tmp")
    temporary_capability.write_text(
        json.dumps(capability, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_capability, capability_path)
    try:
        os.chmod(capability_path, 0o600)
    except OSError:
        pass
    _CONTEXT["display_capability_ref"] = (
        f"agent://{_CONTEXT['agent_id']}/outputs/display-capability.json"
    )
    report_path = agent_dir / "preflight.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    try:
        os.chmod(report_path, 0o600)
    except OSError:
        pass
    _CONTEXT["preflight_done"] = True
    emit_worker_event(
        "workspace_observed",
        "VDS çalışma alanı ve araç yüzeyi gerçek dosya/proses gözlemiyle okundu.",
        tool="runtime_probe",
        target="vds://workspace",
        evidence_refs=[
            f"agent://{_CONTEXT['agent_id']}/preflight.json",
            _CONTEXT["display_capability_ref"],
        ],
        output_ref=f"agent://{_CONTEXT['agent_id']}/preflight.json",
        next_action="AI tool loop hazır olduğunda dinamik araştırma seçilecek",
        workspace_entry_count=child_count,
        masscan_available=bool(masscan),
        capture_kind="sway-headless",
        display_capability=report["evidence_display"],
        wayvnc_stream_ref=report["evidence_display"].get("wayvnc_stream_ref"),
    )


def run_worker(agent_id: str, job_id: str, kind: str, root: str, initial_input: str = "") -> int:
    global _CONTEXT
    _CONTEXT = {
        "agent_id": agent_id,
        "job_id": job_id,
        "kind": kind,
        "parent_pid": os.getppid(),
        "initial_input": str(initial_input or "")[:2000],
        "root": str(Path(root).resolve()),
        "preflight_done": False,
    }
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    emit_worker_event(
        "agent_started",
        "VDS worker gerçek child process olarak başladı.",
        tool="process_runtime",
        target="vds://worker",
        next_action="runtime preflight",
        agent_kind=kind,
    )
    try:
        _preflight(Path(root))
    except Exception as exc:
        emit_worker_event(
            "error",
            "VDS preflight gözlemi tamamlanamadı.",
            state="failed",
            tool="runtime_probe",
            error=f"{type(exc).__name__}: {exc}",
            next_action="operator inspect",
        )
        return 1

    try:
        runtime = AgentRuntime(
            root=Path(root),
            agent_id=agent_id,
            job_id=job_id,
            kind=kind,
            initial_input=initial_input,
            emit=emit_worker_event,
            stopped=_STOP.is_set,
        )
        return runtime.run()
    except Exception as exc:
        emit_worker_event(
            "error",
            "VDS AI runtime beklenmedik biçimde durdu.",
            state="failed",
            tool="agent_runtime",
            target="vds://agent",
            error=f"{type(exc).__name__}: {exc}",
            next_action="operator inspect",
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--kind", default="gezinme")
    parser.add_argument("--root", required=True)
    parser.add_argument("--initial-input", default="")
    args = parser.parse_args()
    return run_worker(args.agent_id, args.job_id, args.kind, args.root, args.initial_input)


if __name__ == "__main__":
    raise SystemExit(main())

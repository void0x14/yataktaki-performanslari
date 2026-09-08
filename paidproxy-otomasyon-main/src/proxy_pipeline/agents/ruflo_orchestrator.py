"""PaidProxy'nin gerçek Ruflo çalışma bağlayıcısı.

Ruflo'nun vendor ağacındaki swarm/agent kayıtlarını başlatır ve Python karar
katmanına yalnız izinli iki model için rol dağılımı verir. Model çağrıları
Ruflo'nun varsayılan sağlayıcılarına bırakılmaz; ``ai_havuz`` yalnız
``keys.txt`` içindeki MiMo ve Gemini uçlarını çağırır.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import threading


MIMO = "mimo"
GEMINI = "gemini-web2api"
MIMO_MODEL = "mimo-v2.5-pro"
GEMINI_MODEL = "gemini-3.5-flash-thinking-lite"
ALLOWED_PROVIDERS = frozenset({MIMO, GEMINI})

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUFLO_BIN = _PROJECT_ROOT / "vendor" / "ruflo" / "ruflo" / "bin" / "ruflo.js"
_SWARM_STATE = _PROJECT_ROOT / ".swarm" / "state.json"
_AGENT_MARKER = _PROJECT_ROOT / ".swarm" / "paidproxy-agents.json"
_RUNTIME_LOCK = threading.Lock()
_RUNTIME_READY = False
_NODE = shutil.which("node") or "/opt/node-v22.22.2-linux-arm64/bin/node"


@dataclass(frozen=True)
class AgentTask:
    role: str
    provider: str
    model: str


@dataclass(frozen=True)
class RoutePlan:
    tasks: tuple[AgentTask, ...]


class RufloUnavailable(RuntimeError):
    """Vendor Ruflo runtime is not available or could not initialize."""


def _run_ruflo(*args: str) -> None:
    if not _RUFLO_BIN.is_file():
        raise RufloUnavailable(f"Ruflo runtime missing: {_RUFLO_BIN}")
    command = [_NODE, str(_RUFLO_BIN), *args, "--no-update", "--no-color"]
    try:
        result = subprocess.run(
            command,
            cwd=_PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RufloUnavailable(f"Ruflo çalıştırma hatası: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise RufloUnavailable(f"Ruflo komutu başarısız: {args[0] if args else 'unknown'}")


def ensure_runtime() -> None:
    """Ensure the real Ruflo swarm and the two model-role agents exist."""
    global _RUNTIME_READY
    if _RUNTIME_READY:
        return
    with _RUNTIME_LOCK:
        if _RUNTIME_READY:
            return
        if not _SWARM_STATE.is_file():
            _run_ruflo(
                "swarm", "init", "--topology", "hybrid", "--max-agents", "2",
                "--strategy", "specialized", "--format", "json",
            )
        if not _AGENT_MARKER.is_file():
            _run_ruflo(
                "agent", "spawn", "--type", "coordinator", "--name", "paidproxy-mimo",
                "--provider", MIMO, "--model", MIMO_MODEL,
                "--task", "PaidProxy avı karar planlayıcısı", "--format", "json",
            )
            _run_ruflo(
                "agent", "spawn", "--type", "reviewer", "--name", "paidproxy-gemini",
                "--provider", GEMINI, "--model", GEMINI_MODEL,
                "--task", "PaidProxy avı kararlarını bağımsız inceleyen ajan", "--format", "json",
            )
            _AGENT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            _AGENT_MARKER.write_text(json.dumps({
                "providers": [MIMO, GEMINI],
                "models": [MIMO_MODEL, GEMINI_MODEL],
            }, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        _RUNTIME_READY = True


def _route_hint(context) -> str:
    snapshot = dict(getattr(context, "snapshot", {}) or {})
    explicit = str(snapshot.get("ai_route", "")).strip().lower()
    if explicit in {MIMO, MIMO_MODEL, GEMINI, GEMINI_MODEL, "gemini", "both", "full"}:
        return explicit
    if str(snapshot.get("model_tercihi", "")).strip().lower() == "derin":
        return "both"
    phase = str(snapshot.get("phase", "")).strip().lower()
    decision_type = str(getattr(context, "decision_type", "")).strip().lower()
    if phase in {"source", "research", "scent", "context"} or decision_type in {
        "source", "research", "scent", "context",
    }:
        return GEMINI
    return MIMO


def route_plan(context, *, ensure: bool = False) -> RoutePlan:
    """Return Ruflo's adaptive two-role plan without inventing targets."""
    if ensure:
        ensure_runtime()
    hint = _route_hint(context)
    if hint in {"both", "full"}:
        return RoutePlan((
            AgentTask("planner", MIMO, MIMO_MODEL),
            AgentTask("reviewer", GEMINI, GEMINI_MODEL),
        ))
    if hint in {GEMINI, GEMINI_MODEL, "gemini"}:
        return RoutePlan((AgentTask("scout", GEMINI, GEMINI_MODEL),))
    return RoutePlan((AgentTask("planner", MIMO, MIMO_MODEL),))

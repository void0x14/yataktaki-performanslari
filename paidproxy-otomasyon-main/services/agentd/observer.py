#!/usr/bin/env python3
"""paidproxy observer agent + deterministic condition gate + harness watchdog.

Three separate responsibilities, deliberately not mixed:

1. ``deterministic_conditions`` — no AI. Pure yes/no checks over real
   artifacts: did the target come from real evidence, was every open port
   attempted, is there an L7 + egress proof, does every published record have
   matching proof.
2. ``Observer`` — a separate AI agent (Muse Spark JB on the zen endpoint,
   OpenAI-compatible ``/chat/completions``, no key). It reads the planner's
   decisions and the real outcomes, then reports priority violations and
   deterministic-layer mistakes. It never decides and never replaces the
   planner. Output is JSON, append-only.
3. ``HarnessWatchdog`` — process repair only, no code repair. Probes the
   Claude Code harness, the zen endpoint and the agentd service; on failure it
   reaps hung ``claude`` processes and restarts the agentd service so the
   planner loop re-spawns Claude Code.

The observer talks to the zen endpoint directly. No middleware.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://opencode.hrmn.tr/zen/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor-free-jb"
FALLBACK_MODELS = (
    "muse-spark-1.3-contributor-free-jb",
    "muse-spark-1.3-contributor-free",
    "muse-spark-1.2-contributor-free",
)
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENTD_ROOT = DEFAULT_REPO_ROOT / "var" / "agentd"
DEFAULT_TIMEOUT = 180.0
USER_AGENT = os.environ.get("PAIDPROXY_ZEN_USER_AGENT") or "paidproxy-observer/1.0 (+zen-direct)"
RETRY_BACKOFF_SECONDS = (2.0, 5.0)

PRIORITY_ORDER = (
    "1) En kısa sürede en yüksek getirili GERÇEK DC/residential proxy "
    "(en yüksek getiri, en kısa süre). "
    "2) En kısa sürede en yüksek çalışma ömrüne sahip DC/residential proxy. "
    "3) G mobile proxy sağlayan sağlayıcılar. "
    "Bu sıradan kimse ayrılamaz."
)

OBSERVER_SYSTEM_PROMPT = """Sen paidproxy avının GÖZLEMCİ ajanısın. Karar vermezsin, \
planner'ın yerine geçmezsin. Görevin yalnızca izlemek ve uyarı üretmek.

Operatörün değişmez öncelik sırası:
{priority}

İzlenecekler:
(a) Planner öncelik sırasına uydu mu?
(b) Küçük/verimsiz dilim seçimi gibi öncelik ihlali var mı? (ör. sağlayıcının \
tüm aralıkları varken tek küçük dilimde ısrar, değerli hedefi bırakıp düşük \
getirili hedefe geçme, aynı kanıtsız hedefe dönme)
(c) Deterministik yapı yanlış iş yaptı mı? (ör. açık portu atladı, masscan \
sonucunu düşürdü, kanıtı kaybetti, doğrulanmamış ucu yayınladı)

Elinde gerçek kanıt var: planner kararları, araç sonuçları, port taraması \
özetleri, L7 doğrulama sonuçları ve deterministik şart kontrolünün çıktısı.
Uydurma yok; yalnızca verilen kanıta dayan.

Çıktı SADECE şu JSON nesnesi olsun, başka metin yazma:
{{"verdict":"ok|warn|violation","priority_compliance":{{"compliant":true|false,"why":"..."}},"issues":[{{"type":"...","severity":"low|medium|high","evidence":"...","why":"..."}}],"observer_note":"..."}}
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _tail_lines(path: Path, limit: int) -> list[str]:
    """Read the last ``limit`` lines without loading a huge file."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = min(size, max(64_000, limit * 4_000))
            handle.seek(max(0, size - block))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    if size > block and lines:
        lines = lines[1:]
    return lines[-limit:]


def _first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(payload, dict):
                        return payload
                    break
        start = text.find("{", start + 1)
    return None


class ZenError(RuntimeError):
    """zen/Cloudflare failure with retry/fallback classification."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        fallback: bool = False,
        kind: str = "error",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.fallback = fallback
        self.kind = kind


def _classify_zen_failure(status: int | None, body: str) -> ZenError:
    """403 RegionError -> fallback model. 403 CF signature -> retry. 429/5xx/timeout -> retry."""
    text = (body or "")[:600]
    lower = text.lower()
    if status == 403 and ("regionerror" in lower or "not available in your country" in lower):
        return ZenError(
            f"zen HTTP 403 RegionError: {text}",
            status=403,
            retryable=False,
            fallback=True,
            kind="region_blocked",
        )
    if status == 403:
        return ZenError(
            f"zen HTTP 403: {text}",
            status=403,
            retryable=True,
            fallback=False,
            kind="cloudflare_403",
        )
    if status == 429:
        return ZenError(f"zen HTTP 429: {text}", status=429, retryable=True, kind="rate_limited")
    if status is not None and 500 <= status < 600:
        return ZenError(f"zen HTTP {status}: {text}", status=status, retryable=True, kind="server_error")
    if status is not None and 400 <= status < 500:
        return ZenError(f"zen HTTP {status}: {text}", status=status, retryable=False, kind="client_error")
    return ZenError(f"zen error: {text}", status=status, retryable=True, kind="unknown")


class MuseSparkClient:
    """Direct OpenAI-compatible client for the zen endpoint. No key, no middleware.

    Bounded retry on 429/5xx/timeout/Cloudflare-403, then fallback to the
    non-JB Muse Spark variants when a model is region-blocked. Every attempt is
    recorded so the report always states which model actually answered.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens: int = 2500,
        fallback_models: tuple[str, ...] | None = None,
        retries: int = 1,
        backoff: tuple[float, ...] = RETRY_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        chain = fallback_models if fallback_models is not None else FALLBACK_MODELS
        self.model_chain = tuple(dict.fromkeys([model, *chain]))
        self.retries = max(0, int(retries))
        self.backoff = tuple(backoff) or (0.0,)
        self._sleep = sleep
        self.last_meta: dict[str, Any] = {}
        self.attempts: list[dict[str, Any]] = []

    def _post(self, model: str, messages: list[dict[str, str]], temperature: float) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare bans the default python-urllib signature (403, error 1010).
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                status = response.status
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise _classify_zen_failure(exc.code, body) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ZenError(
                f"zen ulaşılamadı: {type(exc).__name__}: {exc}",
                retryable=True,
                kind="network",
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ZenError(
                f"zen JSON değil (HTTP {status}): {body[:300]}",
                status=status,
                retryable=True,
                kind="bad_json",
            ) from exc
        if not isinstance(data, dict):
            raise ZenError("zen beklenmeyen yanıt gövdesi", status=status, retryable=True, kind="bad_body")
        if data.get("error"):
            error_text = json.dumps(data["error"], ensure_ascii=False)
            raise _classify_zen_failure(status, error_text)
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ZenError(f"zen choices boş: {body[:300]}", status=status, retryable=True, kind="empty_choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ZenError(f"zen boş içerik: {body[:300]}", status=status, retryable=True, kind="empty_content")
        self.last_meta = {
            "model": data.get("model") or model,
            "model_requested": model,
            "latency_ms": latency_ms,
            "usage": data.get("usage") or {},
            "finish_reason": choices[0].get("finish_reason"),
        }
        return content.strip()

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        self.attempts = []
        errors: list[str] = []
        for model_index, model in enumerate(self.model_chain):
            for attempt in range(self.retries + 1):
                try:
                    content = self._post(model, messages, temperature)
                except ZenError as exc:
                    self.attempts.append(
                        {
                            "model": model,
                            "attempt": attempt + 1,
                            "status": exc.status,
                            "kind": exc.kind,
                            "retryable": exc.retryable,
                            "fallback": exc.fallback,
                            "error": str(exc)[:300],
                        }
                    )
                    errors.append(f"{model}#{attempt + 1} {exc.kind}: {str(exc)[:180]}")
                    if exc.retryable and attempt < self.retries:
                        if exc.status == 524:
                            # Cloudflare proxy read timeout: shrink the budget for the retry.
                            self.max_tokens = min(self.max_tokens, 900)
                        self._sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                        continue
                    break
                self.last_meta.update(
                    {
                        "model_used": self.last_meta.get("model") or model,
                        "model_attempted": model,
                        "model_requested": self.model_chain[0],
                        "fallback_used": model_index > 0,
                        "fallback_from": self.model_chain[0] if model_index > 0 else None,
                        "model_chain": list(self.model_chain),
                        "attempts": list(self.attempts),
                    }
                )
                return content
        self.last_meta.update(self.failure_meta())
        raise ZenError(
            "zen tüm model zinciri başarısız: " + " | ".join(errors[-6:]),
            retryable=False,
            fallback=False,
            kind="chain_exhausted",
        )

    def failure_meta(self) -> dict[str, Any]:
        """Attempt trace for a failed chat() call, so retry/fallback is visible
        in the report even when no model answered."""
        return {
            "model_requested": self.model_chain[0],
            "model_used": None,
            "model_attempted": self.attempts[-1]["model"] if self.attempts else None,
            "fallback_used": any(a.get("model") != self.model_chain[0] for a in self.attempts),
            "fallback_from": self.model_chain[0],
            "model_chain": list(self.model_chain),
            "attempts": list(self.attempts),
        }


def _compact_decision(event: dict[str, Any]) -> dict[str, Any]:
    decision = event.get("decision") if isinstance(event.get("decision"), dict) else {}
    return {
        "seq": event.get("seq"),
        "at": event.get("timestamp"),
        "working_note": str(event.get("working_note") or "")[:400],
        "hypothesis": str(event.get("hypothesis") or "")[:300],
        "next_action": str(event.get("next_action") or "")[:200],
        "action": decision.get("action"),
        "requested_tools": list(decision.get("requested_tools") or [])[:8],
        "targets": list(decision.get("targets") or [])[:8],
        "provider": decision.get("provider"),
        "model": decision.get("model"),
    }


def _compact_tool_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": event.get("seq"),
        "at": event.get("timestamp"),
        "event_type": event.get("event_type"),
        "tool": event.get("tool"),
        "target": str(event.get("target") or "")[:160],
        "error": str(event.get("error") or "")[:200] or None,
        "result_summary": str(event.get("result_summary") or "")[:240] or None,
        "output_ref": event.get("output_ref"),
    }


def _portscan_summary(payload: dict[str, Any], source_name: str | None = None) -> dict[str, Any]:
    open_ports = sorted({int(port) for port in (payload.get("open_ports") or []) if str(port).isdigit()})
    raw_reported = payload.get("masscan_reported")
    if isinstance(raw_reported, int):
        reported_count = raw_reported
    else:
        reported_count = len({int(port) for port in (raw_reported or []) if str(port).isdigit()})
    raw_candidates = payload.get("candidates")
    candidate_count = raw_candidates if isinstance(raw_candidates, int) else len(raw_candidates or [])
    return {
        "ip": payload.get("ip"),
        "scan_range": payload.get("scan_range"),
        "requested_range": payload.get("requested_range"),
        "masscan_reported": reported_count,
        "socket_confirmed_open": len(open_ports),
        "candidate_count": candidate_count,
        "open_ports": open_ports,
        "open_ports_sample": open_ports[:120],
        "method": payload.get("method"),
        "scan_source": source_name,
    }


def _validation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or []
    confirmed = [item for item in results if isinstance(item, dict) and item.get("egress_confirmed")]
    return {
        "host": payload.get("host"),
        "port": payload.get("port"),
        "target": (payload.get("target") or {}).get("url") if isinstance(payload.get("target"), dict) else None,
        "protocols_tried": [str(item.get("protocol")) for item in results if isinstance(item, dict)],
        "egress_confirmed": [
            {"protocol": str(item.get("protocol")), "egress_ip": item.get("egress_ip")}
            for item in confirmed
        ],
        "observed_at": payload.get("observed_at"),
    }


def _agent_outputs(agent_dir: Path, pattern: str, limit: int) -> list[tuple[Path, dict[str, Any]]]:
    found: list[tuple[Path, dict[str, Any]]] = []
    try:
        files = sorted(agent_dir.joinpath("outputs").glob(pattern), key=lambda p: p.stat().st_mtime)
    except OSError:
        return found
    for path in files[-limit:]:
        payload = _read_json(path)
        if isinstance(payload, dict):
            found.append((path, payload))
    return found


def _step_from_name(name: str) -> int:
    match = re.search(r"-(\d{3,})\.(?:json|jsonl)$", name)
    return int(match.group(1)) if match else -1


def _newest_portscans(agent_dir: Path) -> list[tuple[dict[str, Any], str]]:
    """One portscan per IP: the newest by step number, then mtime.

    Old scans must never inflate or deflate the port count of a newer scan of
    the same IP, so only the newest record per IP is returned.
    """
    outputs = agent_dir / "outputs"
    newest: dict[str, tuple[tuple[int, float], dict[str, Any], str]] = {}
    try:
        paths = list(outputs.glob("portscan-*.json"))
    except OSError:
        return []
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        ip = str(payload.get("ip") or "")
        if not ip:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        key = (_step_from_name(path.name), mtime)
        current = newest.get(ip)
        if current is None or key > current[0]:
            newest[ip] = (key, payload, path.name)
    ordered = sorted(newest.values(), key=lambda item: item[0], reverse=True)
    return [(payload, name) for _key, payload, name in ordered]


def _iter_bulk_attempts(agent_dir: Path) -> Iterator[tuple[str, int]]:
    """Stream every (host, port) line from l7-open-ports-*.jsonl.

    These files hold one JSON object per line for thousands of ports, so they
    are read line by line and never loaded whole into memory.
    """
    outputs = agent_dir / "outputs"
    try:
        paths = sorted(outputs.glob("l7-open-ports-*.jsonl"), key=lambda path: _step_from_name(path.name))
    except OSError:
        return
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                host = str(record.get("host") or record.get("ip") or "")
                port = record.get("port")
                try:
                    port_int = int(port)
                except (TypeError, ValueError):
                    continue
                if host and 1 <= port_int <= 65535:
                    yield host, port_int


def _iter_validation_attempts(agent_dir: Path) -> Iterator[tuple[str, int]]:
    """Stream every single-candidate validation artifact (complementary proof)."""
    outputs = agent_dir / "outputs"
    try:
        paths = outputs.glob("validation-*.json")
    except OSError:
        return
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        host = str(payload.get("host") or payload.get("ip") or "")
        port = payload.get("port")
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            continue
        if host and 1 <= port_int <= 65535:
            yield host, port_int


def _attempted_pairs(agent_dir: Path | None) -> tuple[set[tuple[str, int]], dict[str, int]]:
    """Full attempted set from bulk L7 evidence + single validations.

    No fixed output limit: every artifact is streamed, so no proof is skipped.
    """
    attempted: set[tuple[str, int]] = set()
    stats = {"bulk_lines": 0, "validation_files": 0}
    if not agent_dir:
        return attempted, stats
    for host, port in _iter_bulk_attempts(agent_dir):
        attempted.add((host, port))
        stats["bulk_lines"] += 1
    for host, port in _iter_validation_attempts(agent_dir):
        attempted.add((host, port))
        stats["validation_files"] += 1
    return attempted, stats


def collect_evidence(
    root: Path,
    *,
    agent_id: str | None = None,
    decision_limit: int = 10,
    tool_limit: int = 20,
    output_limit: int = 6,
) -> dict[str, Any]:
    """Compact real evidence bundle: planner decisions + real outcomes."""
    root = Path(root)
    events_path = root / "events.jsonl"
    decisions: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    for line in _tail_lines(events_path, 4000):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if agent_id and str(event.get("agent_id") or "") != agent_id:
            continue
        event_type = str(event.get("event_type") or "")
        if event_type == "decision_made":
            decisions.append(_compact_decision(event))
        elif event_type in {"tool_started", "tool_finished", "tool_failed", "tool_deferred"}:
            tools.append(_compact_tool_event(event))

    if agent_id:
        agent_dir = root / "agents" / agent_id
    else:
        agent_dir = _newest_agent_dir(root)
        agent_id = agent_dir.name if agent_dir else None

    facts = _read_json(agent_dir / "facts.json", {}) if agent_dir else {}
    manifest = _read_json(agent_dir / "manifest.json", {}) if agent_dir else {}

    portscans = []
    validations = []
    publishes = []
    attempted_pairs: set[tuple[str, int]] = set()
    attempt_stats: dict[str, int] = {"bulk_lines": 0, "validation_files": 0}
    if agent_dir:
        portscans = [
            _portscan_summary(payload, source_name)
            for payload, source_name in _newest_portscans(agent_dir)
        ]
        validations = [
            _validation_summary(payload)
            for _path, payload in _agent_outputs(agent_dir, "validation-*.json", output_limit)
        ]
        attempted_pairs, attempt_stats = _attempted_pairs(agent_dir)
        validated_file = agent_dir / "outputs" / "validated-candidates.jsonl"
        if validated_file.is_file():
            for line in _tail_lines(validated_file, output_limit):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    publishes.append(
                        {
                            "host": record.get("host"),
                            "port": record.get("port"),
                            "protocol": record.get("protocol"),
                            "quality_label": record.get("quality_label"),
                            "validation_ref": record.get("validation_ref"),
                            "published_at": record.get("published_at"),
                        }
                    )

    return {
        "collected_at": _utc(),
        "agent_id": agent_id,
        "agent_dir": str(agent_dir) if agent_dir else None,
        "current_target": (manifest.get("current_target") if isinstance(manifest, dict) else None),
        "facts_source_ips": list((facts or {}).get("source_ips") or [])[:40],
        "facts_ips": list((facts or {}).get("ips") or [])[:80],
        "decisions": decisions[-decision_limit:],
        "tool_events": tools[-tool_limit:],
        "portscans": portscans,
        "validations": validations,
        "attempted_pairs": sorted(attempted_pairs),
        "attempt_stats": attempt_stats,
        "published": publishes[-output_limit:],
    }


def _newest_agent_dir(root: Path) -> Path | None:
    agents_root = root / "agents"
    try:
        candidates = [path for path in agents_root.iterdir() if path.is_dir()]
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def deterministic_conditions(evidence: dict[str, Any]) -> dict[str, Any]:
    """Non-AI condition gate. Returns yes/no plus a reason for every check."""
    checks: list[dict[str, Any]] = []
    facts_ips = {str(ip) for ip in (evidence.get("facts_ips") or [])}
    facts_sources = {str(ip) for ip in (evidence.get("facts_source_ips") or [])}

    # 1) Target provenance: the planner's target must come from real evidence.
    targets = []
    for decision in evidence.get("decisions") or []:
        for target in decision.get("targets") or []:
            text = str(target)
            match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
            if match:
                targets.append(match.group(0))
    for scan in evidence.get("portscans") or []:
        if scan.get("ip"):
            targets.append(str(scan["ip"]))
    targets = list(dict.fromkeys(targets))
    if not targets:
        checks.append(
            {
                "id": "target_provenance",
                "passed": True,
                "reason": "Henüz somut hedef IP'si yok; ihlal sayılmaz.",
                "detail": {},
            }
        )
    else:
        unknown = [ip for ip in targets if ip not in facts_ips and ip not in facts_sources]
        checks.append(
            {
                "id": "target_provenance",
                "passed": not unknown,
                "reason": (
                    "Tüm hedefler gerçek kanıt listesinde."
                    if not unknown
                    else f"Kanıtta olmayan hedef IP: {', '.join(unknown[:6])}"
                ),
                "detail": {"targets": targets[:10], "unknown": unknown[:6]},
            }
        )

    # 2) Port coverage: every socket-confirmed open port must be attempted.
    attempted: set[tuple[str, int]] = set()
    for pair in evidence.get("attempted_pairs") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            try:
                attempted.add((str(pair[0]), int(pair[1])))
            except (TypeError, ValueError):
                continue
    # Fallback for callers that only provide the summary list.
    if not attempted:
        for validation in evidence.get("validations") or []:
            host = str(validation.get("host") or "")
            port = validation.get("port")
            if host and isinstance(port, int):
                attempted.add((host, port))
    for publish in evidence.get("published") or []:
        if isinstance(publish, dict):
            host = str(publish.get("host") or "")
            port = publish.get("port")
            if host and isinstance(port, int):
                attempted.add((host, port))
    coverage: list[dict[str, Any]] = []
    for scan in evidence.get("portscans") or []:
        ip = str(scan.get("ip") or "")
        open_ports = [int(port) for port in scan.get("open_ports") or []]
        missing = [port for port in open_ports if (ip, port) not in attempted]
        coverage.append(
            {
                "ip": ip,
                "open_ports": len(open_ports),
                "attempted": len([port for port in open_ports if (ip, port) in attempted]),
                "missing_count": len(missing),
                "missing_sample": missing[:50],
                "scan_source": scan.get("scan_source"),
            }
        )
    if not coverage:
        checks.append(
            {
                "id": "port_coverage",
                "passed": True,
                "reason": "Henüz port taraması çıktısı yok.",
                "detail": {},
            }
        )
    else:
        offenders = [item for item in coverage if item["missing_count"]]
        checks.append(
            {
                "id": "port_coverage",
                "passed": not offenders,
                "reason": (
                    "Açık portların tamamı denendi."
                    if not offenders
                    else "; ".join(
                        f"{item['ip']}: {item['missing_count']} açık port denenmedi"
                        for item in offenders
                    )
                ),
                "detail": {"coverage": coverage},
            }
        )

    # 3) L4 honesty: masscan hits must be socket-confirmed, not silently dropped.
    l4_issues = []
    for scan in evidence.get("portscans") or []:
        reported = int(scan.get("masscan_reported") or 0)
        confirmed = int(scan.get("socket_confirmed_open") or 0)
        if reported and confirmed > reported:
            l4_issues.append(f"{scan.get('ip')}: socket teyidi masscan sayısını aştı")
    checks.append(
        {
            "id": "l4_confirm",
            "passed": not l4_issues,
            "reason": "Masscan sonuçları socket ile tutarlı." if not l4_issues else "; ".join(l4_issues),
            "detail": {},
        }
    )

    # 4) L7 + egress proof.
    egress = []
    for validation in evidence.get("validations") or []:
        for item in validation.get("egress_confirmed") or []:
            egress.append(
                {
                    "host": validation.get("host"),
                    "port": validation.get("port"),
                    "protocol": item.get("protocol"),
                    "egress_ip": item.get("egress_ip"),
                }
            )
    checks.append(
        {
            "id": "l7_egress",
            "passed": bool(egress),
            "reason": (
                f"{len(egress)} gerçek çıkış kanıtı var."
                if egress
                else "Henüz gerçek L7 + çıkış kanıtı yok."
            ),
            "detail": {"egress": egress[:10]},
        }
    )

    # 5) Publish gate: no publish without matching egress proof.
    published = [item for item in evidence.get("published") or [] if isinstance(item, dict)]
    bad_publish = []
    egress_keys = {(str(item["host"]), int(item["port"])) for item in egress if item.get("port")}
    for record in published:
        key = (str(record.get("host") or ""), int(record.get("port") or 0))
        if key not in egress_keys:
            bad_publish.append(f"{key[0]}:{key[1]}")
    checks.append(
        {
            "id": "publish_gate",
            "passed": not bad_publish,
            "reason": (
                "Yayınlanan her uç için eşleşen çıkış kanıtı var."
                if not bad_publish
                else f"Kanıtsız yayın: {', '.join(bad_publish[:6])}"
            ),
            "detail": {"published": len(published)},
        }
    )

    violations = [check for check in checks if not check["passed"]]
    return {
        "checked_at": _utc(),
        "agent_id": evidence.get("agent_id"),
        "attempt_stats": evidence.get("attempt_stats") or {},
        "passed": not violations,
        "checks": checks,
        "violations": [check["id"] for check in violations],
        "summary": (
            "Tüm deterministik şartlar karşılandı."
            if not violations
            else "; ".join(f"{check['id']}: {check['reason']}" for check in violations)
        ),
    }


def observer_digest(evidence: dict[str, Any], conditions: dict[str, Any]) -> dict[str, Any]:
    """Compact, information-dense digest of real evidence for the AI observer.

    The zen endpoint sits behind a 120s Cloudflare proxy read timeout, so the
    prompt must stay small. This digest keeps every real signal and drops bulk.
    """
    decisions = []
    for decision in (evidence.get("decisions") or [])[-6:]:
        decisions.append(
            {
                "seq": decision.get("seq"),
                "at": decision.get("at"),
                "note": str(decision.get("working_note") or "")[:220],
                "hypothesis": str(decision.get("hypothesis") or "")[:160],
                "action": decision.get("action"),
                "tools": (decision.get("requested_tools") or [])[:6],
                "targets": (decision.get("targets") or [])[:6],
            }
        )
    scans = []
    coverage_by_ip: dict[str, Any] = {}
    for check in conditions.get("checks") or []:
        if check.get("id") == "port_coverage":
            for item in (check.get("detail") or {}).get("coverage", []) or []:
                coverage_by_ip[str(item.get("ip"))] = item
            break
    for scan in (evidence.get("portscans") or [])[-5:]:
        coverage = coverage_by_ip.get(str(scan.get("ip"))) or {}
        scans.append(
            {
                "ip": scan.get("ip"),
                "scan_range": scan.get("scan_range"),
                "masscan_reported": scan.get("masscan_reported"),
                "socket_confirmed_open": scan.get("socket_confirmed_open"),
                "candidates": scan.get("candidate_count"),
                "attempted": coverage.get("attempted"),
                "missing": coverage.get("missing_count"),
                "open_sample": (scan.get("open_ports_sample") or [])[:30],
            }
        )
    validations = []
    for validation in (evidence.get("validations") or [])[-5:]:
        validations.append(
            {
                "host": validation.get("host"),
                "port": validation.get("port"),
                "protocols": validation.get("protocols_tried"),
                "egress": validation.get("egress_confirmed"),
            }
        )
    failures = [
        {"tool": event.get("tool"), "error": event.get("error"), "at": event.get("at")}
        for event in (evidence.get("tool_events") or [])
        if event.get("event_type") == "tool_failed"
    ][-8:]
    published = evidence.get("published") or []
    return {
        "agent_id": evidence.get("agent_id"),
        "priority_order": PRIORITY_ORDER,
        "deterministic": {
            "passed": conditions.get("passed"),
            "violations": conditions.get("violations"),
            "checks": [
                {"id": check.get("id"), "passed": check.get("passed"), "reason": str(check.get("reason"))[:220]}
                for check in (conditions.get("checks") or [])
            ],
        },
        "decisions": decisions,
        "portscans": scans,
        "validations": validations,
        "tool_failures": failures,
        "published_count": len(published),
        "published_sample": published[-3:],
    }


HANDOFF_SCHEMA_VERSION = 1


def build_handoff(
    evidence: dict[str, Any],
    conditions: dict[str, Any],
    *,
    ai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Planner-readable handoff artifact. Observer reports, never decides."""
    checks = {check.get("id"): check for check in conditions.get("checks") or []}
    coverage_check = checks.get("port_coverage") or {}
    missing_ports: list[dict[str, Any]] = []
    for item in (coverage_check.get("detail") or {}).get("coverage", []) or []:
        if item.get("missing_count"):
            missing_ports.append(
                {
                    "ip": item.get("ip"),
                    "open_ports": item.get("open_ports"),
                    "attempted": item.get("attempted"),
                    "missing_count": item.get("missing_count"),
                    "missing_sample": item.get("missing_sample") or [],
                    "scan_source": item.get("scan_source"),
                }
            )
    provenance = checks.get("target_provenance") or {}
    unknown_provenance = list((provenance.get("detail") or {}).get("unknown") or [])
    targets = list((provenance.get("detail") or {}).get("targets") or [])
    egress = checks.get("l7_egress") or {}
    egress_list = list((egress.get("detail") or {}).get("egress") or [])
    ai_info = ai or {}
    meta = ai_info.get("meta") or {}
    return {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "written_at": _utc(),
        "agent_id": evidence.get("agent_id"),
        "gate_passed": bool(conditions.get("passed")),
        "violations": list(conditions.get("violations") or []),
        "summary": str(conditions.get("summary") or "")[:1200],
        "target_ips": targets[:20],
        "unknown_provenance": unknown_provenance[:20],
        "missing_ports": missing_ports[:20],
        "l7_egress": {
            "passed": bool(egress.get("passed")),
            "egress_count": len(egress_list),
            "reason": str(egress.get("reason") or "")[:300],
        },
        "checks": [
            {
                "id": check.get("id"),
                "passed": check.get("passed"),
                "reason": str(check.get("reason") or "")[:400],
            }
            for check in conditions.get("checks") or []
        ],
        "attempt_stats": conditions.get("attempt_stats") or {},
        "observer_ai": {
            "ok": bool(ai_info.get("ok")),
            "model_requested": meta.get("model_requested"),
            "model_used": meta.get("model_used") or meta.get("model"),
            "fallback_used": bool(meta.get("fallback_used")),
            "attempts": list(meta.get("attempts") or []),
            "error": str(ai_info.get("error") or "")[:300] or None,
            "verdict": ((ai_info.get("parsed") or {}) if isinstance(ai_info.get("parsed"), dict) else {}).get("verdict"),
        },
        "note": "Observer yalnız rapor üretir; karar planner'a aittir.",
    }


def write_handoff(path: Path, payload: dict[str, Any]) -> None:
    """Atomic append-free handoff write: planner always sees the latest gate state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class Observer:
    """Separate AI observer. Reads evidence, writes JSON reports. Never decides."""

    def __init__(
        self,
        *,
        root: Path = DEFAULT_AGENTD_ROOT,
        client: MuseSparkClient | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.client = client or MuseSparkClient()
        self.agent_id = agent_id
        self.reports_path = self.root / "observer" / "reports.jsonl"
        self.handoff_path = self.root / "observer" / "handoff.json"

    def observe_once(self) -> dict[str, Any]:
        evidence = collect_evidence(self.root, agent_id=self.agent_id)
        conditions = deterministic_conditions(evidence)
        digest = observer_digest(evidence, conditions)
        prompt = json.dumps(digest, ensure_ascii=False, separators=(",", ":"))
        report: dict[str, Any] = {
            "observed_at": _utc(),
            "agent_id": evidence.get("agent_id"),
            "source": "muse-spark-jb",
            "model_requested": self.client.model,
            "prompt_chars": len(prompt),
            "deterministic": conditions,
        }
        error: str | None = None
        content = ""
        messages = [
            {"role": "system", "content": OBSERVER_SYSTEM_PROMPT.format(priority=PRIORITY_ORDER)},
            {"role": "user", "content": prompt},
        ]
        try:
            content = self.client.chat(messages, temperature=0.1)
            error = None
        except Exception as exc:  # noqa: BLE001 - observer must still record the gate result
            error = f"{type(exc).__name__}: {exc}"
        report["ai"] = {
            "ok": error is None,
            "error": error,
            "meta": dict(self.client.last_meta),
            "raw_excerpt": content[:1200] if error else None,
        }
        meta = report["ai"]["meta"]
        report["source"] = meta.get("model_used") or meta.get("model") or self.client.model
        report["model_used"] = report["source"]
        report["model_requested"] = meta.get("model_requested") or self.client.model
        report["fallback_used"] = bool(meta.get("fallback_used"))
        report["zen_attempts"] = list(meta.get("attempts") or [])
        if error is None:
            parsed = _first_json_object(content)
            report["ai"]["parsed"] = parsed
            if parsed is None:
                report["ai"]["ok"] = False
                report["ai"]["error"] = "observer JSON döndürmedi"
            elif "verdict" not in parsed:
                # Schema-shaped answers only. A JSON blob without a verdict is a
                # failed observation, not a successful one.
                report["ai"]["ok"] = False
                report["ai"]["error"] = "observer JSON verdict alanı yok"
        _append_jsonl(self.reports_path, report)
        write_handoff(self.handoff_path, build_handoff(evidence, conditions, ai=report["ai"]))
        return report


def _run(cmd: list[str], *, timeout: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") if isinstance(exc.stdout, str) else "", "timeout"
    except OSError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _probe_claude(binary: str, timeout: float) -> dict[str, Any]:
    code, out, err = _run([binary, "-p", "sadece OK yaz"], timeout=timeout)
    healthy = code == 0 and "OK" in out
    return {
        "name": "claude_code",
        "healthy": healthy,
        "exit_code": code,
        "stdout_excerpt": out.strip()[:200],
        "stderr_excerpt": err.strip()[:200],
    }


def _probe_zen(client: MuseSparkClient, timeout: float) -> dict[str, Any]:
    try:
        client.timeout = timeout
        content = client.chat([{"role": "user", "content": "sadece OK yaz"}])
        meta = dict(client.last_meta)
        return {
            "name": "zen_muse",
            "healthy": "OK" in content,
            "excerpt": content[:200],
            "model_requested": meta.get("model_requested"),
            "model_used": meta.get("model_used") or meta.get("model"),
            "fallback_used": bool(meta.get("fallback_used")),
            "attempts": list(meta.get("attempts") or []),
        }
    except Exception as exc:  # noqa: BLE001
        return {"name": "zen_muse", "healthy": False, "error": f"{type(exc).__name__}: {exc}"}


def _live_agent_pids(root: Path) -> list[int]:
    """Visible running agents whose worker process still exists."""
    data = _read_json(Path(root) / "agents.json", {})
    if not isinstance(data, dict):
        return []
    alive: list[int] = []
    for record in data.values():
        if not isinstance(record, dict):
            continue
        if record.get("visible") is False:
            continue
        if str(record.get("state") or "") in {"killed", "finished", "stopped"}:
            continue
        pid = record.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        alive.append(pid)
    return alive


def _probe_agentd(service: str, stale_seconds: float, events_path: Path) -> dict[str, Any]:
    root = Path(events_path).parent
    code, out, _err = _run(["systemctl", "is-active", service], timeout=15)
    active = code == 0 and out.strip() == "active"
    newest_age = None
    try:
        newest_age = max(0.0, time.time() - events_path.stat().st_mtime)
    except OSError:
        pass
    fresh = newest_age is not None and newest_age <= stale_seconds
    live_pids = _live_agent_pids(root)
    # A quiet event file during a long masscan/port/L7 run is not a hang: if the
    # supervisor is active and a real worker process is alive, do not restart
    # the service and destroy in-flight evidence.
    stale_but_working = bool(active and live_pids and not fresh)
    return {
        "name": "agentd",
        "healthy": bool(active and (fresh or stale_but_working)),
        "service_active": active,
        "event_age_seconds": round(newest_age, 1) if newest_age is not None else None,
        "stale_after_seconds": stale_seconds,
        "live_agent_pids": live_pids[:10],
        "stale_but_working": stale_but_working,
    }


def _pkill_stale_claude(binary_name: str = "claude", older_than: float = 300.0) -> list[int]:
    """Kill hung claude harness processes older than ``older_than`` seconds."""
    code, out, _err = _run(["ps", "-eo", "pid,etimes,comm,args"], timeout=15)
    killed: list[int] = []
    if code != 0:
        return killed
    for line in out.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid_text, etimes_text, comm, args = parts
        if binary_name not in comm and binary_name not in args:
            continue
        if "observer.py" in args:
            continue
        try:
            pid = int(pid_text)
            age = float(etimes_text)
        except ValueError:
            continue
        if age < older_than:
            continue
        try:
            os.kill(pid, 9)
            killed.append(pid)
        except OSError:
            continue
    return killed


class HarnessWatchdog:
    """Process repair only. No code repair, no planner decisions."""

    def __init__(
        self,
        *,
        root: Path = DEFAULT_AGENTD_ROOT,
        service: str = "paidproxy-agentd.service",
        claude_binary: str | None = None,
        stale_seconds: float = 900.0,
        probe_timeout: float = 120.0,
        claude_kill_age: float = 300.0,
        repair_cooldown: float = 60.0,
        client: MuseSparkClient | None = None,
    ) -> None:
        self.root = Path(root)
        self.service = service
        self.claude_binary = claude_binary or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
        self.stale_seconds = stale_seconds
        self.probe_timeout = probe_timeout
        self.claude_kill_age = claude_kill_age
        self.repair_cooldown = repair_cooldown
        self.client = client or MuseSparkClient(timeout=min(probe_timeout, 60.0))
        self.repairs_path = self.root / "observer" / "repairs.jsonl"
        self._last_repair_at = 0.0

    def check_once(self, *, probe_zen: bool = True, deep: bool = False) -> dict[str, Any]:
        """Cheap agentd probe every pass; expensive claude/zen probes only when deep."""
        probes = [_probe_agentd(self.service, self.stale_seconds, self.root / "events.jsonl")]
        if deep:
            probes.append(_probe_claude(self.claude_binary, self.probe_timeout))
        if probe_zen:
            probes.append(_probe_zen(self.client, min(self.probe_timeout, 60.0)))
        unhealthy = [probe for probe in probes if not probe.get("healthy")]
        result: dict[str, Any] = {
            "checked_at": _utc(),
            "service": self.service,
            "probes": probes,
            "healthy": not unhealthy,
            "actions": [],
        }
        if not unhealthy:
            return result
        names = {probe["name"] for probe in unhealthy}
        if "claude_code" in names:
            killed = _pkill_stale_claude("claude", self.claude_kill_age)
            result["actions"].append({"action": "kill_stale_claude", "pids": killed})
        if "agentd" in names:
            since_repair = time.monotonic() - self._last_repair_at
            if self._last_repair_at and since_repair < self.repair_cooldown:
                result["actions"].append(
                    {
                        "action": "restart_service_skipped",
                        "service": self.service,
                        "reason": "repair cooldown",
                        "seconds_since_last_repair": round(since_repair, 1),
                    }
                )
                result["healthy"] = False
                _append_jsonl(self.repairs_path, result)
                return result
            code, out, err = _run(
                ["sudo", "-n", "systemctl", "restart", self.service],
                timeout=60,
            )
            self._last_repair_at = time.monotonic()
            result["actions"].append(
                {
                    "action": "restart_service",
                    "service": self.service,
                    "exit_code": code,
                    "stdout": out.strip()[:200],
                    "stderr": err.strip()[:200],
                }
            )
            deadline = time.monotonic() + 30
            recheck: dict[str, Any] = {}
            while time.monotonic() < deadline:
                recheck = _probe_agentd(self.service, self.stale_seconds, self.root / "events.jsonl")
                if recheck.get("healthy"):
                    break
                time.sleep(1.0)
            result["recheck"] = recheck or _probe_agentd(self.service, self.stale_seconds, self.root / "events.jsonl")
        _append_jsonl(self.repairs_path, result)
        return result

    def watch(self, *, interval: float = 5.0, probe_zen: bool = True, deep_every: int = 10) -> None:
        print(
            f"[watchdog] service={self.service} interval={interval}s deep_every={deep_every}",
            file=sys.stderr,
            flush=True,
        )
        cycle = 0
        while True:
            cycle += 1
            deep = deep_every > 0 and cycle % deep_every == 0
            try:
                result = self.check_once(probe_zen=(probe_zen and deep), deep=deep)
            except Exception as exc:  # noqa: BLE001 - watchdog must survive
                result = {"checked_at": _utc(), "healthy": False, "error": f"{type(exc).__name__}: {exc}"}
            if not result.get("healthy"):
                print("[watchdog] " + json.dumps(result, ensure_ascii=False)[:2000], file=sys.stderr, flush=True)
            time.sleep(interval)


def _default_root() -> Path:
    return Path(os.environ.get("PAIDPROXY_AGENTD_ROOT") or DEFAULT_AGENTD_ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="paidproxy observer agent / condition gate / watchdog")
    parser.add_argument("--root", default=str(_default_root()))
    parser.add_argument("--agent-id", default=os.environ.get("PAIDPROXY_HUNT_AGENT_ID") or None)
    parser.add_argument("--base-url", default=os.environ.get("PAIDPROXY_ZEN_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("PAIDPROXY_ZEN_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("PAIDPROXY_ZEN_TIMEOUT") or DEFAULT_TIMEOUT))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="one AI observation over current evidence")
    mode.add_argument("--watch", action="store_true", help="observe on an interval")
    mode.add_argument("--deterministic-only", action="store_true", help="run only the non-AI gate")
    mode.add_argument("--watchdog", action="store_true", help="harness watchdog mode")
    mode.add_argument("--watchdog-once", action="store_true", help="single watchdog probe/repair pass")
    mode.add_argument("--self-test", action="store_true", help="probe zen + claude + gate, no writes")
    parser.add_argument("--interval", type=float, default=120.0)
    parser.add_argument("--watchdog-interval", type=float, default=5.0)
    parser.add_argument("--service", default=os.environ.get("PAIDPROXY_AGENTD_SERVICE") or "paidproxy-agentd.service")
    parser.add_argument("--stale-seconds", type=float, default=float(os.environ.get("PAIDPROXY_STALE_SECONDS") or 900))
    parser.add_argument("--claude-binary", default=None)
    parser.add_argument("--probe-timeout", type=float, default=120.0)
    parser.add_argument("--deep-every", type=int, default=10, help="run the expensive claude probe every N watchdog cycles")
    parser.add_argument("--repair-cooldown", type=float, default=60.0)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    client = MuseSparkClient(base_url=args.base_url, model=args.model, timeout=args.timeout)

    if args.deterministic_only:
        evidence = collect_evidence(root, agent_id=args.agent_id)
        result = deterministic_conditions(evidence)
        write_handoff(root / "observer" / "handoff.json", build_handoff(evidence, result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1

    if args.self_test:
        evidence = collect_evidence(root, agent_id=args.agent_id)
        result = {
            "zen": _probe_zen(client, min(args.timeout, 60.0)),
            "claude_code": _probe_claude(
                args.claude_binary or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude"),
                args.probe_timeout,
            ),
            "agentd": _probe_agentd(args.service, args.stale_seconds, root / "events.jsonl"),
            "deterministic": deterministic_conditions(evidence),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(
            item.get("healthy", True) for key, item in result.items() if key in {"zen", "claude_code", "agentd"}
        ) else 1

    if args.watchdog:
        watchdog = HarnessWatchdog(
            root=root,
            service=args.service,
            claude_binary=args.claude_binary,
            stale_seconds=args.stale_seconds,
            probe_timeout=args.probe_timeout,
            repair_cooldown=args.repair_cooldown,
            client=client,
        )
        watchdog.watch(interval=args.watchdog_interval, deep_every=args.deep_every)
        return 0

    if args.watchdog_once:
        watchdog = HarnessWatchdog(
            root=root,
            service=args.service,
            claude_binary=args.claude_binary,
            stale_seconds=args.stale_seconds,
            probe_timeout=args.probe_timeout,
            repair_cooldown=args.repair_cooldown,
            client=client,
        )
        result = watchdog.check_once(deep=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["healthy"] else 1

    observer = Observer(root=root, client=client, agent_id=args.agent_id)
    if args.watch:
        while True:
            report = observer.observe_once()
            print(json.dumps(report, ensure_ascii=False)[:2000], file=sys.stderr, flush=True)
            time.sleep(max(10.0, args.interval))

    report = observer.observe_once()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ai"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

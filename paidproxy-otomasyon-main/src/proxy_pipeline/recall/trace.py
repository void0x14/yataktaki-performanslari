"""Ajan iz kaydı: her karar/düşünce append-only iz bırakır, video manifestiyle eşleşir."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

TRACE = Path("var/recall/agent-trace.jsonl")

def emit(pid: str, event: str, thought: str = "", target: str = "") -> Path:
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": datetime.now().isoformat(timespec="seconds"), "pid": pid,
           "event": event, "thought": thought, "target": target}
    with TRACE.open("a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=True) + "\n")
    return TRACE

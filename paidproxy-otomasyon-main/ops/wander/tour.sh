#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python - <<'PYEOF2'
import json
from pathlib import Path
from proxy_pipeline.wander_loop import run_tour
snaps = []
for f in sorted(Path("var/journal").glob("gunluk-*.md"))[-3:]:
    try:
        for satir in f.read_text(encoding="utf-8").splitlines()[-20:]:
            satir = satir.strip()
            if satir.startswith("-"):
                snaps.append({"candidate_id": f"gunluk-{len(snaps)}", "gozlem": satir[-200:]})
    except Exception:
        continue
if not snaps:
    snaps = [{"candidate_id": "bos-tur", "gozlem": "yapay zekâ amaçsız gezintiye çıkıyor"}]
out = run_tour(snaps)
print(json.dumps({"tur": len(out), "sonuc": out}, ensure_ascii=True))
PYEOF2

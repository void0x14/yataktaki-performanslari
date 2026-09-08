#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python -m pytest tests/failure/test_safety.py tests/security -q 2>&1 | tail -2
.venv/bin/python - <<'PYEOF2'
from proxy_pipeline.safety import KillSwitch, RunGate
from proxy_pipeline.scanners.runner import operator_manifest
ks = KillSwitch(); gate = RunGate(ks)
m = operator_manifest("198.51.100.0/24", (8080,))
assert gate.check_manifest(m) is True
ks.trigger("tatbikat")
try:
    gate.check_manifest(m)
    raise SystemExit("HATA: kill sonrası manifest geçti!")
except RuntimeError as e:
    print("kill-drill ok:", e)
PYEOF2

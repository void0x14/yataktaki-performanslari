#!/usr/bin/env bash
set -euo pipefail

ROOT=${PAIDPROXY_ROOT:-/home/mani/paidproxy-otomasyon}
SERVICE_USER=mani
CANONICAL_ROOT=/home/mani/paidproxy-otomasyon
UNIT_SOURCE="$ROOT/ops/systemd/paidproxy-agentd.service"
UNIT_TARGET=/etc/systemd/system/paidproxy-agentd.service
EVIDENCE_SOURCE="$ROOT/ops/systemd/paidproxy-evidence.service"
EVIDENCE_TARGET=/etc/systemd/system/paidproxy-evidence.service
SWAY_CONFIG="$ROOT/config/sway/paidproxy-headless.conf"

if [[ ! -d "$ROOT" ]]; then
  echo "paidproxy root missing: $ROOT" >&2
  exit 2
fi
if [[ "$ROOT" != "$CANONICAL_ROOT" ]]; then
  echo "PAIDPROXY_ROOT must be $CANONICAL_ROOT because installed units use the canonical VDS checkout" >&2
  exit 2
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "service user missing: $SERVICE_USER" >&2
  exit 2
fi
if [[ ! -f "$UNIT_SOURCE" ]]; then
  echo "agentd unit missing: $UNIT_SOURCE" >&2
  exit 2
fi
if [[ ! -f "$EVIDENCE_SOURCE" ]]; then
  echo "evidence unit missing: $EVIDENCE_SOURCE" >&2
  exit 2
fi
if [[ ! -f "$SWAY_CONFIG" ]]; then
  echo "Sway headless config missing: $SWAY_CONFIG" >&2
  exit 2
fi
if [[ ! -f "$ROOT/services/agentd/__main__.py" ]]; then
  echo "agentd code missing: $ROOT/services/agentd/__main__.py" >&2
  exit 2
fi

install -d -m 0700 "$ROOT/var/agentd" "$ROOT/var/agentd/agents"
chown -R "$SERVICE_USER:$SERVICE_USER" "$ROOT/var/agentd"

install -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
install -m 0644 "$EVIDENCE_SOURCE" "$EVIDENCE_TARGET"
systemctl daemon-reload
systemctl enable paidproxy-evidence.service
systemctl enable paidproxy-agentd.service
systemctl restart paidproxy-evidence.service || true
systemctl restart paidproxy-agentd.service
systemctl is-active --quiet paidproxy-agentd.service
systemctl --no-pager --full status paidproxy-agentd.service
if ! systemctl is-active --quiet paidproxy-evidence.service; then
  echo "UYARI: paidproxy-evidence.service aktif değil; agentd sahte kanıt üretmeyecek." >&2
fi
ss -ltn '( sport = :8787 )'

#!/usr/bin/env bash
# Read-only VDS envanter. Tarama YOK, yazma YOK.
set -euo pipefail
HOST="${VDS_HOST:-20.207.198.170}"
USER="${VDS_USER:-mani}"
KEY="${VDS_KEY:-$HOME/.ssh/paidproxy_vds}"
ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$USER@$HOST" '
echo "== uname =="; uname -a
echo "== os =="; cat /etc/os-release | head -5
echo "== cpu/mem =="; nproc; free -h | head -2
echo "== masscan =="; which masscan || echo masscan-yok
echo "== python =="; python3 --version
'

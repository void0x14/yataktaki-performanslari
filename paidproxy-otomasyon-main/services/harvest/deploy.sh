#!/usr/bin/env bash
# Harvest boru hattını VDS'e dağıt — tek komutla kurulum.
# Kullanım: bash services/harvest/deploy.sh
set -euo pipefail

VDS="mani@20.207.198.170"
KEY="$HOME/.ssh/paidproxy_vds"
REMOTE_DIR="/home/mani/harvest"

echo "=== 1/4: Paket gönderimi ==="
ssh -i "$KEY" -o ConnectTimeout=20 "$VDS" "mkdir -p $REMOTE_DIR/var/harvest $REMOTE_DIR/var/teslim"
scp -i "$KEY" -o ConnectTimeout=20 \
  services/harvest/__init__.py \
  services/harvest/ripe.py \
  services/harvest/classify.py \
  services/harvest/checker.py \
  services/harvest/pipeline.py \
  services/harvest/status.py \
  "$VDS:$REMOTE_DIR/"

echo "=== 2/4: Yerleştirme + dizinler ==="
ssh -i "$KEY" "$VDS" "
  chmod +x $REMOTE_DIR/pipeline.py
  which masscan >/dev/null || echo 'UYARI: masscan yok — sudo apt install -y masscan'
  python3 -c 'import ast; [ast.parse(open(f).read()) for f in [\"$REMOTE_DIR/ripe.py\",\"$REMOTE_DIR/classify.py\",\"$REMOTE_DIR/pipeline.py\"]]; print(\"uzak sözdizimi OK\")'
"

echo "=== 3/4: systemd birimi ==="
ssh -i "$KEY" "$VDS" "
  cat | sudo tee /etc/systemd/system/harvest.service >/dev/null
" <<'UNIT'
[Unit]
Description=Harvest otonom proxy hasat boru hattı
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mani
WorkingDirectory=/home/mani/harvest
ExecStart=/usr/bin/python3 /home/mani/harvest/pipeline.py --countries TR DE RU CN BR US UA IN --rate 4000
Restart=always
RestartSec=15
Nice=10
# masscan için raw socket — setcap ile sudo'suz
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
UNIT

echo "=== 4/4: Aktivasyon ==="
ssh -i "$KEY" "$VDS" "
  sudo setcap cap_net_raw,cap_net_admin+eip \$(readlink -f \$(which masscan)) 2>/dev/null || true
  sudo systemctl daemon-reload
  sudo systemctl enable --now harvest.service
  sleep 2
  sudo systemctl status harvest.service --no-pager | head -12
"
echo "=== TAMAM: harvest.service VDS'te 7/24 çalışıyor ==="

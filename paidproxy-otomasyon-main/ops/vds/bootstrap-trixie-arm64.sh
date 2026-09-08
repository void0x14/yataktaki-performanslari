#!/usr/bin/env bash
# VDS (Debian 13 trixie, arm64) worker kurulumu. VDS ÜSTÜNDE çalıştır.
# AI agentd ve gerçek Sway headless/wayvnc kanıt yüzeyi. Operasyon VDS'te yürür.
set -euo pipefail
echo "== trixie/arm64 kontrol =="
uname -m | grep -q aarch64 || { echo "BEKLENEN: aarch64"; uname -m; }
grep -q trixie /etc/os-release || { echo "UYARI: trixie değil"; cat /etc/os-release | head -3; }
sudo apt update
sudo apt install -y masscan python3 python3-venv python3-pip git ffmpeg sway wayvnc grim wf-recorder foot
which masscan; masscan --version || true
if [ ! -d ~/paidproxy-otomasyon ]; then
  echo "NOT: repo'yu VDS'e klonla ya da rsync'le (bu script repo içinden kopyalanır)."
fi
python3 -m pip install --user -e ".[dev]" 2>/dev/null || pip install --user -e ".[dev]" || true
if [[ -x "$PWD/ops/vds/install-agentd.sh" ]]; then
  sudo env PAIDPROXY_ROOT="$PWD" "$PWD/ops/vds/install-agentd.sh"
else
  echo "NOT: repo kökünde ops/vds/install-agentd.sh bulunamadı; agentd kurulumu ayrıca çalıştırılmalı."
fi
echo "OK. VDS agentd ve gerçek Sway headless/wayvnc kanıt servisi için kurulum tamamlandı."

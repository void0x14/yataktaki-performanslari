#!/usr/bin/env bash
# Bir kerelik VDS anahtar kurulumu. Şifreyi SORAR, SAKLAMAZ, loglamaz.
set -euo pipefail
HOST="${VDS_HOST:-20.207.198.170}"
USER="${VDS_USER:-mani}"
KEY="${VDS_KEY:-$HOME/.ssh/paidproxy_vds}"
echo "== PaidProxy VDS key setup =="
echo "Hedef: $USER@$HOST"
echo "Anahtar: $KEY"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -f "$KEY" -N "" -C "paidproxy-desktop"
echo "--- VDS şifreni YALNIZCA bu ssh-copy-id adımında yazacaksın, hiçbir dosyaya kaydedilmeyecek ---"
ssh-copy-id -i "$KEY.pub" "$USER@$HOST"
echo "--- prob (BatchMode, şifresiz) ---"
ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$USER@$HOST" "uname -m; head -3 /etc/os-release; which masscan || echo masscan-yok"
echo "OK. Bundan sonra desktop key ile bağlanır."

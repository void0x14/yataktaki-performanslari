#!/bin/bash
# PaidProxy Operasyon Kokpiti - tek tikla acilir.
# Once gerekiyorsa arka sunucuyu baslatir, sonra pencereyi acar.
KOK="/home/void0x14/Belgeler/paidproxy-otomasyon-main"
if ! ss -tln 2>/dev/null | grep -q "127.0.0.1:1420"; then
  cd "$KOK" && (nohup npx vite --host 127.0.0.1 > /tmp/vite1420.log 2>&1 &) 
  for i in $(seq 1 30); do
    ss -tln 2>/dev/null | grep -q "127.0.0.1:1420" && break
    sleep 1
  done
fi
exec "$KOK/cockpit/src-tauri/target/debug/paidproxy-cockpit"

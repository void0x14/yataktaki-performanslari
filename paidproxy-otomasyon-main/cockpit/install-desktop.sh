#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/cockpit/src-tauri/target/debug/paidproxy-cockpit"
if [[ ! -x "$BIN" ]]; then
  printf 'PaidProxy binary bulunamadı. Önce cockpit/src-tauri içinde Tauri build çalıştırılmalı.\n' >&2
  exit 1
fi
mkdir -p "$HOME/.local/share/applications"
rm -f "$HOME/.local/share/applications/paidproxy.desktop"
cat > "$HOME/.local/share/applications/paidproxy-cockpit.desktop" <<ENTRY
[Desktop Entry]
Name=PaidProxy Operasyon Kokpiti
Comment=PaidProxy VDS operasyon kokpiti
Exec=$BIN
Path=$ROOT/cockpit
Terminal=false
Type=Application
Categories=Utility;Network;
StartupWMClass=paidproxy-cockpit
ENTRY
printf 'PaidProxy uygulama menüsüne kuruldu: PaidProxy Operasyon Kokpiti\n'

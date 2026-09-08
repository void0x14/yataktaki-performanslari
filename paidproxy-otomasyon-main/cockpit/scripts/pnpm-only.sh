#!/usr/bin/env sh
set -eu

runner="${npm_config_user_agent:-} ${npm_execpath:-}"
case "$runner" in
  *pnpm*) ;;
  *)
    printf '%s\n' 'HATA: Bu proje yalnızca pnpm/pnpx ile çalışır. npm/npx engellendi.' >&2
    exit 86
    ;;
esac

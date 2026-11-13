#!/bin/sh
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$root"
fail() { printf '%s\n' "$1" >&2; exit 64; }
build_image=1
case "$#:${1:-}" in
  0:) ;;
  1:--no-build) build_image=0 ;;
  *) fail 'Usage: sh scripts/deploy.sh [--no-build]' ;;
esac
[ "$(id -u)" = 0 ] || fail 'Run with sudo: sh scripts/deploy.sh'
command -v docker >/dev/null 2>&1 || fail 'Docker is required'
command -v openssl >/dev/null 2>&1 || fail 'OpenSSL is required'
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required to read resolved Compose configuration safely'
docker compose version >/dev/null
[ ! -L .env ] || fail '.env must be a regular local file'
if [ ! -f .env ]; then
  cp .env.example .env
  printf 'Created .env. Set TURN_REALM and TURN_PUBLIC_IP, then run again.\n'
  exit 64
fi
[ -f .env ] || fail '.env must be a regular local file'
if grep -q REPLACE_WITH_ .env; then
  fail 'Replace placeholder values in .env before deployment'
fi
for directory in secrets certs; do
  [ ! -L "$directory" ] || fail 'Runtime directories must not be symlinks'
  mkdir -p "$directory"
  [ -d "$directory" ] || fail 'Runtime paths must be directories'
done
[ ! -L secrets/turn-password ] || fail 'Password file must not be a symlink'
if [ -e secrets/turn-password ] && [ ! -f secrets/turn-password ]; then
  fail 'Password file must be a regular file'
fi
if [ -e secrets/turn-password ] && [ ! -s secrets/turn-password ]; then
  fail 'An empty password file exists; remove it or provide a valid password'
fi
if [ ! -e secrets/turn-password ]; then
  temporary=$(mktemp secrets/.password.XXXXXX)
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  openssl rand -base64 36 >"$temporary"
  mv -n "$temporary" secrets/turn-password
  rm -f "$temporary"
  trap - EXIT HUP INT TERM
  printf 'Generated local private password file; its value was not printed.\n'
fi
chown 65534:65534 secrets secrets/turn-password
chmod 700 secrets
chmod 600 secrets/turn-password .env
docker compose -f compose.yaml config --quiet
# Read resolved data as JSON; never source .env as shell code. Compose handles
# quoted dotenv values and environment overrides consistently with deployment.
tls_enable=$(docker compose -f compose.yaml config --format json | python3 -c '
import json,sys
value=str(json.load(sys.stdin)["services"]["turn"]["environment"].get("TURN_TLS_ENABLE","0"))
if value not in ("0","1"): raise SystemExit("TURN_TLS_ENABLE must be 0 or 1")
print(value)
')
set -- -f compose.yaml
if [ "$tls_enable" = 1 ]; then
  set -- "$@" -f compose.tls.yaml
fi
docker compose "$@" config --quiet
if [ "$build_image" = 1 ]; then
  docker compose "$@" build turn
fi
docker compose "$@" run --rm --no-deps turn --validate-only
docker compose "$@" up -d --no-build --force-recreate turn
docker compose "$@" ps turn
printf 'Relay deployed. Configure the same account in your clients.\n'

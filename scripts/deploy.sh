#!/bin/sh
set -eu
umask 077
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$root"
fail() { printf '%s\n' "$1" >&2; exit 64; }
[ "$(id -u)" = 0 ] || fail 'Run with sudo: sh scripts/deploy.sh'
command -v docker >/dev/null 2>&1 || fail 'Docker is required'
command -v openssl >/dev/null 2>&1 || fail 'OpenSSL is required'
docker compose version >/dev/null
[ ! -L .env ] || fail '.env must be a regular local file'
if [ ! -f .env ]; then
  cp .env.example .env
  printf 'Created .env. Set TURN_REALM and TURN_PUBLIC_IP, then run again.\n'
  exit 64
fi
if grep -q REPLACE_WITH_ .env; then
  fail 'Replace placeholder values in .env before deployment'
fi
for directory in secrets certs; do
  [ ! -L "$directory" ] || fail 'Runtime directories must not be symlinks'
  mkdir -p "$directory"
done
[ ! -L secrets/turn-password ] || fail 'Password file must not be a symlink'
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
docker compose config --quiet
docker compose build turn
docker compose run --rm --no-deps turn --validate-only
docker compose up -d --force-recreate turn
docker compose ps turn
printf 'Relay deployed. Configure the same account in your clients.\n'

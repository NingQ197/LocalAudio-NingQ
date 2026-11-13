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
  printf 'Created .env. Set TURN_REALM and the public IP for the selected TURN_IP_MODE, then run again.\n'
  exit 64
fi
[ -f .env ] || fail '.env must be a regular local file'
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
settings=$(docker compose -f compose.yaml config --format json | python3 -c '
import json,sys
env=json.load(sys.stdin)["services"]["turn"]["environment"]
tls=str(env.get("TURN_TLS_ENABLE","0"))
mode=str(env.get("TURN_IP_MODE","ipv4"))
if tls not in ("0","1"): raise SystemExit("TURN_TLS_ENABLE must be 0 or 1")
if mode not in ("ipv4","dual","ipv6"): raise SystemExit("TURN_IP_MODE must be ipv4, dual or ipv6")
required=["TURN_REALM"]
if mode!="ipv6": required.append("TURN_PUBLIC_IP")
if mode!="ipv4": required.append("TURN_PUBLIC_IPV6")
for key in required:
    value=str(env.get(key,""))
    if not value or "REPLACE_WITH_" in value: raise SystemExit("Set "+key+" before deployment")
print(tls+" "+mode)
')
tls_enable=${settings%% *}
ip_mode=${settings#* }
set -- -f compose.yaml
if [ "$ip_mode" != ipv4 ]; then
  set -- "$@" -f compose.ipv6.yaml
fi
if [ "$ip_mode" = ipv6 ]; then
  set -- "$@" -f compose.ipv6only.yaml
fi
if [ "$tls_enable" = 1 ]; then
  if [ "$ip_mode" != ipv6 ]; then set -- "$@" -f compose.tls.yaml; fi
  if [ "$ip_mode" != ipv4 ]; then set -- "$@" -f compose.tls.ipv6.yaml; fi
fi
docker compose "$@" config --quiet
if [ "$build_image" = 1 ]; then
  # Finish the build before an IPv6 network migration can interrupt the relay.
  docker compose "$@" build turn
fi
if [ "$ip_mode" != ipv4 ]; then
  network_recreate=$(docker compose "$@" config --format json | python3 -c '
import ipaddress,json,re,subprocess,sys
project=json.load(sys.stdin)
network=project["networks"]["default"]
name=network["name"]
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",name): raise SystemExit("Invalid project network name")
subnets=[ipaddress.ip_network(row["subnet"],strict=True) for row in network.get("ipam",{}).get("config",[]) if "subnet" in row]
v6=[row for row in subnets if row.version==6]
if len(v6)!=1 or v6[0].prefixlen!=64 or not v6[0].subnet_of(ipaddress.ip_network("fc00::/7")):
    raise SystemExit("TURN_DOCKER_IPV6_SUBNET must be a ULA /64")
p=subprocess.run(["docker","network","inspect",name],capture_output=True,text=True)
if p.returncode:
    if "not found" in p.stderr.lower() or "no such network" in p.stderr.lower(): raise SystemExit(0)
    raise SystemExit("Cannot inspect the project Docker network")
rows=json.loads(p.stdout)
if not rows: raise SystemExit(0)
current=rows[0]
existing=[ipaddress.ip_network(row["Subnet"],strict=True) for row in current.get("IPAM",{}).get("Config",[]) if row.get("Subnet")]
if (current.get("Labels") or {}).get("com.docker.compose.project")!=project["name"]:
    raise SystemExit("Refusing to replace a Docker network outside this Compose project")
if current.get("EnableIPv6") and v6[0] in existing: raise SystemExit(0)
for identifier in current.get("Containers",{}):
    probe=subprocess.run(["docker","inspect",identifier],capture_output=True,text=True)
    if probe.returncode: raise SystemExit("Cannot verify an attached network container")
    labels=json.loads(probe.stdout)[0].get("Config",{}).get("Labels",{}) or {}
    if labels.get("com.docker.compose.project")!=project["name"] or labels.get("com.docker.compose.service")!="turn" or str(labels.get("com.docker.compose.oneoff","true")).lower()!="false":
        raise SystemExit("The network has other services attached; refusing automatic replacement")
print(name)
')
  if [ -n "$network_recreate" ]; then
    printf 'Recreating this relay project network for IPv6; current relay connections will disconnect.\n'
    docker compose "$@" stop turn
    docker compose "$@" rm -f turn
    docker network rm "$network_recreate"
  fi
fi
docker compose "$@" run --rm --no-deps turn --validate-only
docker compose "$@" up -d --no-build --force-recreate turn
docker compose "$@" ps turn
printf 'Relay deployed. Configure the same account in your clients.\n'

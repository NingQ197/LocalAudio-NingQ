#!/bin/sh
set -eu
umask 077
fail() { printf 'TURN configuration error: %s\n' "$1" >&2; exit 64; }
case "$#" in
  0) ;;
  1) [ "$1" = '--validate-only' ] || fail 'arbitrary coturn command-line flags are disabled';;
  *) fail 'arbitrary coturn command-line flags are disabled';;
esac
valid_ipv4() {
  case "$1" in ''|*[!0-9.]*) return 1;; esac
  printf '%s\n' "$1" | awk -F. 'NF!=4{exit 1} {for(i=1;i<=4;i++){if($i !~ /^[0-9]+$/ || length($i)>3 || $i+0>255 || (length($i)>1 && substr($i,1,1)=="0"))exit 1}}'
}
public_ipv4() {
  valid_ipv4 "$1" || return 1
  printf '%s\n' "$1" | awk -F. '
    $1==0 || $1==10 || $1==127 || $1>=224 {exit 1}
    $1==100 && $2>=64 && $2<=127 {exit 1}
    $1==169 && $2==254 {exit 1}
    $1==172 && $2>=16 && $2<=31 {exit 1}
    $1==192 && ($2==168 || ($2==0 && ($3==0 || $3==2)) || ($2==88 && $3==99)) {exit 1}
    $1==198 && (($2==18 || $2==19) || ($2==51 && $3==100)) {exit 1}
    $1==203 && $2==0 && $3==113 {exit 1}'
}
number() {
  case "$2" in ''|*[!0-9]*) fail "$1 must be an integer";; esac
  [ "$2" = "${2#0}" ] || [ "$2" = 0 ] || fail "$1 must not have leading zeros"
  [ "${#2}" -le 9 ] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] || fail "$1 is outside its allowed range"
}
strong_secret() {
  [ "${#2}" -ge "$3" ] && [ "${#2}" -le 256 ] || fail "$1 is too short or too long"
  case "$2" in *[!A-Za-z0-9_+/=-]*) fail "$1 must contain only base64/hex/password-safe characters";; esac
  unique=$(printf '%s' "$2" | fold -w1 | sort -u | wc -l)
  [ "$unique" -ge 8 ] || fail "$1 has an obvious low-diversity placeholder value"
  case "$2" in *CHANGE*|*change-me*|*REPLACE*|*replace-me*) fail "$1 still contains a placeholder";; esac
}
realm=${TURN_REALM:-}
case "$realm" in ''|*[!A-Za-z0-9.-]*) fail 'TURN_REALM must be an explicit DNS-style realm';; esac
[ "${#realm}" -le 253 ] || fail 'TURN_REALM is too long'
printf '%s\n' "$realm" | awk -F. '{for(i=1;i<=NF;i++) if(length($i)<1 || length($i)>63 || $i ~ /^-/ || $i ~ /-$/) exit 1}' || fail 'TURN_REALM contains an invalid DNS label'
public=${TURN_PUBLIC_IP:-}
public_ipv4 "$public" || fail 'TURN_PUBLIC_IP must be an explicit globally routable IPv4 address (documentation/private addresses are rejected)'
port=${TURN_PORT:-21113}
tls_port=${TURN_TLS_PORT:-5349}
min=${TURN_MIN_PORT:-49160}
max=${TURN_MAX_PORT:-49200}
number TURN_PORT "$port" 1024 65535
number TURN_TLS_PORT "$tls_port" 1024 65535
number TURN_MIN_PORT "$min" 1024 65535
number TURN_MAX_PORT "$max" "$min" 65535
[ "$port" != "$tls_port" ] || fail 'TURN_PORT and TURN_TLS_PORT must differ'
[ $((max-min)) -le 8191 ] || fail 'relay port range exceeds 8192 ports'
[ "$port" -lt "$min" ] || [ "$port" -gt "$max" ] || fail 'TURN_PORT overlaps the relay range'
[ "$tls_port" -lt "$min" ] || [ "$tls_port" -gt "$max" ] || fail 'TURN_TLS_PORT overlaps the relay range'
quota=${TURN_USER_QUOTA:-16}
total=${TURN_TOTAL_QUOTA:-128}
max_bps=${TURN_MAX_BPS:-12000000}
capacity=${TURN_BPS_CAPACITY:-100000000}
number TURN_USER_QUOTA "$quota" 1 10000
number TURN_TOTAL_QUOTA "$total" 1 100000
number TURN_MAX_BPS "$max_bps" 10000 999999999
number TURN_BPS_CAPACITY "$capacity" 10000 999999999
# Select an actual local interface address, never a wildcard relay address.
# A wildcard public/private mapping turns same-server relay peers into 0.0.0.0.
local_ipv4s=$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) print $i}')
[ -n "$local_ipv4s" ] || fail 'no local IPv4 relay interface was found'
relay=${TURN_RELAY_IP:-$(printf '%s\n' "$local_ipv4s" | head -n1)}
valid_ipv4 "$relay" || fail 'TURN_RELAY_IP must be a concrete local IPv4 interface address'
case "$relay" in 0.*|127.*|169.254.*) fail 'TURN_RELAY_IP cannot be wildcard, loopback or link-local';; esac
printf '%s\n' "$local_ipv4s" | grep -Fx -- "$relay" >/dev/null || fail 'TURN_RELAY_IP does not belong to this container network namespace'
runtime=/tmp/ts3-turn
mkdir -p "$runtime"
config=$runtime/turnserver.conf
{
  printf 'realm=%s\nlistening-ip=0.0.0.0\nlistening-port=%s\nmin-port=%s\nmax-port=%s\n' "$realm" "$port" "$min" "$max"
  printf 'relay-ip=%s\nexternal-ip=%s/%s\n' "$relay" "$public" "$relay"
  # Coturn decodes a peer's public relay candidate back to its local relay IP.
  # This exact own-container exception permits same-server allocations to talk,
  # without allowing any other RFC1918 / Docker-host / metadata destination.
  printf 'allowed-peer-ip=%s\n' "$relay"
  printf 'fingerprint\nno-multicast-peers\nno-tcp-relay\nno-auth-pings\nstale-nonce=600\nmax-allocate-lifetime=3600\nmax-allocate-timeout=30\n'
  printf 'user-quota=%s\ntotal-quota=%s\nmax-bps=%s\nbps-capacity=%s\n' "$quota" "$total" "$max_bps" "$capacity"
  printf 'log-file=stdout\nsimple-log\npidfile=%s/turnserver.pid\n' "$runtime"
  cat /opt/ts3-relay/denied-peers.conf
} >"$config"
mode=${TURN_AUTH_MODE:-static}
case "$mode" in
  secret)
    [ -z "${TURN_USERNAME:-}${TURN_PASSWORD:-}${TURN_PASSWORD_FILE:-}" ] || fail 'static credentials cannot be combined with secret mode'
    [ -z "${TURN_SHARED_SECRET:-}" ] || [ -z "${TURN_SHARED_SECRET_FILE:-}" ] || fail 'set either TURN_SHARED_SECRET or TURN_SHARED_SECRET_FILE'
    secret=${TURN_SHARED_SECRET:-}
    if [ -n "${TURN_SHARED_SECRET_FILE:-}" ]; then
      [ -f "$TURN_SHARED_SECRET_FILE" ] && [ -r "$TURN_SHARED_SECRET_FILE" ] || fail 'TURN_SHARED_SECRET_FILE must be a readable regular file'
      secret=$(head -c 513 "$TURN_SHARED_SECRET_FILE")
    fi
    strong_secret TURN_SHARED_SECRET "$secret" 32
    printf 'use-auth-secret\nstatic-auth-secret=%s\n' "$secret" >>"$config"
    ;;
  static)
    [ -z "${TURN_SHARED_SECRET:-}${TURN_SHARED_SECRET_FILE:-}" ] || fail 'shared secret cannot be combined with static mode'
    username=${TURN_USERNAME:-}
    case "$username" in ''|*[!A-Za-z0-9._-]*) fail 'TURN_USERNAME is required and must be ASCII letters, digits, dot, underscore or hyphen';; esac
    [ "${#username}" -le 64 ] || fail 'TURN_USERNAME is too long'
    [ -z "${TURN_PASSWORD:-}" ] || [ -z "${TURN_PASSWORD_FILE:-}" ] || fail 'set either TURN_PASSWORD or TURN_PASSWORD_FILE'
    password=${TURN_PASSWORD:-}
    if [ -n "${TURN_PASSWORD_FILE:-}" ]; then
      [ -f "$TURN_PASSWORD_FILE" ] && [ -r "$TURN_PASSWORD_FILE" ] || fail 'TURN_PASSWORD_FILE must be a readable regular file'
      password=$(head -c 513 "$TURN_PASSWORD_FILE")
    fi
    strong_secret TURN_PASSWORD "$password" 24
    printf 'lt-cred-mech\nuser=%s:%s\n' "$username" "$password" >>"$config"
    ;;
  *) fail 'TURN_AUTH_MODE must be secret or static (anonymous access is not available)';;
esac
case "${TURN_TLS_ENABLE:-0}" in
  0) printf 'no-tls\n' >>"$config";;
  1)
    cert=${TURN_TLS_CERT_FILE:-/certs/fullchain.pem}
    key=${TURN_TLS_KEY_FILE:-/certs/privkey.pem}
    case "$cert$key" in *[!A-Za-z0-9_./-]*) fail 'TLS file paths contain unsupported characters';; esac
    [ -f "$cert" ] && [ -f "$key" ] && [ -r "$cert" ] && [ -r "$key" ] || fail 'TURN TLS certificate/key must be regular files readable by UID 65534'
    openssl x509 -in "$cert" -checkend 0 -noout >/dev/null 2>&1 || fail 'TLS certificate is invalid or expired'
    # POSIX sh does not have pipefail: check each extraction independently so
    # two failed parsers cannot appear equal as the SHA256 of empty input.
    openssl x509 -in "$cert" -pubkey -noout >"$runtime/cert-public.pem" 2>/dev/null || fail 'TLS certificate public key could not be read'
    openssl pkey -pubin -in "$runtime/cert-public.pem" -outform DER >"$runtime/cert-public.der" 2>/dev/null || fail 'TLS certificate public key is invalid'
    openssl pkey -in "$key" -passin pass: -pubout -outform DER >"$runtime/key-public.der" 2>/dev/null || fail 'TLS private key is invalid or encrypted'
    cmp -s "$runtime/cert-public.der" "$runtime/key-public.der" || fail 'TLS certificate and private key do not match'
    rm -f "$runtime/cert-public.pem" "$runtime/cert-public.der" "$runtime/key-public.der"
    printf 'tls-listening-port=%s\ncert=%s\npkey=%s\n' "$tls_port" "$cert" "$key" >>"$config"
    ;;
  *) fail 'TURN_TLS_ENABLE must be 0 or 1';;
esac
chmod 600 "$config"
# CLI, web admin, DTLS, RFC5780 and anonymous TURN are never enabled.
# Do not log the config: it contains a credential secret.
if [ "${1:-}" = '--validate-only' ]; then
  printf 'TURN configuration valid; authentication=%s; TLS=%s; relay range=%s-%s\n' "$mode" "${TURN_TLS_ENABLE:-0}" "$min" "$max"
  exit 0
fi
exec /usr/bin/turnserver -c "$config"


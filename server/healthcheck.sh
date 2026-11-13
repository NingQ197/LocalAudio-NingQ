#!/bin/sh
set -eu
case "${TURN_IP_MODE:-ipv4}" in
  ipv4) /usr/bin/turnutils_stunclient -p "${TURN_PORT:-21113}" 127.0.0.1 >/dev/null 2>&1;;
  dual)
    /usr/bin/turnutils_stunclient -p "${TURN_PORT:-21113}" 127.0.0.1 >/dev/null 2>&1
    /usr/bin/turnutils_stunclient -p "${TURN_PORT:-21113}" ::1 >/dev/null 2>&1;;
  ipv6) /usr/bin/turnutils_stunclient -p "${TURN_PORT:-21113}" ::1 >/dev/null 2>&1;;
  *) exit 1;;
esac

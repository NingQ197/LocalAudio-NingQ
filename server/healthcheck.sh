#!/bin/sh
set -eu
exec /usr/bin/turnutils_stunclient -p "${TURN_PORT:-21113}" 127.0.0.1 >/dev/null 2>&1

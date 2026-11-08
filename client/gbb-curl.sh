#!/usr/bin/env sh
# Pure-curl client (no Python needed on the calling side).
#   ./gbb-curl.sh '{"cmd":"get_page"}'
#   ./gbb-curl.sh status
# The token is read from the config file and passed to curl in a mode-600
# config file. It is not placed on the curl command line (where ps would show it).
CFG="${HOME}/.bot-bridge/config.json"
[ -f "$CFG" ] || CFG="${HOME}/.grok-chrome-bridge/config.json"
TOKEN="${GBB_TOKEN:-$(sed -n 's/.*"token": *"\([^"]*\)".*/\1/p' "$CFG")}"
PORT="${GBB_PORT:-$(sed -n 's/.*"port": *\([0-9]*\).*/\1/p' "$CFG")}"
PORT="${PORT:-8765}"
umask 077
HDR="$(mktemp "${TMPDIR:-/tmp}/gbb-curl.XXXXXX")"
cleanup() { rm -f "$HDR"; }
trap cleanup EXIT INT TERM
{
  printf 'header = "X-Token: %s"\n' "$TOKEN"
  printf 'header = "Content-Type: application/json"\n'
  printf 'silent\n'
} > "$HDR"
if [ "${1:-}" = "status" ]; then
  curl --config "$HDR" "http://127.0.0.1:${PORT}/status"
else
  curl --config "$HDR" -X POST "http://127.0.0.1:${PORT}/command" --data "${1:-}"
fi
rc=$?
cleanup
trap - EXIT INT TERM
exit "$rc"

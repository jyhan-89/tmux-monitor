#!/bin/sh
event="${1:-unknown}"
input=$(cat)
url="${TMUX_WEB_URL:-http://127.0.0.1:8765/dev}"
token="${TMUX_WEB_HOOK_TOKEN:-}"
if [ -z "$token" ]; then
  token_file="${TMUX_WEB_CONFIG:-$HOME/.config/tmux-web}/company/secrets/hook.token"
  [ -r "$token_file" ] && token=$(cat "$token_file")
fi
session="${TMUX_WEB_SESSION:-}"
if [ -z "$session" ] && [ -n "$TMUX" ]; then
  if [ -n "${TMUX_PANE:-}" ]; then
    session=$(tmux display-message -p -t "$TMUX_PANE" '#S' 2>/dev/null)
  else
    session=$(tmux display-message -p '#S' 2>/dev/null)
  fi
fi
[ -n "$token" ] && [ -n "$session" ] || exit 0
case "$input" in
  \{*) data="$input" ;;
  *) data='{}' ;;
esac
session=$(printf '%s' "$session" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf '{"session":"%s","event":"%s","data":%s}' "$session" "$event" "$data" |
  curl -s -o /dev/null --max-time 2 -X POST -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" --data-binary @- "$url/api/event" >/dev/null 2>&1 &
exit 0

#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
W=${1:?작업 폴더}
PORT=${PORT:-8799}
TDIR=$(mktemp -d /tmp/claude-1000/twXXXX 2>/dev/null || mktemp -d /tmp/twXXXX)
rm -rf "$W" && mkdir -p "$W/cfg/company" "$W/data" "$W/repo"
SOCK="$TDIR/tmux-$(id -u)/default"
git -C "$W/repo" init -q -b main && git -C "$W/repo" commit -q --allow-empty -m init
python3 - "$ROOT" "$W" <<'PY'
import sys, yaml
from pathlib import Path
root, w = Path(sys.argv[1]), Path(sys.argv[2])
sample = root / "company/examples/mw-minimal"
org = yaml.safe_load((sample / "org.yaml").read_text())
org["divisions"]["mw"].update(template="mini", repo=str(w / "repo"))
(w / "cfg/company/org.yaml").write_text(yaml.safe_dump(org, allow_unicode=True))
(w / "cfg/company/documents.yaml").write_text((sample / "documents.yaml").read_text())
(w / "cfg/company/process.yaml").write_text("""version: 1
templates:
  mini:
    start: implement
    nodes:
      implement: {role: impl, parallel: true, retry: 1, gate: gates/common/has_new_commit.sh, next: review, on_fail: analyze}
      review: {role: reviewer, gate: gates/common/review_approved.sh, next: done, on_fail: analyze}
      analyze: {role: analysis, next: implement, on_fail: escalate, loop: {max: {implement: 1, review: 1}, on_exceed: escalate}}
      escalate: {type: approval, options: [redesign, drop]}
      done: {type: terminal}
""")
PY
export TMUX_TMPDIR="$TDIR" TMUX_WEB_CONFIG="$W/cfg" TMUX_WEB_AUTH="$W/cfg/auth.json" TMUX_WEB_DATA="$W/data" PORT
export TMUX_WEB_CLAUDE_CMD="python3 $ROOT/tests/manual/fake_claude.py"
unset TMUX TMUX_PANE
cd "$ROOT"
setsid .venv/bin/python server.py > "$W/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; [ -S "$SOCK" ] && tmux -S "$SOCK" kill-server 2>/dev/null; rm -rf "$TDIR"' EXIT
for _ in $(seq 50); do curl -s -o /dev/null "localhost:$PORT/dev/login" && break; sleep 0.2; done
.venv/bin/python orchestrator.py start mw svc_a --brief "svc-a 기능 구현"
for i in $(seq 60); do
  .venv/bin/python orchestrator.py run --once 2>>"$W/orch.log"
  status=$(.venv/bin/python orchestrator.py list)
  echo "[$i] $status"
  case "$status" in *" done "*|*escalated*) break ;; esac
  sleep 1
done
echo "--- tmux sessions"; tmux -S "$SOCK" ls -F '#S'
echo "--- orchestrator log"; tail -5 "$W/orch.log"
echo "--- branches"; git -C "$W/repo" branch --list 'feat/*' -v
echo "--- history types"; cat "$W"/data/history/*/*/*.jsonl | python3 -c "import sys,json,collections; print(dict(collections.Counter(json.loads(l)['type'] for l in sys.stdin)))"

#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
W=${1:?작업 폴더}
PORT=${PORT:-8799}
TDIR=$(mktemp -d /tmp/claude-1000/twXXXX 2>/dev/null || mktemp -d /tmp/twXXXX)
rm -rf "$W" && mkdir -p "$W/cfg/company" "$W/data" "$W/repo"
SOCK="$TDIR/tmux-$(id -u)/default"
git -C "$W/repo" init -q -b main && git -C "$W/repo" commit -q --allow-empty -m init
if [ -n "${E2E_FULL:-}" ]; then
  git clone -q --bare "$W/repo" "$W/origin.git"
fi
python3 - "$ROOT" "$W" <<'PY'
import os, sys, yaml
from pathlib import Path
root, w = Path(sys.argv[1]), Path(sys.argv[2])
sample = root / "company/examples/mw-minimal"
org = yaml.safe_load((sample / "org.yaml").read_text())
full = bool(os.environ.get("E2E_FULL"))
org["divisions"]["mw"].update(template="feature_dev" if full else "mini", repo=str(w / ("origin.git" if full else "repo")))
import os
if os.environ.get("E2E_REAL"):
    for m in list(org["shared"].values()) + [m for d in org["divisions"]["mw"]["depts"].values() for m in (d.get("lead"), d.get("members")) if m]:
        m["model"] = "haiku"
(w / "cfg/company/org.yaml").write_text(yaml.safe_dump(org, allow_unicode=True))
(w / "cfg/company/documents.yaml").write_text((sample / "documents.yaml").read_text())
(w / "cfg/company/process.yaml").write_text((sample / "process.yaml").read_text() if full else ("""version: 1
templates:
  mini:
    start: implement
    nodes:
      implement: {role: impl, parallel: true, retry: 1, gate: gates/common/has_new_commit.sh, next: review, on_fail: analyze}
      review: {role: reviewer, gate: gates/common/review_approved.sh, next: done, on_fail: analyze, requires_approval: REVIEW_APPROVAL}
      analyze: {role: analysis, next: implement, on_fail: escalate, loop: {max: {implement: 1, review: 1}, on_exceed: escalate}}
      escalate: {type: approval, options: [redesign, drop]}
      done: {type: terminal}
""").replace("REVIEW_APPROVAL", "true" if os.environ.get("E2E_APPROVAL") else "false"))
PY
export TMUX_TMPDIR="$TDIR" TMUX_WEB_CONFIG="$W/cfg" TMUX_WEB_AUTH="$W/cfg/auth.json" TMUX_WEB_DATA="$W/data" PORT
if [ -z "${E2E_REAL:-}" ]; then
  export TMUX_WEB_CLAUDE_CMD="python3 $ROOT/tests/manual/fake_claude.py"
fi
unset TMUX TMUX_PANE
cd "$ROOT"
setsid .venv/bin/python server.py > "$W/server.log" 2>&1 &
SERVER=$!
if [ -z "${E2E_KEEP:-}" ]; then
  trap 'kill $SERVER 2>/dev/null; [ -S "$SOCK" ] && tmux -S "$SOCK" kill-server 2>/dev/null; rm -rf "$TDIR"' EXIT
else
  echo "KEEP server=$SERVER sock=$SOCK tdir=$TDIR"
  printf 'testpass123\n' | TMUX_WEB_AUTH="$W/cfg/auth.json" .venv/bin/python auth.py tester >/dev/null 2>&1 || true
fi
for _ in $(seq 50); do curl -s -o /dev/null "localhost:$PORT/dev/login" && break; sleep 0.2; done
.venv/bin/python orchestrator.py start mw svc_a --brief "${E2E_BRIEF:-svc-a 기능 구현}"
for i in $(seq "${E2E_TICKS:-60}"); do
  .venv/bin/python orchestrator.py run --once 2>>"$W/orch.log"
  if [ -n "${E2E_AUTO_APPROVE:-}" ]; then
    .venv/bin/python -c 'import approvals
for a in approvals.query("pending"):
    if a["kind"] == "gate":
        approvals.decide(a["id"], "approve", None, "e2e")
        print("auto-approved", a["id"], a["node"])'
  fi
  status=$(.venv/bin/python orchestrator.py list)
  echo "[$i] $status"
  case "$status" in *" done "*|*escalated*) break ;; esac
  sleep "${E2E_SLEEP:-1}"
done
echo "--- tmux sessions"; tmux -S "$SOCK" ls -F '#S'
echo "--- orchestrator log"; tail -5 "$W/orch.log"
echo "--- branches"; git -C "$W/repo" branch --list 'feat/*' -v
[ -d "$W/origin.git" ] && { echo "--- origin main"; git --git-dir "$W/origin.git" log --oneline main | head -12; }
echo "--- history types"; cat "$W"/data/history/*/*/*.jsonl | python3 -c "import sys,json,collections; print(dict(collections.Counter(json.loads(l)['type'] for l in sys.stdin)))"

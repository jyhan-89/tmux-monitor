wt="$1"; feature="$2"; out="${3:-$(mktemp -d)}"
here=$(cd "$(dirname "$0")" && pwd)
[ -f "$here/env.sh" ] && . "$here/env.sh"
[ -n "${GATE_ENV:-}" ] && [ -f "$GATE_ENV" ] && . "$GATE_ENV"
cd "$wt" || exit 1
warn() { echo "경고: $*"; }
first_line_is() { [ -f "$1" ] && [ "$(head -n 1 "$1" | tr -d '\r' | sed 's/[[:space:]]*$//')" = "$2" ]; }
run_cmd() { echo "\$ $1"; sh -c "$1" >"$out/$2.log" 2>&1; rc=$?; tail -n 15 "$out/$2.log"; return $rc; }

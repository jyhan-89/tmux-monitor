#!/bin/sh
wt="$1"
cd "$wt" || exit 1
set -f
base="${GATE_BASE:-}"
[ -n "$base" ] || { git rev-parse --verify -q origin/main >/dev/null && base=origin/main || base=main; }
git rev-parse --verify -q "$base" >/dev/null || { echo "기준 브랜치 $base를 찾을 수 없습니다"; exit 1; }
to_case() { printf '%s\n' "$1" | sed 's#\*\*/##g; s#\*\*#*#g; s#^/##'; }
matches() {
  file="$1"; list="$2"
  for g in $list; do
    pat=$(to_case "$g")
    case "$file" in $pat) return 0 ;; esac
  done
  return 1
}
bad=0
files=$(git log --first-parent --no-merges --format= --name-only "$base..HEAD" | sort -u)
for f in $files; do
  if [ -n "${GATE_DENY:-}" ] && matches "$f" "$GATE_DENY"; then
    echo "수정 금지 경로: $f"; bad=1
  elif ! matches "$f" "${GATE_CAN_EDIT:-}"; then
    echo "역할(${GATE_ROLE:-?}) 범위 밖: $f"; bad=1
  fi
done
[ $bad = 0 ] && echo "소유권 확인: $(printf '%s\n' "$files" | grep -c .)개 파일 모두 범위 안"
exit $bad

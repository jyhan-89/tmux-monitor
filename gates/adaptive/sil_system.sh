#!/bin/sh
. "$(dirname "$0")/_lib.sh"
if [ -n "${SIL_RUNNER:-}" ]; then
  run_cmd "$SIL_RUNNER system $feature" sil || { echo "SIL(system) 실패"; exit 1; }
  echo "SIL(system) 통과"
  exit 0
fi
warn "SIL_RUNNER 미설정, 리포트 파일만 확인"
report="reports/sil2/$feature.md"
[ -f "$report" ] || { echo "리포트가 없습니다: $report"; exit 1; }
grep -qi "^결과: *\(PASS\|통과\)" "$report" || { echo "리포트 결과가 통과가 아닙니다"; sed -n '1,10p' "$report"; exit 1; }
echo "리포트 통과: $report"

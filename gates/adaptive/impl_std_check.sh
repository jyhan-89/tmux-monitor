#!/bin/sh
. "$(dirname "$0")/_lib.sh"
if [ -n "${STATIC_CMD:-}" ]; then run_cmd "$STATIC_CMD" static || { echo "정적 분석 위반"; exit 1; }; else warn "STATIC_CMD 미설정, 정적 분석 생략"; fi
check="coord/standards-check/impl-$feature.md"
first_line_is "$check" PASS || { echo "구현 표준 검사 결과가 PASS가 아닙니다: $check"; [ -f "$check" ] && sed -n '1,10p' "$check"; exit 1; }
echo "구현 표준 검사 PASS"

#!/bin/sh
. "$(dirname "$0")/_lib.sh"
[ -f "coord/design/$feature.md" ] || { echo "설계서가 없습니다: coord/design/$feature.md"; exit 1; }
if [ -n "${ARXML_VALIDATE:-}" ]; then
  files=$(git ls-files '*.arxml')
  [ -z "$files" ] || run_cmd "$ARXML_VALIDATE $files" arxml || { echo "ARXML 검증 실패"; exit 1; }
else
  warn "ARXML_VALIDATE 미설정, 스키마 검증 생략"
fi
check="coord/standards-check/design-$feature.md"
if [ -f "$check" ]; then
  first_line_is "$check" PASS || { echo "설계 표준 검사 결과가 PASS가 아닙니다"; sed -n '1,10p' "$check"; exit 1; }
fi
echo "설계서 확인: coord/design/$feature.md"

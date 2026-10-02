#!/bin/sh
wt="$1"; feature="$2"
f="$wt/coord/review/$feature.md"
[ -f "$f" ] || { echo "리뷰 파일이 없습니다: coord/review/$feature.md"; exit 1; }
first=$(head -n 1 "$f" | tr -d '\r' | sed 's/[[:space:]]*$//')
[ "$first" = "APPROVED" ] && { echo "APPROVED"; exit 0; }
echo "리뷰 결과: $first"
sed -n '2,20p' "$f"
exit 1

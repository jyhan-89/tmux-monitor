#!/bin/sh
wt="$1"
base="${GATE_BASE:-main}"
n=$(git -C "$wt" rev-list --count "$base..HEAD" 2>/dev/null) || { echo "기준 브랜치 $base를 찾을 수 없습니다"; exit 1; }
[ "$n" -gt 0 ] && { echo "새 커밋 $n개"; exit 0; }
echo "$base 이후 새 커밋이 없습니다"
exit 1

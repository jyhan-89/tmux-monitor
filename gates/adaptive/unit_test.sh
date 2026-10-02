#!/bin/sh
. "$(dirname "$0")/_lib.sh"
n=$(git rev-list --count "${GATE_BASE:-main}..HEAD" 2>/dev/null || echo 0)
[ "$n" -gt 0 ] || { echo "${GATE_BASE:-main} 이후 커밋이 없습니다"; exit 1; }
if [ -n "${BUILD_CMD:-}" ]; then run_cmd "$BUILD_CMD" build || { echo "빌드 실패"; exit 1; }; else warn "BUILD_CMD 미설정, 빌드 생략"; fi
if [ -n "${TEST_CMD:-}" ]; then run_cmd "$TEST_CMD" test || { echo "단위 테스트 실패"; exit 1; }; else warn "TEST_CMD 미설정, 단위 테스트 생략"; fi
echo "새 커밋 $n개"

#!/bin/sh
wt="$1"; feature="$2"; out="${3:-$(mktemp -d)}"
here=$(cd "$(dirname "$0")" && pwd)
[ -n "${GATE_ENV:-}" ] && [ -f "$GATE_ENV" ] && . "$GATE_ENV"
cd "$wt" || exit 1
git fetch -q origin 2>/dev/null || true
ref=$(git rev-parse --verify -q origin/main || git rev-parse --verify -q main) || { echo "main을 찾을 수 없습니다"; exit 1; }
for b in $(git for-each-ref --format='%(refname:short)' "refs/heads/feat/$feature/" | grep -v '/integrator$'); do
  git merge-base --is-ancestor "$b" "$ref" || { echo "main에 머지되지 않은 브랜치: $b"; exit 1; }
done
if [ -n "${BUILD_CMD:-}${TEST_CMD:-}" ]; then
  tmp="$out/main"
  rm -rf "$tmp"
  git worktree add -q --detach "$tmp" "$ref" || exit 1
  rc=0
  ( cd "$tmp" && { [ -z "${BUILD_CMD:-}" ] || sh -c "$BUILD_CMD"; } && { [ -z "${TEST_CMD:-}" ] || sh -c "$TEST_CMD"; } ) >"$out/main.log" 2>&1 || rc=1
  tail -n 15 "$out/main.log"
  git worktree remove --force "$tmp"
  [ $rc = 0 ] || { echo "main 빌드·테스트 실패"; exit 1; }
else
  echo "경고: BUILD_CMD/TEST_CMD 미설정, main 빌드 생략"
fi
echo "main($ref)에 기능 브랜치가 모두 들어 있습니다"

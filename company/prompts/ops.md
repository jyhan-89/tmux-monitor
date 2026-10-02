# 역할: ops (운영부)

## 책임
- worktree·브랜치·태그 정리, 이력·정의·git 미러의 NAS 동기화
- `status` 지시서를 모아 상태를 집계한다

## 수정 가능
없음 (git worktree·branch·tag, rsync만)

## 산출물
- 동기화 결과, 정리한 worktree·브랜치 목록

## 금지
- `src/**` 수정, 머지, 브랜치 강제 삭제
- 진행 중인 지시서가 있는 세션의 worktree 제거

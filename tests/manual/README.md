# 수동 테스트

tmux와 Claude Code가 필요한 테스트는 자동 테스트(`pytest tests/`)에서 빼고 여기에 둔다.
모든 스크립트는 격리된 tmux 소켓·설정·데이터 폴더를 쓰고 끝나면 정리한다. 실제 tmux 서버는 건드리지 않는다.

## e2e_mini.sh

테스트 서버(포트 8799), 테스트 tmux, 임시 git 저장소를 만들고 오케스트레이터를 한 주기씩 돌린다.

```bash
PATH=$PWD/.venv/bin:$PATH tests/manual/e2e_mini.sh /tmp/e2e
```

| 환경변수 | 효과 |
|---|---|
| (없음) | 가짜 에이전트(`fake_claude.py`)로 `implement → review → done` |
| `FAKE_REJECT_FIRST=1` | 첫 리뷰를 반려해 `analyze` 루프와 카운터 확인 |
| `E2E_FULL=1` | 예시 정의 `mw-minimal`의 전체 프로세스, bare 저장소를 원격으로 사용 |
| `E2E_AUTO_APPROVE=1` | 통합 결재를 자동 승인 |
| `E2E_APPROVAL=1` | 리뷰 전에 결재를 받도록 설정 (결재함 화면 확인용) |
| `E2E_REAL=1` | 가짜 에이전트 대신 실제 Claude Code(haiku). 사용량이 든다 |
| `E2E_KEEP=1` | 끝나도 서버·tmux를 남기고 계정 `tester` / `testpass123`을 만든다. 정리는 출력된 pid와 소켓으로 |
| `E2E_TICKS`, `E2E_SLEEP` | 주기 횟수와 간격 (기본 60회, 1초) |
| `E2E_BRIEF` | 기능 요청 문구 |

통과 기준: 마지막 줄이 `done`, 기능 브랜치와 이력 종류가 출력된다.

## 비상 정지

1. Claude 세션 3개를 띄운다.
2. 세션 목록 위 `⏹ 비상 정지` → 확인.
3. 모든 Claude 세션이 입력 대기, `~/.config/tmux-web/company/STOPPED` 존재, 이력에 `emergency_stop` 1줄.
4. 배너의 `해제` → 플래그 삭제, 이력 `emergency_resume`.

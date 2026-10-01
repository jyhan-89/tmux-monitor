# tmux-persist

리붓해도 tmux 세션을 그대로 다시 열어 주는 도구입니다.

## 복원되는 것
- 세션, 윈도우(인덱스·이름·자동 이름 여부), 패인 분할 레이아웃, 줌 상태, 활성 윈도우/패인
- 각 패인의 작업 디렉터리
- 패인 화면 내용 (기본 1000줄)
- 허용 목록에 있는 프로그램 (`vim`, `less`, `htop`, `ssh` 등)은 같은 명령줄로 재실행
- **Claude Code**: 패인마다 실행 중이던 대화 ID를 저장해 두었다가 `claude --resume <ID>`로 같은 대화를 다시 엽니다 (원래 옵션 유지, 같은 디렉터리에 여러 개 있어도 각각 구분)

## 설치
```sh
./install.sh
```
- `~/.local/bin/tmux-persist` 설치
- `~/.tmux.conf`에 설정 파일 `source-file` 한 줄 추가
- systemd user 유닛:
  - `tmux-persist-save.timer` — 5분마다 자동 저장
  - `tmux-persist-restore.service` — 로그인(부팅) 시 자동 복원, 로그아웃/종료 직전 한 번 더 저장

리붓 후에는 `tmux attach`(또는 `tmux ls`)만 하면 됩니다.

## 사용법
```sh
tmux-persist save                 # 지금 저장
tmux-persist restore [스냅샷]      # 최근(또는 지정한) 스냅샷에서 복원 — 이미 있는 세션은 건너뜀
tmux-persist list                 # 스냅샷 목록 (* = 최신)
```
tmux 안에서는 `prefix + C-s` 로 저장, `prefix + C-r` 로 복원합니다.

## 설정 (`~/.config/tmux-persist/tmux-persist.conf`)
| 옵션 | 기본값 | 의미 |
|---|---|---|
| `@persist-processes` | `vi vim nvim nano emacs man less more tail top htop btop watch ssh claude` | 복원 시 재실행할 프로그램 이름, `:all:`이면 전부 |
| `@persist-capture-lines` | `1000` | 저장할 화면 줄 수, `0`이면 내용 저장 안 함 |
| `@persist-keep` | `20` | 보관할 스냅샷 개수 |

스냅샷은 `~/.local/share/tmux-persist/snapshots/`에 저장됩니다(권한 700). 패인 화면 내용이 평문으로 남으므로 민감한 출력이 걱정되면 `@persist-capture-lines 0`으로 끄세요.

## 제거
```sh
./uninstall.sh   # 스냅샷은 남겨 둠
```

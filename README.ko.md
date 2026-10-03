# tmux-web-monitor

[English](README.md) | **한국어**

PC에서 실행 중인 tmux 세션을 브라우저에서 보고 접속하는 웹 서비스입니다.
여러 개의 Claude Code 세션을 tmux로 띄워 두고 PC나 폰에서 확인·작업하는 용도로 만들었습니다.

![PC 화면](docs/screenshots/desktop.png)

| 파일 보기 | 폰 화면 |
|---|---|
| ![파일 보기](docs/screenshots/files.png) | ![폰 화면](docs/screenshots/mobile.png) |

## 기능

- **세션 목록**: 세션별 마지막 출력 3줄과 상태(셸, 실행 중, Claude 작업 중·확인 필요·대기) 표시, 정렬, 그룹(그룹 안에 하위 그룹 가능)
- **터미널**: xterm.js로 tmux 세션에 접속. 연결이 끊기면 자동 재연결
- **분할 화면**: 탭을 끌어 상하좌우로 분할, 영역마다 탭 줄, 경계선으로 크기 조절
- **가상 데스크탑**: 데스크탑마다 분할 배치와 탭을 따로 저장하고 전환(Alt+1~9). 같은 세션을 여러 데스크탑에 둘 수 있고, 구성을 서버에 저장해 다른 기기에서 불러올 수 있음
- **세션 관리**: 만들기(작업 폴더·시작 명령), 이름 변경, 종료, tmux 창/패널 전환·닫기
- **입력**: 한글 입력창, 자주 쓰는 명령 버튼, 모바일 특수키(Esc, Ctrl, 방향키 등)
- **파일**: 홈 폴더 아래 탐색, Markdown·코드 보기, 파일 올리기. 수정·복사·이동·삭제는 옵션(기본 꺼짐)
- **복사**: 터미널과 파일 보기에서 드래그로 선택하면 접속한 기기의 클립보드로 복사
- **알림**: Claude 작업이 끝나거나 확인이 필요할 때 웹 푸시 알림 (HTTPS 필요)
- **세션 저장/복원**: tmux-persist 애드온으로 주기적으로 저장하고 재부팅 후 복원
- **오케스트레이터 (선택)**: 조직·프로세스 정의에 따라 여러 Claude 세션을 자동 운영, 결재함·조직도·비상 정지

Claude 상태는 화면에 보이는 문구(`esc to interrupt`, `Do you want to…` 등)로 판단합니다.
Claude Code의 화면 구성이 바뀌면 상태 표시가 맞지 않을 수 있습니다.

## 요구 사항

- Linux(Ubuntu/Debian에서 사용 중) 또는 macOS
- tmux 3.x, Python 3.10 이상
- HTTPS 설치 방식을 쓸 경우 nginx

macOS용 설치 스크립트는 작성했지만 실제 Mac에서 검증하지 않았습니다.

## 설치

```bash
git clone https://github.com/jyhan-89/tmux-web-monitor.git
cd tmux-web-monitor
install/ubuntu.sh          # macOS: install/macos.sh
```

설치 스크립트는 패키지, Python 가상환경, 로그인 계정, 자동 시작(systemd 사용자 서비스 / launchd)을 설정합니다.
다시 실행해도 됩니다.

| 설치 방식 | 옵션 | 접속 주소 |
|---|---|---|
| 같은 네트워크에서 접속 (기본) | 없음 | `http://<IP>:8765/dev` |
| HTTPS (nginx + 자체 인증서) | `--https` | `https://<IP>/dev` |
| 이 PC에서만 | `--local` | `http://localhost:8765/dev` |

기타 옵션

- `--with-persist`: tmux-persist 애드온 함께 설치 (아래 참고)
- `--with-orchestrator`: 오케스트레이터 함께 설치 (아래 참고)
- `--no-service`: 자동 시작 등록 안 함 (`./run.sh`로 직접 실행)
- `-y`: 질문에 모두 예 (계정 만들기 제외)
- 포트 변경: `PORT=9000 install/ubuntu.sh`

기본 방식은 HTTP라서 브라우저에 '안전하지 않음'이 표시되고, 푸시 알림·붙여넣기 버튼·홈 화면 앱 설치를 쓸 수 없습니다.
이 기능이 필요하면 `--https`로 설치하거나 아래의 Tailscale Serve를 사용합니다.

### HTTPS 방식의 인증서

`--https`는 이 PC 전용 CA를 만들고 그 CA로 IP 주소용 인증서를 발급합니다.
접속하는 기기마다 `http://<IP>/dev/ca.crt`를 받아 신뢰할 수 있는 루트 인증서로 한 번 설치해야 경고가 사라집니다.
IP가 바뀌면 설치 스크립트를 다시 실행하면 인증서만 다시 발급됩니다(CA는 그대로).

## 계정

처음 설치하면 계정을 만들라고 묻습니다. 나중에 만들거나 비밀번호를 잊었을 때는
**서버 PC의 브라우저**에서 `http://localhost:8765/dev/setup`을 엽니다.

- 계정 설정과 서버 설정(파일 수정 허용 등)은 서버 PC에서 localhost로 접속했을 때만 바꿀 수 있습니다
- 비밀번호를 바꾸면 모든 기기에서 로그아웃됩니다
- 명령줄에서는 `.venv/bin/python auth.py [아이디]`

## 사용법

| 하고 싶은 것 | 방법 |
|---|---|
| 세션 열기 | 목록에서 클릭. 선택된 영역에 탭으로 열림 |
| 화면 분할 | 탭이나 목록의 세션을 터미널 영역 가장자리로 끌어다 놓기 |
| 데스크탑 | 상단 숫자 버튼으로 전환, ＋로 추가, 우클릭으로 이름 변경·삭제, 탭을 숫자 버튼에 끌어 놓으면 이동 |
| 데스크탑 구성 저장/불러오기 | 데스크탑 버튼 옆 ⋯. 서버에 저장되므로 다른 기기·주소에서도 불러올 수 있음. 저장하거나 불러온 구성에 연결되어 이후 변경이 자동 저장됨(연결 끊기 가능) |
| 세션·그룹 메뉴 | 목록에서 우클릭 (폰: 📁 ✎ ✕ 버튼) |
| 하위 그룹 | 그룹 우클릭 → 하위 그룹 만들기 / 다른 그룹 안으로 옮기기, 또는 그룹 이름을 `상위/하위`로 입력 |
| 한글 입력 | 하단 입력창에 입력 후 Enter |
| 지난 출력 보기 | 마우스 휠 / 폰에서 위아래로 쓸기 |
| 복사 | 드래그로 선택 (Claude 화면 안에서는 Shift+드래그, 또는 아래 설정) |
| 파일 보기 | 상단 📂. 우클릭 메뉴로 복사·이동·삭제(수정 허용 시) |
| 저장/복원 | 목록 위 💾 |

### Claude Code 화면에서 복사

Claude Code처럼 마우스를 쓰는 앱에서는 드래그가 앱으로 전달됩니다.
앱이 복사한 내용을 기기 클립보드로 받으려면 tmux가 클립보드 시퀀스(OSC 52)를 통과시키도록 설정합니다.
tmux 기본값(`external`)은 이 시퀀스를 무시합니다.

```bash
tmux set -s set-clipboard on
echo 'set -s set-clipboard on' >> ~/.tmux.conf
```

### 세션 저장/복원 (tmux-persist)

`addons/tmux-persist/`는 tmux 세션을 저장했다가 다시 만드는 스크립트입니다.
창·패널 배치, 작업 폴더, 화면 내용을 저장하고, 실행 중이던 Claude Code는 `claude --resume <대화 ID>`로 다시 엽니다.

- `--with-persist`로 설치하면 5분마다 저장하고 로그인(부팅) 때 복원합니다
- 웹의 💾에서 지금 저장하거나 원하는 스냅샷으로 복원할 수 있습니다. 이미 있는 세션은 건너뜁니다
- 명령줄: `tmux-persist save | restore [스냅샷] | list`

### 오케스트레이터 (선택, 실험 단계)

여러 Claude Code 세션을 조직(본부·부서·역할)과 프로세스(단계·게이트·반려 루프) 정의에 따라 자동으로 운영합니다.
사람은 결재함에서 승인·반려만 하고, 나머지는 세션들이 지시서를 주고받으며 진행합니다.

```
결재함(📝) / 조직도(🏢) ── tmux-web 서버 ── 오케스트레이터(별도 서비스)
                              │                 │ 지시서 발송·깨우기·게이트 실행
                         이력(JSONL)      역할 세션 (worktree + CLAUDE.md + 권한)
```

설치: `install/ubuntu.sh --with-orchestrator`. `~/.config/tmux-web/company/`에 역할 프롬프트와 예시 정의가 복사되고
오케스트레이터 서비스(`tmux-web-orchestrator`)가 등록됩니다. 정의가 없으면 오케스트레이터는 대기만 합니다.

**정의 파일** (`~/.config/tmux-web/company/`, 저장할 때마다 이 폴더의 git에 기록)

| 파일 | 내용 |
|---|---|
| `org.yaml` | 본부·부서·역할, 역할별 모델·인원·권한(`allowed_tools`, `can_edit`), 본부의 git 저장소 |
| `process.yaml` | 노드(담당 역할, 게이트, 통과·실패 시 다음 노드, 재시도, 결재 필요), 반려 루프 상한 |
| `documents.yaml` | 문서 소유권, 지시서 종류별 보낼 수 있는 역할·받을 역할 |
| `prompts/` | `common.md`(지시서 처리 절차)와 역할별·노드별 프롬프트 |

예시: `company/examples/mw-minimal/`. 저장할 때 검증해서 규칙을 어기면 거부하고 규칙 이름과 위치를 알려 줍니다.

**동작**

- 역할 세션 이름은 `본부-부서-역할[-계층|번호]` (예: `mw-impl-impl-skeleton`). 세션 목록에서 `본부/부서` 하위 그룹으로 묶입니다
- 런처가 세션마다 git worktree와 브랜치 `feat/<기능>/<계층>`, `CLAUDE.md`, 권한(`.claude/settings.json`, 목록 밖 도구는 묻지 않고 거부), 훅을 만듭니다. 처음 여는 worktree의 Claude Code 폴더 신뢰 확인은 런처가 자동으로 수락합니다
- 세션 안의 판단과 절차는 `CLAUDE.md` 규칙이 맡고, 오케스트레이터는 지시서 배달·깨우기("inbox 확인")·게이트 실행·전이만 합니다
- 세션은 `directive` 명령(list, show, ack, start, done, block, reject, send)으로 지시서를 처리합니다. `done --ref <브랜치@커밋>`이 있어야 완료로 봅니다
- 게이트는 읽기 전용 스크립트입니다 (`gates/`). 벤더 빌드·테스트·SIL 연결은 `gates/adaptive/env.sh`의 `BUILD_CMD`, `TEST_CMD`, `STATIC_CMD`, `ARXML_VALIDATE`, `SIL_RUNNER`에 적습니다. 비워 두면 산출물 파일만 확인합니다
- 상태는 지시서 → Claude Code 훅(30초 안) → 화면 감지 순으로 판단합니다

**화면**

| 하고 싶은 것 | 방법 |
|---|---|
| 기능 시작 | 📝 결재함 → 새 기능 시작 (본부, 기능 이름, 요청) |
| 결재 | 📝 결재함에서 승인 / 반려 / 수정 요청 (반려·수정은 사유 필수). 결재가 생기면 푸시 알림 |
| 조직·프로세스 보기와 편집 | 🏢 조직도: 역할 노드 색이 세션 상태, 노드를 누르면 편집 패널. 본부를 더블클릭하면 프로세스 |
| 기존 세션 배정 | 🏢 조직도 아래 '조직 밖 세션'을 역할 노드로 끌어다 놓기 (폰: 세션을 누른 뒤 역할 노드). 배정된 자리는 새 세션을 만들지 않고 그 세션에 일을 맡기며, 자동 재시작하지 않습니다. Claude가 실행 중일 때만 깨웁니다 |
| 노드 강제 이동 | 📝 결재함 → 진행 중인 기능 → 노드 이동 |
| 모두 멈추기 | 세션 목록 위 ⏹ 비상 정지 (모든 Claude 세션에 Esc, 자동 진행 정지). 배너의 해제로 재개 |
| 세션 이력 | 세션 우클릭 → 최근 이력 |

**주의**

- 권한 설정은 실수 방지용입니다. Bash가 열린 역할은 우회할 수 있으므로 소유권은 게이트(`ownership_check.sh`)와 git 서버의 보호 브랜치로 지키세요
- 통합(머지) 노드는 원격 저장소에 `git push origin HEAD:main`을 하므로 본부의 `repo`는 bare 저장소나 git 서버 주소로 두세요
- NAS 백업: `TMUX_WEB_NAS_ROOT`를 정하고 설치하면 이력·정의·`coord/`와 git 미러를 매시간 동기화합니다
- 수동 테스트 절차는 `tests/manual/README.md`

## 외부에서 접속하기

이 서비스는 브라우저에서 셸을 쓰는 도구입니다. **공유기 포트포워딩 등으로 인터넷에 직접 열지 마세요.**
밖에서 쓸 때는 VPN을 거칩니다.

[Tailscale](https://tailscale.com)을 쓰는 경우:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4                       # 이 IP로 접속
```

Tailscale Serve를 쓰면 `*.ts.net` 주소에 정식 인증서가 붙어 기기마다 CA를 설치하지 않아도 됩니다.
(관리 콘솔에서 MagicDNS와 HTTPS Certificates를 먼저 켜야 하고, `--https` 방식과는 443 포트가 겹칩니다.)

```bash
sudo tailscale serve --bg http://127.0.0.1:8765     # https://<기기이름>.<tailnet>.ts.net/dev
```

## 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `HOST` | `127.0.0.1` | 받을 주소 (같은 네트워크 방식은 `0.0.0.0`) |
| `PORT` | `8765` | 포트 |
| `BASE_PATH` | `/dev` | URL 경로 |
| `TMUX_WEB_FILES_ROOT` | `~` | 파일 탐색 범위 |
| `TMUX_WEB_CONFIG` | `~/.config/tmux-web` | 설정·데이터 폴더 |
| `TMUX_WEB_AUTH` | `~/.config/tmux-web/auth.json` | 계정 파일 |
| `TMUX_WEB_TLS` | `~/.config/tmux-web/tls` | 자체 인증서 폴더 |
| `TMUX_PERSIST_DIR` | `~/.local/share/tmux-persist` | 스냅샷 폴더 |
| `TMUX_WEB_DATA` | `~/.local/share/tmux-web` | 이력·지시서·결재·오케스트레이터 상태·worktree |
| `TMUX_WEB_MAX_ACTIVE` | `4` | 동시에 작업할 수 있는 역할 세션 수 (오케스트레이터) |
| `TMUX_WEB_NAS_ROOT` | (없음) | NAS 백업 경로 |

`~/.config/tmux-web/`에는 계정, 로그인 세션, 명령 버튼·그룹 설정, 저장한 데스크탑 구성, 푸시 알림 키·구독, 인증서가 저장되며 저장소에는 포함되지 않습니다.
지금 열려 있는 데스크탑 배치는 브라우저(접속 주소별)에 저장됩니다.

## 관리

```bash
systemctl --user status tmux-web        # 상태 (macOS: launchctl list kr.tmuxweb.server)
systemctl --user restart tmux-web       # 재시작
journalctl --user -u tmux-web -n 50     # 로그 (macOS: ~/Library/Logs/tmux-web.log)
```

업데이트는 `git pull` 후 설치 스크립트를 같은 옵션으로 다시 실행합니다.
열려 있는 브라우저 화면에는 '새 버전이 있습니다' 안내가 표시됩니다.

제거 (Ubuntu)

```bash
systemctl --user disable --now tmux-web && rm ~/.config/systemd/user/tmux-web.service
sudo rm /etc/nginx/sites-enabled/tmux-web && sudo systemctl reload nginx   # --https로 설치한 경우
addons/tmux-persist/uninstall.sh                                            # --with-persist로 설치한 경우
rm -rf ~/.config/tmux-web                                                   # 계정·설정까지 지울 때
```

## 보안

- 로그인한 사람은 PC 사용자 권한으로 셸을 쓸 수 있습니다. 믿을 수 있는 네트워크에서만 사용하세요
- 비밀번호는 scrypt 해시로 저장하고, 5분 안에 5번 틀리면 해당 IP를 5분간 막습니다
- 파일 탐색은 `TMUX_WEB_FILES_ROOT` 밖(심볼릭 링크 포함)을 거부하고, 수정 기능은 기본으로 꺼져 있습니다
- 기본 설치 방식(HTTP)에서는 비밀번호와 터미널 내용이 암호화되지 않습니다

## 구조

```
server.py            FastAPI 서버 (API, WebSocket 터미널)
tmuxctl.py           tmux 조회와 상태 판별
auth.py, store.py    계정, 설정 저장
push.py              상태 감시, 웹 푸시
static/              웹 화면 (index.html, app.js, app.css, login/setup 화면)
install/             설치 스크립트 (Ubuntu, macOS)
deploy/              systemd 유닛, nginx 설정, 인증서 생성 스크립트
addons/tmux-persist/ 세션 저장/복원 애드온
orchestrator.py      오케스트레이터 (노드 전이, 게이트, 결재 대기, 시간 상한, 복구)
launcher.py          역할 세션 생성 (worktree, CLAUDE.md, 권한, 훅)
models.py            조직·프로세스·문서 정의 로더와 검증
directives.py        지시서 큐, bin/directive 세션용 명령
approvals.py         결재 항목
history.py           이력 (JSONL)
*_api.py             정의·제어·지시서·결재·이벤트·이력 API
company/             역할·노드 프롬프트, 예시 정의
gates/               게이트 스크립트
hooks/               Claude Code 훅 스크립트
ops/                 NAS 동기화
```

## 라이선스

[PolyForm Noncommercial 1.0.0](LICENSE)

- 개인, 교육기관, 공공 연구기관, 비영리 단체는 무료로 사용할 수 있습니다
- 회사·영리 목적의 사용(사내 사용 포함)은 별도의 상업 라이선스가 필요합니다: jyhan.dev@gmail.com

## 기여

외부 코드 기여(Pull Request)는 받지 않습니다. 버그와 제안은 Issues에 남겨 주세요.

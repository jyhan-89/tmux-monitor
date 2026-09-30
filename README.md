# tmux 웹 모니터

로컬 tmux 세션 목록을 웹에서 보고, 브라우저 터미널로 접속해 작업하는 서비스.

A self-hosted web UI to monitor and attach to local tmux sessions from any browser (desktop & mobile),
with Claude Code status detection and push notifications.
For remote access, use a VPN such as Tailscale — never expose it directly to the internet
(see [외부에서 접속하기](#외부에서-접속하기-tailscale-등)).
Free for personal, educational, research and other noncommercial use — see [License](#license).

- 세션 목록/미리보기, Claude Code 상태(작업 중·확인 필요·대기) 표시와 푸시 알림
- 탭·분할 화면, 자동 재연결, 한글 입력창, 모바일 특수키·제스처, 홈 화면 앱(PWA)
- 세션 생성(작업 폴더·시작 명령)·이름 변경·종료, tmux 창/패널 전환
- 정렬, 그룹(드래그로 이동), 파일 업로드, 화면 내용 복사
- 파일 탐색: 홈 폴더 아래 폴더 탐색, Markdown 문서·코드(문법 색상) 보기, 선택적으로 파일 수정

## 설치

설치 스크립트가 패키지, Python 환경, 계정, 자동 시작까지 한 번에 구성한다. 여러 번 실행해도 안전하다.

```bash
install/ubuntu.sh     # Ubuntu/Debian: apt, systemd 사용자 서비스
install/macos.sh      # macOS: Homebrew, launchd 에이전트
```

| 설치 방식 | 옵션 | 접속 주소 |
|---|---|---|
| 로컬 네트워크 서버 (기본) | 없음 | `http://<IP>:8765/dev` |
| HTTPS (nginx + 자체 인증서) | `--https` | `https://<IP>/dev` |
| 이 PC에서만 | `--local` | `http://localhost:8765/dev` |

기본 방식은 HTTP라서 브라우저 주소창에 '안전하지 않음'이 표시되고, 푸시 알림·붙여넣기 버튼·홈 화면 앱 설치는
HTTPS에서만 동작한다. 필요하면 `--https`로 다시 실행한다.

기타 옵션: `-y` 질문에 모두 예, `--no-service` 자동 시작 등록 생략. 포트 변경: `PORT=9000 install/ubuntu.sh`.

수동으로 실행만 하려면:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh                         # http://127.0.0.1:8765/dev/
```

## 계정 설정 / 초기화

처음 실행하면 계정이 없으므로 서버 PC의 브라우저에서 `http://localhost:8765/dev/setup` 을 열어 아이디/비밀번호를 만든다.
같은 주소에서 현재 비밀번호 없이 아이디/비밀번호를 초기화할 수 있다 (저장하면 모든 기기 로그아웃).

- 서버 PC에서 localhost 주소로 접속했을 때만 허용 (외부 IP, 프록시 헤더 위조, DNS 리바인딩 차단)
- 터미널에서는 `.venv/bin/python auth.py [아이디]` 로도 설정 가능

## 파일 탐색 / 수정

상단 📂 버튼으로 홈 폴더 아래 파일을 탐색한다. 기본은 **읽기 전용**이다.

- 파일 수정은 서버 PC의 `http://localhost:8765/dev/setup` → **서버 설정 → 파일 수정 허용**에서 켜고 끈다
  (계정 설정처럼 서버 PC에서 localhost로 접속했을 때만 변경 가능)
- 켜면 텍스트 파일 보기 화면에 **수정** 버튼이 생긴다. `Ctrl+S` 저장, 원래 인코딩(UTF-8/EUC-KR)과 줄바꿈(LF/CRLF) 유지,
  다른 곳에서 먼저 바뀐 파일은 덮어쓰기 전에 확인
- 볼 수 있는 범위는 `TMUX_WEB_FILES_ROOT` 환경변수로 바꿀 수 있다 (기본: 홈 폴더)

## 외부에서 접속하기 (Tailscale 등)

기본 설치는 같은 네트워크(사내망, 집 와이파이)에서만 접속된다. 밖에서 쓰려면 **VPN을 거쳐 접속**한다.

> ⚠️ 공유기 포트포워딩 등으로 이 서비스를 **인터넷에 직접 열지 말 것.** 로그인이 있지만 브라우저에서 셸을 여는 도구이므로,
> 노출되면 비밀번호 대입 공격 등의 표적이 된다.

### Tailscale (추천)

[Tailscale](https://tailscale.com)은 내 기기끼리 암호화된 사설 네트워크를 만들어 주는 무료 VPN이다(개인 사용 무료).
서버 PC와 폰/노트북에 설치하고 같은 계정으로 로그인하면, 어디서든 서버의 Tailscale IP(`100.x.y.z`)로 접속된다.

```bash
# 서버 PC (Linux)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4          # 100.x.y.z
```

- 기본 설치(로컬 네트워크 서버): `http://100.x.y.z:8765/dev`
- `--https` 설치: `https://100.x.y.z/dev` (자체 인증서의 CA를 기기에 설치. 설치 스크립트가 Tailscale IP도 인증서에 넣는다)

**Tailscale Serve로 HTTPS 쓰기 (인증서 설치 불필요)**

Tailscale이 `https://<기기이름>.<tailnet>.ts.net` 주소로 정식 인증서(Let's Encrypt)를 붙여 준다.
기기마다 CA를 설치하지 않아도 푸시 알림, 붙여넣기 버튼, 홈 화면 앱을 쓸 수 있다.

```bash
# 관리 콘솔에서 MagicDNS와 HTTPS Certificates를 켠 뒤 (처음 실행 시 안내 링크가 나옴)
sudo tailscale serve --bg http://127.0.0.1:8765
# 접속: https://<기기이름>.<tailnet>.ts.net/dev   (끄기: sudo tailscale serve reset)
```

- tailnet(내 Tailscale 기기)에서만 열리고 인터넷에는 공개되지 않는다.
- `--https` 설치(nginx가 443 사용)와 함께 쓰면 Tailscale IP의 443 포트가 겹친다. 둘 중 하나만 쓴다.
- 발급된 인증서의 기기 이름(`*.ts.net`)은 인증서 투명성(CT) 공개 기록에 남는다.

### 그 밖의 방법

- **회사/학교 VPN**: VPN으로 내부망에 들어온 뒤 내부 IP로 접속
- **WireGuard** 등 직접 구성한 VPN
- **SSH 터널** (임시로 쓸 때): `ssh -L 8765:127.0.0.1:8765 user@서버` 후 내 PC에서 `http://localhost:8765/dev`

## 배포 (deploy/)

- `tmux-web.service`: systemd 사용자 서비스 (`~/.config/systemd/user/`에 복사 후 `systemctl --user enable --now tmux-web`)
- `nginx-tmux-web.conf`: HTTPS 리버스 프록시 (`/dev` → 127.0.0.1:8765), `--https` 설치 시 사용
- `make-cert.sh`: IP 주소용 자체 CA/인증서 생성. 기기에는 `/dev/ca.crt`를 설치.
  IP가 바뀌면 설치 스크립트를 다시 실행하면 인증서가 새로 발급된다 (CA는 유지되므로 기기 재설치 불필요)

## 설정 파일 (`~/.config/tmux-web/`)

계정(`auth.json`), 로그인 세션, 명령 버튼·그룹(`config.json`), 푸시 키/구독, TLS 인증서.
저장소에는 포함하지 않는다.

## License

[PolyForm Noncommercial 1.0.0](LICENSE)

- **무료**: 개인, 학생, 교육기관(대학 등), 공공 연구기관, 정부기관, 비영리 단체의 사용
- **상업 라이선스 필요**: 회사·영리 목적의 사용 (사내 사용 포함)
- 상업 라이선스 문의: jyhan.dev@gmail.com

Free for noncommercial use. Commercial use (including internal use at a company) requires a commercial license —
contact jyhan.dev@gmail.com.

## 기여

현재 외부 코드 기여(Pull Request)는 받지 않습니다. 버그 제보와 기능 제안은 Issues에 남겨 주세요.

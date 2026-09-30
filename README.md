# tmux 웹 모니터

로컬 tmux 세션 목록을 웹에서 보고, 브라우저 터미널로 접속해 작업하는 서비스.

- 세션 목록/미리보기, Claude Code 상태(작업 중·확인 필요·대기) 표시와 푸시 알림
- 탭·분할 화면, 자동 재연결, 한글 입력창, 모바일 특수키·제스처, 홈 화면 앱(PWA)
- 세션 생성(작업 폴더·시작 명령)·이름 변경·종료, tmux 창/패널 전환
- 정렬, 그룹(드래그로 이동), 파일 업로드, 화면 내용 복사

## 설치

```bash
python3 -m venv .venv            # pip가 없으면 get-pip.py로 설치
.venv/bin/pip install -r requirements.txt
.venv/bin/python auth.py         # 로그인 계정 설정
./run.sh                         # http://127.0.0.1:8765/dev/
```

## 배포 (deploy/)

- `tmux-web.service`: systemd 사용자 서비스 (`~/.config/systemd/user/`에 복사 후 `systemctl --user enable --now tmux-web`)
- `nginx-tmux-web.conf`: HTTPS 리버스 프록시 (`/dev` → 127.0.0.1:8765)
- `make-cert.sh`: IP 주소용 자체 CA/인증서 생성. 기기에는 `/dev/ca.crt`를 설치

## 설정 파일 (`~/.config/tmux-web/`)

계정(`auth.json`), 로그인 세션, 명령 버튼·그룹(`config.json`), 푸시 키/구독, TLS 인증서.
저장소에는 포함하지 않는다.

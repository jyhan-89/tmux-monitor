#!/usr/bin/env bash
# tmux 웹 모니터 설치 (macOS, Homebrew 필요)
#
#  1. 패키지: tmux, python, openssl@3, (nginx)  — Homebrew
#  2. Python 가상환경 + 의존성
#  3. 로그인 계정
#  4. launchd 사용자 에이전트 (로그인 시 자동 시작, 죽으면 재시작)
#  5. 자체 CA 인증서 + nginx HTTPS (/dev → 127.0.0.1:8765)
#
# 여러 번 실행해도 안전 (이미 된 단계는 갱신만 함).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
parse_args "$@"

[[ "$(uname -s)" == Darwin ]] || die "macOS에서 실행하세요 (Ubuntu는 install/ubuntu.sh)"
[[ $EUID -ne 0 ]] || die "sudo 없이 일반 사용자로 실행하세요"

# ---------- 1. 패키지 ----------
step "패키지 설치 (Homebrew)"
if ! command -v brew >/dev/null; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [[ -x $b ]] && eval "$("$b" shellenv)" && break
  done
fi
command -v brew >/dev/null || die "Homebrew가 없습니다. https://brew.sh 의 설치 명령을 먼저 실행하세요"
BREW="$(brew --prefix)"
pkgs=(tmux python openssl@3)
[[ $WITH_NGINX == 1 ]] && pkgs+=(nginx)
missing=()
for p in "${pkgs[@]}"; do
  brew list --formula "$p" >/dev/null 2>&1 || missing+=("$p")
done
if ((${#missing[@]})); then
  info "설치: ${missing[*]}"
  brew install -q "${missing[@]}"
fi
PY="$BREW/bin/python3"
export OPENSSL="$(brew --prefix openssl@3)/bin/openssl"  # 기본 LibreSSL은 인증서 옵션 일부 미지원
ok "tmux $("$BREW/bin/tmux" -V | cut -d' ' -f2), $("$PY" --version)"

# ---------- 2~3. Python / 계정 ----------
setup_venv "$PY"
setup_account

# ---------- 4. launchd 에이전트 ----------
LABEL="kr.tmuxweb.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/tmux-web.log"
if [[ $WITH_SERVICE == 1 ]]; then
  step "상시 실행 (launchd: $LABEL)"
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
  # launchd는 PATH가 최소라서 brew의 tmux를 찾도록 지정. 한글 처리를 위해 UTF-8 로케일
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/.venv/bin/python</string>
    <string>server.py</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$BREW/bin:$BREW/sbin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>${LANG:-ko_KR.UTF-8}</string>
    <key>PORT</key><string>$PORT</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  wait_healthy && ok "실행 중: http://127.0.0.1:$PORT/dev  (로그: $LOG)" \
    || die "서비스가 응답하지 않습니다: tail -50 $LOG"
else
  warn "상시 실행 생략: 필요할 때 $APP_DIR/run.sh 로 실행"
fi

# ---------- 5. nginx + HTTPS ----------
if [[ $WITH_NGINX == 1 ]]; then
  make_cert
  step "nginx 설정 (80 → 443 HTTPS, /dev 프록시)"
  # brew nginx.conf 는 servers/* 를 include. 사용자 권한으로 실행되므로 인증서는 제자리에서 읽음
  conf_dir="$BREW/etc/nginx/servers"
  mkdir -p "$conf_dir"
  render_nginx_conf "$TLS_DIR/server.crt" "$TLS_DIR/server.key" > "$conf_dir/tmux-web.conf"
  "$BREW/bin/nginx" -t -q 2>/dev/null || { "$BREW/bin/nginx" -t; die "nginx 설정 오류"; }
  brew services restart nginx >/dev/null
  sleep 1
  curl -fsk -o /dev/null https://127.0.0.1/dev/login && ok "nginx 적용 완료" \
    || warn "https://127.0.0.1/dev 응답 없음. 방화벽 허용 여부와 'brew services list' 를 확인하세요"

  step "이 Mac이 CA를 신뢰하도록 등록 (선택)"
  if ask "로그인 키체인에 CA를 '항상 신뢰'로 추가할까요? (Safari/Chrome 경고 제거, 암호 입력 창이 뜸)"; then
    security add-trusted-cert -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" "$TLS_DIR/ca.crt" \
      && ok "키체인에 추가"
  fi
fi

ips="$(ifconfig | awk '/inet /{print $2}' | grep -vE '^(127\.|172\.17\.|192\.168\.122\.)' | xargs)"
summary "$ips"

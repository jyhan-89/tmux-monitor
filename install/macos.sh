#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
parse_args "$@"

[[ "$(uname -s)" == Darwin ]] || die "macOS에서 실행하세요 (Ubuntu는 install/ubuntu.sh)"
[[ $EUID -ne 0 ]] || die "sudo 없이 일반 사용자로 실행하세요"

step "패키지 설치 (Homebrew)"
if ! command -v brew >/dev/null; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [[ -x $b ]] && eval "$("$b" shellenv)" && break
  done
fi
command -v brew >/dev/null || die "Homebrew가 없습니다. https://brew.sh 의 설치 명령을 먼저 실행하세요"
BREW="$(brew --prefix)"
pkgs=(tmux python openssl@3)
[[ $MODE == https ]] && pkgs+=(nginx)
missing=()
for p in "${pkgs[@]}"; do
  brew list --formula "$p" >/dev/null 2>&1 || missing+=("$p")
done
if ((${#missing[@]})); then
  info "설치: ${missing[*]}"
  brew install -q "${missing[@]}"
fi
PY="$BREW/bin/python3"
export OPENSSL="$(brew --prefix openssl@3)/bin/openssl"
ok "tmux $("$BREW/bin/tmux" -V | cut -d' ' -f2), $("$PY" --version)"

setup_venv "$PY"
setup_account

LABEL="kr.tmuxweb.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/tmux-web.log"
if [[ $WITH_SERVICE == 1 ]]; then
  step "상시 실행 (launchd: $LABEL)"
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
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
    <key>HOST</key><string>$(app_host)</string>
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

if [[ $MODE == lan ]]; then
  step "로컬 네트워크 서버 (0.0.0.0:$PORT)"
  info "macOS 방화벽이 켜져 있으면 'python이 들어오는 연결을 허용' 창이 뜰 수 있습니다 → 허용"
  [[ $WITH_SERVICE == 1 ]] || warn "직접 실행할 때: HOST=0.0.0.0 $APP_DIR/run.sh"
fi

if [[ $MODE == https ]]; then
  make_cert
  step "nginx 설정 (80 → 443 HTTPS, /dev 프록시)"
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

if [[ $WITH_ORCH == 1 ]]; then
  setup_company
  if [[ $WITH_SERVICE == 1 ]]; then
    OLABEL="kr.tmuxweb.orchestrator"
    OPLIST="$HOME/Library/LaunchAgents/$OLABEL.plist"
    cat > "$OPLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$OLABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/.venv/bin/python</string>
    <string>orchestrator.py</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$BREW/bin:$BREW/sbin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PORT</key><string>$PORT</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/tmux-web-orchestrator.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/tmux-web-orchestrator.log</string>
</dict>
</plist>
PLIST
    launchctl bootout "gui/$(id -u)/$OLABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$OPLIST"
    ok "오케스트레이터 실행 (로그: ~/Library/Logs/tmux-web-orchestrator.log)"
  fi
fi

if [[ $WITH_PERSIST == 1 ]]; then
  step "tmux-persist (세션 자동 저장, 로그인 후 복원)"
  PD="$APP_DIR/addons/tmux-persist"
  mkdir -p "$HOME/.local/bin" "$HOME/.config/tmux-persist" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  install -m 755 "$PD/tmux-persist" "$HOME/.local/bin/tmux-persist"
  install -m 644 "$PD/tmux-persist.conf" "$HOME/.config/tmux-persist/tmux-persist.conf"
  line="source-file -q ~/.config/tmux-persist/tmux-persist.conf"
  grep -qF "$line" "$HOME/.tmux.conf" 2>/dev/null || echo "$line" >> "$HOME/.tmux.conf"
  for job in save restore; do
    label="kr.tmuxweb.persist-$job"
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if [[ $job == save ]]; then
      when="<key>StartInterval</key><integer>300</integer>"
    else
      when="<key>RunAtLoad</key><true/>"
    fi
    cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HOME/.local/bin/tmux-persist</string>
    <string>$job</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$BREW/bin:$BREW/sbin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>${LANG:-ko_KR.UTF-8}</string>
  </dict>
  $when
  <key>StandardOutPath</key><string>$HOME/Library/Logs/tmux-persist.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/tmux-persist.log</string>
</dict>
</plist>
PLIST
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  done
  PATH="$BREW/bin:$PATH" "$PY" "$HOME/.local/bin/tmux-persist" save -q || true
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/kr.tmuxweb.persist-save.plist"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/kr.tmuxweb.persist-restore.plist" 2>/dev/null || true
  ok "5분마다 자동 저장, 로그인 시 자동 복원, 웹 화면 💾 에서 저장/복원 (로그: ~/Library/Logs/tmux-persist.log)"
fi

ips="$(ifconfig | awk '/inet /{print $2}' | grep -vE '^(127\.|172\.17\.|192\.168\.122\.)' | xargs)"
summary "$ips"

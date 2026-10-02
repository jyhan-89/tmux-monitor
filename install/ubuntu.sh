#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
parse_args "$@"

[[ $EUID -ne 0 ]] || die "root가 아닌 일반 사용자로 실행하세요 (필요한 곳에서만 sudo 사용)"
command -v apt-get >/dev/null || die "apt-get이 없습니다. Ubuntu/Debian 계열에서 실행하세요"

step "패키지 설치 (apt)"
pkgs=(tmux python3 python3-venv openssl curl ca-certificates)
[[ $MODE == https ]] && pkgs+=(nginx)
missing=()
for p in "${pkgs[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
if ((${#missing[@]})); then
  info "설치: ${missing[*]}"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
fi
ok "tmux $(tmux -V | cut -d' ' -f2), $(python3 --version)"

setup_venv python3
setup_account

if [[ $WITH_SERVICE == 1 ]]; then
  step "상시 실행 (systemd 사용자 서비스 tmux-web)"
  unit_dir="$HOME/.config/systemd/user"
  mkdir -p "$unit_dir"
  sed -e "s#%h/dev_monitor#$APP_DIR#g" "$APP_DIR/deploy/tmux-web.service" > "$unit_dir/tmux-web.service"
  sed -i "/^\[Service\]/a Environment=HOST=$(app_host)\nEnvironment=PORT=$PORT" "$unit_dir/tmux-web.service"
  systemctl --user daemon-reload
  systemctl --user enable tmux-web >/dev/null 2>&1
  systemctl --user restart tmux-web
  wait_healthy && ok "실행 중: http://127.0.0.1:$PORT/dev" \
    || die "서비스가 응답하지 않습니다: journalctl --user -u tmux-web -n 50"
  if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]]; then
    sudo loginctl enable-linger "$USER" && ok "부팅 시 자동 시작 (linger) 켬"
  else
    ok "부팅 시 자동 시작 (linger) 이미 켜짐"
  fi
else
  warn "상시 실행 생략: 필요할 때 $APP_DIR/run.sh 로 실행"
fi

if [[ $MODE == lan ]]; then
  step "로컬 네트워크 서버 (0.0.0.0:$PORT)"
  if command -v ufw >/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
    if ask "방화벽(ufw)에서 $PORT 포트를 열까요?"; then
      sudo ufw allow "$PORT/tcp" >/dev/null && ok "ufw: $PORT/tcp 허용"
    else
      warn "다른 기기에서 접속하려면: sudo ufw allow $PORT/tcp"
    fi
  fi
  [[ $WITH_SERVICE == 1 ]] || warn "직접 실행할 때: HOST=0.0.0.0 $APP_DIR/run.sh"
fi

if [[ $MODE == https ]]; then
  make_cert
  step "nginx 설정 (80 → 443 HTTPS, /dev 프록시)"
  sudo install -m 600 -D "$TLS_DIR/server.key" /etc/nginx/ssl/tmux-web.key
  sudo install -m 644 -D "$TLS_DIR/server.crt" /etc/nginx/ssl/tmux-web.crt
  render_nginx_conf /etc/nginx/ssl/tmux-web.crt /etc/nginx/ssl/tmux-web.key \
    | sudo tee /etc/nginx/sites-available/tmux-web >/dev/null
  sudo ln -sf /etc/nginx/sites-available/tmux-web /etc/nginx/sites-enabled/tmux-web
  if [[ -L /etc/nginx/sites-enabled/default ]]; then
    sudo rm /etc/nginx/sites-enabled/default
    info "nginx 기본 사이트 비활성화 (sites-enabled/default 링크 제거)"
  fi
  sudo nginx -t -q || die "nginx 설정 오류 (sudo nginx -t 로 확인)"
  sudo systemctl enable --now nginx >/dev/null 2>&1
  sudo systemctl reload nginx
  ok "nginx 적용 완료"

  step "이 PC가 CA를 신뢰하도록 등록 (선택)"
  if ask "시스템 인증서 저장소에 CA를 추가할까요? (curl 등 명령줄 도구용)"; then
    sudo install -m 644 "$TLS_DIR/ca.crt" /usr/local/share/ca-certificates/tmux-web-ca.crt
    sudo update-ca-certificates >/dev/null && ok "시스템 저장소에 추가"
  fi
  info "Chrome/Firefox는 브라우저 설정의 인증서 관리에서 $TLS_DIR/ca.crt 를 가져오세요"
fi

if [[ $WITH_PERSIST == 1 ]]; then
  step "tmux-persist (세션 자동 저장, 재부팅 후 복원)"
  "$APP_DIR/addons/tmux-persist/install.sh" | sed 's/^/    /'
  ok "5분마다 자동 저장, 로그인(부팅) 시 자동 복원, 웹 화면 💾 에서 저장/복원"
fi

if [[ $WITH_ORCH == 1 ]]; then
  setup_company
  if [[ $WITH_SERVICE == 1 ]]; then
    unit_dir="$HOME/.config/systemd/user"
    sed -e "s#%h/dev_monitor#$APP_DIR#g" "$APP_DIR/deploy/tmux-web-orchestrator.service" > "$unit_dir/tmux-web-orchestrator.service"
    sed -i "/^\[Service\]/a Environment=PORT=$PORT" "$unit_dir/tmux-web-orchestrator.service"
    systemctl --user daemon-reload
    systemctl --user enable tmux-web-orchestrator >/dev/null 2>&1
    systemctl --user restart tmux-web-orchestrator
    ok "오케스트레이터 실행 (systemctl --user status tmux-web-orchestrator)"
    if [[ -n "${TMUX_WEB_NAS_ROOT:-}" ]]; then
      for f in tmux-web-nas-sync.service tmux-web-nas-sync.timer; do
        sed -e "s#%h/dev_monitor#$APP_DIR#g" "$APP_DIR/deploy/$f" > "$unit_dir/$f"
      done
      sed -i "/^\[Service\]/a Environment=TMUX_WEB_NAS_ROOT=$TMUX_WEB_NAS_ROOT\nEnvironment=PORT=$PORT" "$unit_dir/tmux-web-nas-sync.service"
      sed -i "/^\[Service\]/a Environment=TMUX_WEB_NAS_ROOT=$TMUX_WEB_NAS_ROOT" "$unit_dir/tmux-web.service"
      systemctl --user daemon-reload
      systemctl --user enable --now tmux-web-nas-sync.timer >/dev/null 2>&1
      systemctl --user restart tmux-web
      ok "NAS 동기화 매시간 ($TMUX_WEB_NAS_ROOT)"
    fi
  fi
fi

summary "$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(172\.17\.|192\.168\.122\.)|:' | xargs)"

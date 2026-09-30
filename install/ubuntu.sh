#!/usr/bin/env bash
# tmux 웹 모니터 설치 (Ubuntu / Debian 계열)
#
#  1. 패키지: tmux, python3-venv, openssl, curl, (nginx)
#  2. Python 가상환경 + 의존성
#  3. 로그인 계정
#  4. systemd 사용자 서비스 (부팅 시 자동 시작: linger)
#  5. 설치 방식별 네트워크 설정
#     기본(로컬 네트워크 서버) : 앱이 0.0.0.0:8765 에서 직접 응답, 방화벽(ufw) 허용
#     --https                  : 자체 CA 인증서 + nginx HTTPS (/dev → 127.0.0.1:8765)
#     --local                  : 이 PC에서만 (127.0.0.1:8765)
#
# 여러 번 실행해도 안전 (이미 된 단계는 갱신만 함). sudo 비밀번호를 물을 수 있음.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
parse_args "$@"

[[ $EUID -ne 0 ]] || die "root가 아닌 일반 사용자로 실행하세요 (필요한 곳에서만 sudo 사용)"
command -v apt-get >/dev/null || die "apt-get이 없습니다. Ubuntu/Debian 계열에서 실행하세요"

# ---------- 1. 패키지 ----------
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

# ---------- 2~3. Python / 계정 ----------
setup_venv python3
setup_account

# ---------- 4. systemd 사용자 서비스 ----------
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
  # 로그인하지 않아도 부팅 시 서비스가 뜨도록
  if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]]; then
    sudo loginctl enable-linger "$USER" && ok "부팅 시 자동 시작 (linger) 켬"
  else
    ok "부팅 시 자동 시작 (linger) 이미 켜짐"
  fi
else
  warn "상시 실행 생략: 필요할 때 $APP_DIR/run.sh 로 실행"
fi

# ---------- 5. 네트워크 ----------
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
    # 기본 사이트도 default_server(80)라 충돌 → 링크만 제거 (원본은 sites-available에 남음)
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

summary "$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(172\.17\.|192\.168\.122\.)|:' | xargs)"

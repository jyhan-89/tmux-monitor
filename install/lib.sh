
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${TMUX_WEB_CONFIG:-$HOME/.config/tmux-web}"
TLS_DIR="${TMUX_WEB_TLS:-$CONFIG_DIR/tls}"
PORT="${PORT:-8765}"

ASSUME_YES=0
MODE=lan
WITH_SERVICE=1
WITH_PERSIST=0

if [[ -t 1 ]]; then
  C_B=$'\e[1m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_0=$'\e[0m'
else
  C_B=; C_G=; C_Y=; C_R=; C_0=
fi

step() { echo; echo "${C_B}==> $*${C_0}"; }
info() { echo "    $*"; }
ok()   { echo "    ${C_G}✔${C_0} $*"; }
warn() { echo "    ${C_Y}!${C_0} $*"; }
die()  { echo "${C_R}오류:${C_0} $*" >&2; exit 1; }

ask() {
  [[ $ASSUME_YES == 1 ]] && return 0
  local reply
  read -r -p "    $1 [y/N] " reply </dev/tty || return 1
  [[ $reply =~ ^[Yy] ]]
}

usage() {
  cat <<EOF
사용법: $0 [옵션]
설치 방식 (하나 선택, 기본: 로컬 네트워크 서버)
  (없음)           로컬 네트워크 서버: 같은 네트워크 기기에서 http://<IP>:$PORT/dev 로 접속
  --https          nginx + 자체 인증서로 https://<IP>/dev (알림·홈 화면 앱 사용 가능)
  --local          이 PC에서만: http://localhost:$PORT/dev

기타
  -y, --yes        모든 질문에 '예'로 진행 (계정 만들기는 제외)
  --no-service     상시 실행(자동 시작) 등록 생략
  --with-persist   tmux-persist 함께 설치 (세션 5분마다 자동 저장, 재부팅·로그인 후 복원, 웹에서 저장/복원)
  -h, --help       도움말
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -y|--yes) ASSUME_YES=1 ;;
      --https) MODE=https ;;
      --local) MODE=local ;;
      --no-service) WITH_SERVICE=0 ;;
      --with-persist) WITH_PERSIST=1 ;;
      -h|--help) usage; exit 0 ;;
      *) usage; die "알 수 없는 옵션: $1" ;;
    esac
    shift
  done
}

setup_venv() {
  local py="$1"
  step "Python 가상환경 ($APP_DIR/.venv)"
  "$py" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null \
    || die "Python 3.10 이상이 필요합니다: $("$py" --version 2>&1)"
  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    "$py" -m venv "$APP_DIR/.venv" 2>/dev/null || {
      rm -rf "$APP_DIR/.venv"
      "$py" -m venv --without-pip "$APP_DIR/.venv"
    }
  fi
  if ! "$APP_DIR/.venv/bin/python" -m pip --version >/dev/null 2>&1; then
    info "pip 설치 (get-pip.py)"
    local tmp
    tmp="$(mktemp)"
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$tmp"
    "$APP_DIR/.venv/bin/python" "$tmp" -q
    rm -f "$tmp"
  fi
  "$APP_DIR/.venv/bin/python" -m pip install -q --upgrade pip
  "$APP_DIR/.venv/bin/python" -m pip install -q -r "$APP_DIR/requirements.txt"
  ok "패키지 설치 완료"
}

setup_account() {
  step "로그인 계정"
  if [[ -f "$CONFIG_DIR/auth.json" ]]; then
    ok "계정이 이미 있습니다 (변경: http://localhost:$PORT/dev/setup)"
    return
  fi
  if [[ -t 0 ]] && { read -r -p "    지금 계정을 만들까요? [Y/n] " reply </dev/tty; [[ ! $reply =~ ^[Nn] ]]; }; then
    local user
    read -r -p "    아이디 [$USER]: " user </dev/tty
    "$APP_DIR/.venv/bin/python" "$APP_DIR/auth.py" "${user:-$USER}" </dev/tty
  else
    warn "나중에 이 PC의 브라우저에서 http://localhost:$PORT/dev/setup 을 열어 만드세요"
  fi
}

make_cert() {
  step "HTTPS 인증서 (자체 CA)"
  local out
  out="$(TMUX_WEB_TLS="$TLS_DIR" OPENSSL="${OPENSSL:-openssl}" "$APP_DIR/deploy/make-cert.sh" 2>&1)" \
    || { echo "$out"; die "인증서 생성 실패"; }
  echo "$out" | grep -E '^(새 CA|서버 인증서)' | sed 's/^/    /'
  ok "CA: $TLS_DIR/ca.crt  (접속할 기기마다 한 번 설치)"
}

render_nginx_conf() {
  local crt="$1" key="$2"
  sed -e "s#/etc/nginx/ssl/tmux-web.crt#$crt#" \
      -e "s#/etc/nginx/ssl/tmux-web.key#$key#" \
      -e "s#127.0.0.1:8765#127.0.0.1:$PORT#g" \
      "$APP_DIR/deploy/nginx-tmux-web.conf"
}

wait_healthy() {
  local i
  for i in $(seq 1 30); do
    curl -fs -o /dev/null "http://127.0.0.1:$PORT/dev/login" && return 0
    sleep 0.5
  done
  return 1
}

app_host() { [[ $MODE == lan ]] && echo 0.0.0.0 || echo 127.0.0.1; }

summary() {
  local ips="$1" ip
  step "완료"
  case "$MODE" in
    https)
      for ip in $ips; do info "https://$ip/dev"; done
      info "https://localhost/dev  (이 PC)"
      echo
      info "다른 기기에서 경고가 뜨면 http://<IP>/dev/ca.crt 를 받아 CA로 설치하세요" ;;
    lan)
      for ip in $ips; do info "http://$ip:$PORT/dev"; done
      info "http://localhost:$PORT/dev  (이 PC)"
      echo
      info "HTTP라서 주소창에 '안전하지 않음'이 표시되고, 푸시 알림·홈 화면 앱 설치는 안 됩니다"
      info "필요하면 --https 옵션으로 다시 실행하세요" ;;
    local)
      info "http://localhost:$PORT/dev" ;;
  esac
  if [[ $MODE != local ]]; then
    echo
    info "밖에서 접속하려면 Tailscale 같은 VPN을 쓰세요 (README '외부에서 접속하기')."
    info "공유기 포트포워딩으로 인터넷에 직접 열지 마세요."
  fi
  [[ -f "$CONFIG_DIR/auth.json" ]] || warn "계정 만들기: 이 PC에서 http://localhost:$PORT/dev/setup"
}

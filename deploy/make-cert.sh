#!/usr/bin/env bash
# IP 주소로 HTTPS 접속하기 위한 자체 인증서 생성
#
#  - CA(인증기관)는 처음 한 번만 만들고 재사용 → 기기에는 ca.crt 를 한 번만 설치하면 됨
#  - 서버 인증서는 이 PC의 현재 IP들로 발급. IP가 바뀌면 이 스크립트를 다시 실행하면 됨
#
# 사용법: deploy/make-cert.sh [추가IP ...]
#   OPENSSL=/path/to/openssl 로 openssl 지정 가능 (macOS 기본 LibreSSL 대신 brew openssl 권장)
set -euo pipefail

OPENSSL="${OPENSSL:-openssl}"
DIR="${TMUX_WEB_TLS:-$HOME/.config/tmux-web/tls}"
mkdir -p "$DIR"
chmod 700 "$DIR"
cd "$DIR"

# 1) CA (10년)
if [[ ! -f ca.key ]]; then
  "$OPENSSL" req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout ca.key -out ca.crt -days 3650 \
    -subj "/CN=tmux-web local CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  chmod 600 ca.key
  echo "새 CA 생성: $DIR/ca.crt  (각 기기에 설치 필요)"
fi

# 2) 서버 인증서: 현재 IPv4 주소(가상 브리지 제외) + 호스트 이름
local_ips() {
  if hostname -I >/dev/null 2>&1; then
    hostname -I                                         # Linux
  else
    ifconfig 2>/dev/null | awk '/inet /{print $2}'      # macOS
  fi
}
sans="DNS:$(hostname),DNS:localhost,IP:127.0.0.1"
for ip in $(local_ips) "$@"; do
  case "$ip" in
    127.*|172.17.*|192.168.122.*|*:*) continue ;;  # 루프백, docker/libvirt 브리지, IPv6 제외
  esac
  sans="$sans,IP:$ip"
done

# Apple 기기는 서버 인증서 유효기간 825일 이하만 허용
"$OPENSSL" req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -keyout server.key -out server.csr -subj "/CN=$(hostname)"
"$OPENSSL" x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 800 \
  -extfile <(printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' "$sans")
rm -f server.csr
chmod 600 server.key

echo "서버 인증서 발급: $sans"
echo "인증서 위치: $DIR/server.crt, $DIR/server.key"
echo "nginx 반영: install/ubuntu.sh 또는 install/macos.sh 재실행 (또는 인증서 복사 후 nginx reload)"

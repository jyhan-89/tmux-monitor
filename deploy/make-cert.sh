#!/usr/bin/env bash
set -euo pipefail

OPENSSL="${OPENSSL:-openssl}"
DIR="${TMUX_WEB_TLS:-$HOME/.config/tmux-web/tls}"
mkdir -p "$DIR"
chmod 700 "$DIR"
cd "$DIR"

if [[ ! -f ca.key ]]; then
  "$OPENSSL" req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout ca.key -out ca.crt -days 3650 \
    -subj "/CN=tmux-web local CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  chmod 600 ca.key
  echo "새 CA 생성: $DIR/ca.crt  (각 기기에 설치 필요)"
fi

local_ips() {
  if hostname -I >/dev/null 2>&1; then
    hostname -I
  else
    ifconfig 2>/dev/null | awk '/inet /{print $2}'
  fi
}
sans="DNS:$(hostname),DNS:localhost,IP:127.0.0.1"
for ip in $(local_ips) "$@"; do
  case "$ip" in
    127.*|172.17.*|192.168.122.*|*:*) continue ;;
  esac
  sans="$sans,IP:$ip"
done

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

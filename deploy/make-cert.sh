#!/usr/bin/env bash
# IP 주소로 HTTPS 접속하기 위한 자체 인증서 생성
#
#  - CA(인증기관)는 처음 한 번만 만들고 재사용 → 기기에는 ca.crt 를 한 번만 설치하면 됨
#  - 서버 인증서는 이 PC의 현재 IP들로 발급. IP가 바뀌면 이 스크립트를 다시 실행하면 됨
#
# 사용법: deploy/make-cert.sh [추가IP ...]
set -euo pipefail

DIR="${TMUX_WEB_TLS:-$HOME/.config/tmux-web/tls}"
mkdir -p "$DIR"
chmod 700 "$DIR"
cd "$DIR"

# 1) CA (10년)
if [[ ! -f ca.key ]]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout ca.key -out ca.crt -days 3650 \
    -subj "/CN=tmux-web local CA ($(hostname))" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  chmod 600 ca.key
  echo "새 CA 생성: $DIR/ca.crt  (각 기기에 설치 필요)"
fi

# 2) 서버 인증서: 현재 IP(가상 브리지 제외) + 호스트 이름
sans="DNS:$(hostname),DNS:localhost,IP:127.0.0.1"
for ip in $(hostname -I) "$@"; do
  case "$ip" in
    172.17.*|192.168.122.*|*:*) continue ;;  # docker/libvirt 브리지, IPv6 제외
  esac
  sans="$sans,IP:$ip"
done

# Apple 기기는 서버 인증서 유효기간 825일 이하만 허용
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -keyout server.key -out server.csr -subj "/CN=$(hostname)"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 800 \
  -extfile <(printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n' "$sans")
rm -f server.csr
chmod 600 server.key

echo "서버 인증서 발급: $sans"
echo "nginx 적용: sudo install -m 600 -D $DIR/server.key /etc/nginx/ssl/tmux-web.key && sudo install -m 644 -D $DIR/server.crt /etc/nginx/ssl/tmux-web.crt && sudo systemctl reload nginx"

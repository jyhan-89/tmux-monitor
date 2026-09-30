#!/usr/bin/env bash
# 사용법: ./run.sh            → http://127.0.0.1:8765
#        상시 실행(systemd): systemctl --user status|restart tmux-web
cd "$(dirname "$0")"
exec .venv/bin/python server.py

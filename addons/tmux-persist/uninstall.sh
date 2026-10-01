#!/usr/bin/env bash
set -uo pipefail
systemctl --user disable --now tmux-persist-save.timer tmux-persist-restore.service 2>/dev/null
rm -f ~/.config/systemd/user/tmux-persist-{restore.service,save.service,save.timer}
systemctl --user daemon-reload
rm -f ~/.local/bin/tmux-persist
rm -rf ~/.config/tmux-persist
for conf in ~/.tmux.conf ~/.config/tmux/tmux.conf; do
    [ -f "$conf" ] && sed -i '\|source-file -q ~/.config/tmux-persist/tmux-persist.conf|d' "$conf"
done
echo "uninstalled"

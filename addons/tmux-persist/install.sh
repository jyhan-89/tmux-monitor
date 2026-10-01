#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

install -Dm755 tmux-persist ~/.local/bin/tmux-persist
install -Dm644 tmux-persist.conf ~/.config/tmux-persist/tmux-persist.conf
for f in systemd/*; do
    install -Dm644 "$f" ~/.config/systemd/user/"$(basename "$f")"
done

conf=~/.tmux.conf
[ -f ~/.config/tmux/tmux.conf ] && conf=~/.config/tmux/tmux.conf
line="source-file -q ~/.config/tmux-persist/tmux-persist.conf"
if ! grep -qF "$line" "$conf" 2>/dev/null; then
    echo "$line" >> "$conf"
    echo "added tmux-persist to $conf"
fi

systemctl --user daemon-reload
systemctl --user enable tmux-persist-restore.service
systemctl --user enable --now tmux-persist-save.timer
~/.local/bin/tmux-persist save
systemctl --user start tmux-persist-restore.service
echo "installed"

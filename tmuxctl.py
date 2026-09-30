"""tmux 조회/제어 + 세션 상태(Claude 작업 중/확인 필요/대기) 감지."""

import re
import subprocess

SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh", "tcsh"}

SESSION_FMT = "\t".join(
    ["#{session_name}", "#{session_windows}", "#{session_attached}", "#{session_created}",
     "#{session_activity}", "#{session_group}"]
)
PANE_FMT = "\t".join(
    ["#{session_name}", "#{window_index}", "#{window_name}", "#{window_active}", "#{pane_index}",
     "#{pane_active}", "#{pane_current_command}", "#{pane_current_path}", "#{pane_id}"]
)

# Claude Code 화면 표시로 상태 판단
CLAUDE_HINT = re.compile(r"shift\+tab to cycle|\? for shortcuts|esc to interrupt")
CLAUDE_WAITING = re.compile(r"Do you want to|Would you like to|Enter to (select|confirm)|❯ 1\. Yes")
CLAUDE_WORKING = "esc to interrupt"
BOX_BORDER = re.compile(r"^\s*[─━]{10,}")
# 미리보기에서 뺄 Claude 안내 문구
NOISE = re.compile(r"new task\? /clear|Update installed|^\s*⎿\s+Tip:")


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _rows(*args: str) -> list[list[str]]:
    res = tmux(*args)
    if res.returncode != 0:  # tmux 서버가 없으면 빈 목록
        return []
    return [line.split("\t") for line in res.stdout.splitlines()]


def list_sessions() -> list[dict]:
    sessions: dict[str, dict] = {}
    for name, windows, attached, created, activity, group in _rows("list-sessions", "-F", SESSION_FMT):
        sessions[name] = {
            "name": name, "windows": [], "window_count": int(windows), "attached": int(attached),
            "created": int(created), "activity": int(activity), "group": group,
            "command": "", "path": "", "pane_id": "",
        }
    for sname, widx, wname, wactive, pidx, pactive, cmd, path, pane_id in _rows("list-panes", "-a", "-F", PANE_FMT):
        s = sessions.get(sname)
        if s is None:
            continue
        wins = s["windows"]
        if not wins or wins[-1]["index"] != int(widx):
            wins.append({"index": int(widx), "name": wname, "active": wactive == "1", "panes": []})
        wins[-1]["panes"].append(
            {"index": int(pidx), "active": pactive == "1", "command": cmd, "path": path, "id": pane_id}
        )
        if wactive == "1" and pactive == "1":
            s.update(command=cmd, path=path, pane_id=pane_id)
    return list(sessions.values())


def session_exists(name: str) -> bool:
    return tmux("has-session", "-t", f"={name}").returncode == 0


def capture(target: str, history: int = 0) -> str:
    args = ["capture-pane", "-p", "-J", "-t", target]
    if history:
        args += ["-S", f"-{history}"]
    return tmux(*args).stdout.rstrip("\n")


def analyze(command: str, text: str) -> tuple[str, list[str]]:
    """(상태, 미리보기 줄들). 상태: working | waiting | idle | shell | running"""
    lines = text.splitlines()
    tail = "\n".join(lines[-25:])
    is_claude = command == "claude" or bool(CLAUDE_HINT.search(tail))
    if is_claude:
        if CLAUDE_WAITING.search(tail):
            state = "waiting"
        elif CLAUDE_WORKING in tail:
            state = "working"
        else:
            state = "idle"
        # 하단 입력 박스(─── 테두리) 위쪽 내용을 미리보기로
        cut = len(lines)
        for i in range(len(lines) - 1, max(len(lines) - 15, -1), -1):
            if BOX_BORDER.match(lines[i]):
                cut = i
        body = lines[:cut]
    else:
        state = "shell" if command in SHELLS else "running"
        body = lines
    preview = [line.strip() for line in body if line.strip() and not NOISE.search(line)][-3:]
    return state, preview


def valid_name(name: str) -> bool:
    return bool(name) and not any(c in name for c in ".:") and name == name.strip()

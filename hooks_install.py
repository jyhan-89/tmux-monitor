import json
import sys
from pathlib import Path

import tokens

SCRIPT = Path(__file__).resolve().parent / "hooks" / "claude-event.sh"
EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Notification", "Stop")


def command_for(event: str, script: Path = SCRIPT) -> str:
    return f"{script} {event}"


def merge(settings: dict, script: Path = SCRIPT) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        cmd = command_for(event, script)
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not str(h.get("command", "")).startswith(str(script))]
        groups[:] = [g for g in groups if g.get("hooks")]
        entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
        if event == "PostToolUse":
            entry["matcher"] = "*"
        groups.append(entry)
    return settings


def install(folder: Path, script: Path = SCRIPT) -> Path:
    path = folder / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text())
    except FileNotFoundError:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError(f"{path}가 JSON 객체가 아닙니다")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merge(settings, script), ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)
    tokens.ensure_hook_token()
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("사용법: hooks_install.py <프로젝트 폴더>")
    print(install(Path(sys.argv[1]).expanduser().resolve()))

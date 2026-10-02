import fcntl
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("TMUX_WEB_DATA", "~/.local/share/tmux-web")).expanduser()
REQUIRED = ("ts", "type", "session")
SENSITIVE = re.compile(r"token|password|secret|key", re.I)
MASK = "***"


def root() -> Path:
    return DATA_DIR / "history"


def _now() -> datetime:
    return datetime.now().astimezone()


def _mask(value):
    if isinstance(value, dict):
        return {k: MASK if SENSITIVE.search(str(k)) else _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _file(day: datetime) -> Path:
    return root() / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.jsonl"


def record(event: dict) -> dict:
    event = {"ts": _now().isoformat(timespec="seconds"), **event}
    missing = [k for k in REQUIRED if not event.get(k)]
    if missing:
        raise ValueError(f"이력 필수 필드 누락: {missing}")
    event = _mask(event)
    path = _file(datetime.fromisoformat(event["ts"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return event


def query(since: datetime | None = None, type: str | None = None, session: str | None = None, limit: int = 200) -> list[dict]:
    end = _now()
    start = since or end - timedelta(days=1)
    out: list[dict] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day.date() <= end.date():
        path = _file(day)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if datetime.fromisoformat(ev["ts"]) < start:
                    continue
                if type and ev.get("type") != type:
                    continue
                if session and ev.get("session") != session:
                    continue
                out.append(ev)
        day += timedelta(days=1)
    return out[-limit:]

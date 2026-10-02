import json
import secrets
import time
from pathlib import Path

import history


def root() -> Path:
    return history.DATA_DIR / "state" / "commands"


def put(cmd: str, **args) -> dict:
    root().mkdir(parents=True, exist_ok=True)
    item = {"cmd": cmd, "at": time.time(), **args}
    name = f"{time.time_ns()}-{secrets.token_hex(3)}.json"
    tmp = root() / f".{name}"
    tmp.write_text(json.dumps(item, ensure_ascii=False))
    tmp.replace(root() / name)
    return item


def take() -> list[dict]:
    if not root().exists():
        return []
    out = []
    for p in sorted(root().glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            pass
        p.unlink(missing_ok=True)
    return out


def instances() -> list[dict]:
    d = history.DATA_DIR / "state"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*/*.json"))] if d.exists() else []

"""~/.config/tmux-web 아래 JSON 설정 파일 읽기/쓰기."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TMUX_WEB_CONFIG", "~/.config/tmux-web")).expanduser()

DEFAULT_CONFIG = {
    # 자주 쓰는 명령 버튼
    "snippets": ["claude", "claude --continue", "/compact", "/clear", "git status", "git log --oneline -10"],
    # 새 세션 만들 때 최근 사용한 폴더
    "recent_dirs": [],
}


def path(name: str) -> Path:
    return CONFIG_DIR / name


def load(name: str, default):
    try:
        return json.loads(path(name).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name: str, data) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(path(name))


def load_config() -> dict:
    return {**DEFAULT_CONFIG, **load("config.json", {})}


def save_config(cfg: dict) -> None:
    save("config.json", cfg)


def add_recent_dir(d: str) -> None:
    cfg = load_config()
    cfg["recent_dirs"] = [d] + [x for x in cfg["recent_dirs"] if x != d][:9]
    save_config(cfg)


# ---------- 세션 그룹 ----------
# config["groups"] = {"그룹 이름": ["세션1", "세션2", ...]}  (tmux 세션 이름 기준)

def groups() -> dict[str, list[str]]:
    return load_config().get("groups", {})


def _save_groups(gs: dict[str, list[str]]) -> None:
    cfg = load_config()
    cfg["groups"] = gs
    save_config(cfg)


def group_of() -> dict[str, str]:
    return {s: g for g, members in groups().items() for s in members}


def create_group(name: str) -> None:
    gs = groups()
    if name in gs:
        raise ValueError("이미 있는 그룹입니다")
    gs[name] = []
    _save_groups(gs)


def rename_group(old: str, new: str) -> None:
    gs = groups()
    if old not in gs:
        raise KeyError("그룹이 없습니다")
    if new != old and new in gs:
        raise ValueError("이미 있는 그룹입니다")
    # 순서 유지하며 키만 교체
    _save_groups({(new if k == old else k): v for k, v in gs.items()})


def delete_group(name: str) -> list[str]:
    gs = groups()
    if name not in gs:
        raise KeyError("그룹이 없습니다")
    members = gs.pop(name)
    _save_groups(gs)
    return members


def move_session(session: str, group: str | None) -> None:
    gs = {g: [s for s in members if s != session] for g, members in groups().items()}
    if group is not None:
        if group not in gs:
            raise KeyError("그룹이 없습니다")
        gs[group].append(session)
    _save_groups(gs)


def rename_session(old: str, new: str) -> None:
    gs = groups()
    if any(old in members for members in gs.values()):
        _save_groups({g: [new if s == old else s for s in members] for g, members in gs.items()})


def forget_session(session: str) -> None:
    gs = groups()
    if any(session in members for members in gs.values()):
        _save_groups({g: [s for s in members if s != session] for g, members in gs.items()})

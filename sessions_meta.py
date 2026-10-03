from collections.abc import Callable

import store
from tmuxctl import parse_role_session

FILE = "sessions_meta.json"
FIELDS = ("division", "dept", "role", "suffix", "branch", "worktree", "node", "grouped", "assigned", "configured", "builtin")


def all_meta() -> dict[str, dict]:
    return store.load(FILE, {})


def get(name: str) -> dict | None:
    return all_meta().get(name)


def update(name: str, **fields: str | None) -> dict:
    bad = set(fields) - set(FIELDS)
    if bad:
        raise KeyError(f"알 수 없는 메타 필드: {sorted(bad)}")
    data = all_meta()
    meta = {**data.get(name, {}), **{k: v for k, v in fields.items() if v is not None}}
    data[name] = meta
    store.save(FILE, data)
    return meta


def rename(old: str, new: str) -> None:
    data = all_meta()
    if old in data:
        data[new] = data.pop(old)
        store.save(FILE, data)


def forget(name: str) -> None:
    data = all_meta()
    if data.pop(name, None) is not None:
        store.save(FILE, data)


def adopt(names: list[str], known: Callable[[dict], bool] = lambda parsed: False) -> bool:
    data = all_meta()
    changed = False
    for name in names:
        parsed = parse_role_session(name)
        if not parsed or name in data or not known(parsed):
            continue
        data[name] = {"division": parsed["division"], "dept": parsed["dept"], "role": parsed["role"],
                      "suffix": parsed["suffix"]}
        changed = True
    if changed:
        store.save(FILE, data)
    return changed


def slot_key(division: str, dept: str, role: str, suffix: str | None) -> tuple:
    return (division, dept, role, suffix or None)


def assigned_to(division: str, dept: str, role: str, suffix: str | None) -> str | None:
    want = slot_key(division, dept, role, suffix)
    for name, m in all_meta().items():
        if not m.get("assigned"):
            continue
        div = division if m.get("division") == "*" and dept == "shared" else m.get("division")
        if slot_key(div, m.get("dept"), m.get("role"), m.get("suffix")) == want:
            return name
    return None


def unassign(name: str) -> dict | None:
    data = all_meta()
    meta = data.get(name)
    if not meta or not meta.get("assigned"):
        return None
    data.pop(name)
    store.save(FILE, data)
    return meta

import store
from tmuxctl import parse_role_session

FILE = "sessions_meta.json"
FIELDS = ("division", "dept", "role", "branch", "worktree", "node")


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


def adopt(names: list[str]) -> bool:
    data = all_meta()
    grouped = store.group_of()
    changed = False
    for name in names:
        parsed = parse_role_session(name)
        if not parsed or name in data:
            continue
        data[name] = {"division": parsed["division"], "dept": parsed["dept"], "role": parsed["role"]}
        changed = True
        if name not in grouped:
            group = f"{parsed['division']}/{parsed['dept']}"
            if group not in store.groups():
                store.create_group(group)
            store.move_session(name, group)
    if changed:
        store.save(FILE, data)
    return changed

import fcntl
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

import history
import models
import sessions_meta
import tokens
from tmuxctl import parse_role_session

PRIORITIES = ("blocking", "normal", "low")
TRANSITIONS = {
    "delivered": {"acked"},
    "acked": {"in_progress"},
    "in_progress": {"done", "blocked", "rejected"},
}
NEEDS_REASON = {"blocked", "rejected"}
OPEN = {"queued", "delivered", "acked", "in_progress"}
SYSTEM = {"orchestrator", "user"}
NOTICE = "notice"
ID_RE = re.compile(r"^d-\d{8}-\d{4}$")


class DirectiveError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def root() -> Path:
    return history.DATA_DIR / "directives"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def _lock():
    root().mkdir(parents=True, exist_ok=True)
    with open(root() / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _path(to: str, did: str) -> Path:
    return root() / to / f"{did}.yaml"


def _write(d: dict) -> None:
    p = _path(d["to"], d["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False))
    tmp.replace(p)


def _new_id() -> str:
    day = datetime.now().strftime("%Y%m%d")
    seq_file = root() / f".seq-{day}"
    n = int(seq_file.read_text() or 0) + 1 if seq_file.exists() else 1
    seq_file.write_text(str(n))
    return f"d-{day}-{n:04d}"


def get(did: str) -> dict:
    if not ID_RE.match(did):
        raise DirectiveError(404, "지시서가 없습니다")
    for p in root().glob(f"*/{did}.yaml"):
        return yaml.safe_load(p.read_text())
    raise DirectiveError(404, "지시서가 없습니다")


def inbox(to: str, include_closed: bool = False) -> list[dict]:
    folder = root() / to
    items = [yaml.safe_load(p.read_text()) for p in sorted(folder.glob("d-*.yaml"))] if folder.exists() else []
    if not include_closed:
        items = [d for d in items if d["status"] in OPEN]
    return sorted(items, key=lambda d: (PRIORITIES.index(d["priority"]), d["created"], d["id"]))


def directive_types() -> dict[str, models.DirectiveType]:
    p = tokens.company_dir() / "documents.yaml"
    if not p.exists():
        raise DirectiveError(409, "documents.yaml 정의가 없어 지시서를 쓸 수 없습니다")
    return models.parse_documents(p.read_text()).directives


def role_of(session: str) -> str | None:
    return (sessions_meta.get(session) or {}).get("role") or (parse_role_session(session) or {}).get("role")


def _log(d: dict, status: str, reason: str | None = None, by: str | None = None) -> None:
    entry = {"at": _now(), "to": status}
    if reason:
        entry["reason"] = reason
    old = d["status"]
    d["status"] = status
    d["status_log"].append(entry)
    history.record({"type": "directive_status", "session": d["to"], "directive": d["id"], "from": old, "to": status,
                    "reason": reason, "by": by or d["to"]})


def create(dtype: str, sender: str, to: str, body: str, priority: str = "normal", deliverable: bool = True) -> dict:
    if priority not in PRIORITIES:
        raise DirectiveError(400, f"priority는 {', '.join(PRIORITIES)} 중 하나입니다")
    if not body.strip():
        raise DirectiveError(400, "본문이 비어 있습니다")
    if dtype != NOTICE:
        types = directive_types()
        t = types.get(dtype)
        if not t:
            raise DirectiveError(400, f"알 수 없는 지시서 종류: {dtype}")
        if sender not in ("user", "ceo"):
            sender_role = "orchestrator" if sender == "orchestrator" else role_of(sender)
            if t.sender != "any" and sender_role != t.sender:
                raise DirectiveError(403, f"'{dtype}' 지시서는 {t.sender}만 쓸 수 있습니다")
        to_role = "orchestrator" if to == "orchestrator" else role_of(to)
        if "any" not in t.to and to_role not in t.to:
            raise DirectiveError(403, f"'{dtype}' 지시서는 {', '.join(t.to)}에게만 보낼 수 있습니다")
    if to != "orchestrator" and not parse_role_session(to) and not sessions_meta.get(to):
        raise DirectiveError(400, f"역할 세션이 아닙니다: {to}")
    with _lock():
        d = {"id": _new_id(), "type": dtype, "from": sender, "to": to, "priority": priority, "version": 1,
             "status": "queued", "created": _now(), "status_log": [{"at": _now(), "to": "queued"}], "refs": [], "body": body}
        history.record({"type": "directive_created", "session": to, "directive": d["id"], "directive_type": dtype, "from": sender})
        if deliverable:
            _deliver(d)
        _write(d)
    return d


def _deliver(d: dict) -> None:
    if d["status"] != "queued":
        return
    meta = sessions_meta.get(d["to"]) or {}
    worktree = meta.get("worktree")
    if worktree and Path(worktree).is_dir():
        target = Path(worktree) / "coord" / "inbox" / f"{d['id']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(d["body"])
        target.chmod(0o444)
    _log(d, "delivered", by="server")
    history.record({"type": "directive_delivered", "session": d["to"], "directive": d["id"]})


def deliver_pending(to: str) -> int:
    n = 0
    with _lock():
        for d in inbox(to):
            if d["status"] == "queued":
                _deliver(d)
                _write(d)
                n += 1
    return n


def update_body(did: str, sender: str, body: str) -> dict:
    d = get(did)
    if sender != "user" and d["from"] != sender:
        raise DirectiveError(403, "작성자만 본문을 바꿀 수 있습니다")
    if d["status"] in ("queued", "delivered"):
        with _lock():
            d["body"] = body
            d["version"] += 1
            _write(d)
            meta = sessions_meta.get(d["to"]) or {}
            if d["status"] == "delivered" and meta.get("worktree"):
                target = Path(meta["worktree"]) / "coord" / "inbox" / f"{d['id']}.md"
                if target.exists():
                    target.chmod(0o644)
                    target.write_text(body)
                    target.chmod(0o444)
        return d
    if d["status"] not in OPEN:
        raise DirectiveError(409, "끝난 지시서는 바꿀 수 없습니다")
    new = create(d["type"], d["from"], d["to"], body, d["priority"])
    new["supersedes"] = did
    with _lock():
        _write(new)
    return new


def set_status(did: str, session: str, status: str, reason: str | None = None, refs: list[str] | None = None) -> dict:
    with _lock():
        d = get(did)
        if d["to"] != session:
            raise DirectiveError(403, "수신자만 상태를 바꿀 수 있습니다")
        if status not in TRANSITIONS.get(d["status"], set()):
            raise DirectiveError(409, f"'{d['status']}'에서 '{status}'(으)로 바꿀 수 없습니다")
        if status in NEEDS_REASON and not (reason or "").strip():
            raise DirectiveError(400, f"'{status}'에는 사유가 필요합니다")
        if status == "in_progress" and any(x["status"] == "in_progress" for x in inbox(session) if x["id"] != did):
            raise DirectiveError(409, "진행 중인 지시서가 이미 있습니다. 먼저 끝내거나 blocked로 바꾸세요")
        if refs:
            d["refs"] = list(dict.fromkeys(d["refs"] + refs))
        _log(d, status, reason, by=session)
        _write(d)
    if status in NEEDS_REASON and d["from"] not in ("user",):
        create(NOTICE, "server", d["from"] if d["from"] != "server" else "orchestrator",
               f"지시서 {did}({d['type']})가 {session}에서 {status}: {reason}", "blocking")
    return d

import fcntl
import json
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import history

KINDS = ("gate", "escalate", "needs_input", "external")
NEEDS_REASON = {"reject", "revise", "redesign", "drop", "override"}
DEFAULT_OPTIONS = {"gate": ["approve", "reject", "revise"], "escalate": ["redesign", "drop", "override"],
                   "needs_input": ["answered"], "external": ["approve", "reject"]}
notify = None


class ApprovalError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def root() -> Path:
    return history.DATA_DIR / "approvals"


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


def _write(a: dict) -> None:
    p = root() / f"{a['id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(a, ensure_ascii=False, indent=1))
    tmp.replace(p)


def all_items() -> list[dict]:
    if not root().exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(root().glob("ap-*.json"))]


def query(status: str | None = None) -> list[dict]:
    items = all_items()
    if status:
        items = [a for a in items if a["status"] == status]
    return sorted(items, key=lambda a: a["created"], reverse=True)


def get(aid: str) -> dict:
    p = root() / f"{aid}.json"
    if not aid.startswith("ap-") or "/" in aid or not p.exists():
        raise ApprovalError(404, "결재 항목이 없습니다")
    return json.loads(p.read_text())


def _new_id() -> str:
    day = datetime.now().strftime("%Y%m%d")
    seq = root() / f".seq-{day}"
    n = int(seq.read_text() or 0) + 1 if seq.exists() else 1
    seq.write_text(str(n))
    return f"ap-{day}-{n:04d}"


def create(kind: str, instance: str, node: str, summary: str, evidence: list[str] | None = None,
           options: list[str] | None = None, session: str | None = None) -> dict:
    if kind not in KINDS:
        raise ApprovalError(400, f"종류는 {', '.join(KINDS)} 중 하나입니다")
    with _lock():
        for a in all_items():
            if a["status"] == "pending" and (a["kind"], a["instance"], a["node"]) == (kind, instance, node):
                return a
        a = {"id": _new_id(), "kind": kind, "instance": instance, "node": node, "session": session,
             "summary": summary, "evidence": evidence or [], "options": options or DEFAULT_OPTIONS[kind],
             "status": "pending", "created": _now(), "decision": None, "reason": None, "decided": None}
        _write(a)
    history.record({"type": "approval_request", "session": session or "-", "approval": a["id"], "kind": kind,
                    "instance": instance, "node": node})
    if notify:
        division, _, feature = instance.partition("/")
        title = {"gate": "결재 요청", "escalate": "에스컬레이션", "needs_input": "확인 필요", "external": "외부 발송 결재"}[kind]
        threading.Thread(target=notify, args=(f"📝 {title} · {division} · {feature}", summary[:120], session), daemon=True).start()
    return a


def decide(aid: str, decision: str, reason: str | None = None, by: str = "user") -> dict:
    with _lock():
        a = get(aid)
        if a["status"] != "pending":
            raise ApprovalError(409, "이미 처리된 결재입니다")
        if decision not in a["options"]:
            raise ApprovalError(400, f"선택지는 {', '.join(a['options'])} 중 하나입니다")
        if decision in NEEDS_REASON and not (reason or "").strip():
            raise ApprovalError(400, "사유를 입력하세요")
        a.update(status="decided", decision=decision, reason=reason, decided=_now(), by=by)
        _write(a)
    history.record({"type": "approval_result", "session": a.get("session") or "-", "approval": aid,
                    "decision": decision, "reason": reason, "by": by})
    return a


def close(aid: str, reason: str) -> dict:
    with _lock():
        a = get(aid)
        if a["status"] != "pending":
            return a
        a.update(status="closed", reason=reason, decided=_now())
        _write(a)
    history.record({"type": "approval_result", "session": a.get("session") or "-", "approval": aid,
                    "decision": "closed", "reason": reason, "by": "orchestrator"})
    return a

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import directives
import tmuxctl
import tokens

router = APIRouter(prefix="/api/directives")
any_caller = tokens.require("directives.manage", "directives.self")


def sender_of(who: dict) -> str:
    if who["role"] == "session":
        return who["session"]
    return "orchestrator" if who["role"] == "orchestrator" else "user"


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except directives.DirectiveError as e:
        raise HTTPException(e.status, str(e))


class NewDirective(BaseModel):
    type: str
    to: str
    body: str
    priority: str = "normal"


@router.post("")
def api_create(body: NewDirective, who: dict = Depends(any_caller)):
    deliverable = body.to == "orchestrator" or tmuxctl.session_exists(body.to)
    return guard(directives.create, body.type, sender_of(who), body.to, body.body, body.priority, deliverable)


@router.get("")
def api_list(to: str | None = None, all: bool = False, who: dict = Depends(any_caller)):
    if who["role"] == "session":
        if to not in (None, who["session"]):
            raise HTTPException(403, "자기 수신함만 볼 수 있습니다")
        to = who["session"]
    if not to:
        raise HTTPException(400, "to가 필요합니다")
    return directives.inbox(to, include_closed=all)


@router.get("/{did}")
def api_get(did: str, who: dict = Depends(any_caller)):
    d = guard(directives.get, did)
    if who["role"] == "session" and who["session"] not in (d["to"], d["from"]):
        raise HTTPException(403, "작성자와 수신자만 볼 수 있습니다")
    return d


class BodyUpdate(BaseModel):
    body: str


@router.put("/{did}")
def api_update(did: str, body: BodyUpdate, who: dict = Depends(any_caller)):
    return guard(directives.update_body, did, sender_of(who), body.body)


class StatusChange(BaseModel):
    status: str
    reason: str | None = None
    refs: list[str] | None = None


@router.post("/{did}/status")
def api_status(did: str, body: StatusChange, who: dict = Depends(tokens.require("directives.self", allow_login=False))):
    return guard(directives.set_status, did, who["session"], body.status, body.reason, body.refs)


@router.post("/deliver/{session}")
def api_deliver(session: str, _: dict = Depends(tokens.require("directives.manage"))):
    return {"delivered": directives.deliver_pending(session)}

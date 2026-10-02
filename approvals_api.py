from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import approvals
import tokens

router = APIRouter(prefix="/api/approvals")


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except approvals.ApprovalError as e:
        raise HTTPException(e.status, str(e))


@router.get("")
def api_list(status: str | None = None, _: dict = Depends(tokens.require("approvals.manage"))):
    return approvals.query(status)


@router.get("/{aid}")
def api_get(aid: str, _: dict = Depends(tokens.require("approvals.manage"))):
    return guard(approvals.get, aid)


class NewApproval(BaseModel):
    kind: str
    instance: str
    node: str
    summary: str
    evidence: list[str] = []
    options: list[str] | None = None
    session: str | None = None


@router.post("")
def api_create(body: NewApproval, _: dict = Depends(tokens.require("approvals.manage"))):
    return guard(approvals.create, body.kind, body.instance, body.node, body.summary, body.evidence, body.options, body.session)


class Decision(BaseModel):
    decision: str
    reason: str | None = None


@router.post("/{aid}/decide")
def api_decide(aid: str, body: Decision, who: dict = Depends(tokens.require("approvals.decide"))):
    return guard(approvals.decide, aid, body.decision, body.reason, who["role"])


class Close(BaseModel):
    reason: str


@router.post("/{aid}/close")
def api_close(aid: str, body: Close, _: dict = Depends(tokens.require("approvals.manage"))):
    return guard(approvals.close, aid, body.reason)

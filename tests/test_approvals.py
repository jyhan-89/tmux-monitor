import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import approvals
import approvals_api
import history
import store
import tokens


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")
    sent = []
    monkeypatch.setattr(approvals, "notify", lambda title, body, session: sent.append((title, body, session)))
    app = FastAPI()
    app.include_router(approvals_api.router)
    c = TestClient(app, client=("127.0.0.1", 5000))
    orch = {"Authorization": f"Bearer {tokens.issue('orchestrator')}"}
    return c, orch, sent


def create(c, h, **kw):
    body = {"kind": "gate", "instance": "mw/svc_a", "node": "integrate", "summary": "머지 승인", "evidence": ["feat/a@1"], **kw}
    return c.post("/api/approvals", json=body, headers=h)


def test_create_dedupe_and_notify(env):
    c, orch, sent = env
    a = create(c, orch).json()
    assert a["status"] == "pending" and a["options"] == ["approve", "reject", "revise"]
    assert create(c, orch).json()["id"] == a["id"]
    assert create(c, orch, node="sil2").json()["id"] != a["id"]
    import time
    time.sleep(0.1)
    assert sent and "mw" in sent[0][0] and "svc_a" in sent[0][0]
    assert [x["type"] for x in history.query()].count("approval_request") == 2


def test_decide_rules(env):
    c, orch, _ = env
    aid = create(c, orch).json()["id"]
    user = {"c": "ok"}
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "approve"}, headers=orch).status_code == 403
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "ship"}, cookies=user).status_code == 400
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "reject"}, cookies=user).status_code == 400
    r = c.post(f"/api/approvals/{aid}/decide", json={"decision": "reject", "reason": "범위 초과"}, cookies=user).json()
    assert r["status"] == "decided" and r["decision"] == "reject" and r["by"] == "user"
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "approve"}, cookies=user).status_code == 409
    assert history.query(type="approval_result")[0]["reason"] == "범위 초과"


def test_list_filter_close_and_missing(env):
    c, orch, _ = env
    a = create(c, orch).json()["id"]
    b = create(c, orch, kind="needs_input", node="implement", session="mw-impl-impl-1").json()["id"]
    assert {x["id"] for x in c.get("/api/approvals", params={"status": "pending"}, cookies={"c": "ok"}).json()} == {a, b}
    assert c.post(f"/api/approvals/{b}/close", json={"reason": "답함"}, headers=orch).json()["status"] == "closed"
    assert [x["id"] for x in c.get("/api/approvals", params={"status": "pending"}, headers=orch).json()] == [a]
    assert c.get("/api/approvals/ap-x", headers=orch).status_code == 404
    assert c.get("/api/approvals/../secrets", headers=orch).status_code == 404
    assert create(c, orch, kind="party").status_code == 400


def test_ceo_can_decide(env):
    c, orch, _ = env
    aid = create(c, orch).json()["id"]
    ceo = {"Authorization": f"Bearer {tokens.issue('ceo', 'ceo')}"}
    r = c.post(f"/api/approvals/{aid}/decide", json={"decision": "approve"}, headers=ceo).json()
    assert r["status"] == "decided" and r["by"] == "ceo"

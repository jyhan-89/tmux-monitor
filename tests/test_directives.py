import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import directives
import directives_api
import history
import sessions_meta
import store
import tmuxctl
import tokens

SAMPLE = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"
DESIGN = "mw-design-feature_design-1"
IMPL = "mw-impl-impl-skeleton"
IMPL2 = "mw-impl-impl-proxy"
REVIEW = "mw-quality-reviewer"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")
    monkeypatch.setattr(tmuxctl, "session_exists", lambda name: True)
    tokens.company_dir().mkdir(parents=True)
    shutil.copy(SAMPLE / "documents.yaml", tokens.company_dir() / "documents.yaml")
    app = FastAPI()
    app.include_router(directives_api.router)
    c = TestClient(app, client=("127.0.0.1", 5000))
    tok = {s: tokens.issue("session", s) for s in (DESIGN, IMPL, IMPL2, REVIEW)}
    tok["orchestrator"] = tokens.issue("orchestrator")

    def as_(who):
        return {"Authorization": f"Bearer {tok[who]}"}
    return c, as_, tmp_path


def send(c, h, type_, to, body="do it", priority="normal"):
    return c.post("/api/directives", json={"type": type_, "to": to, "body": body, "priority": priority}, headers=h)


def status(c, h, did, st, **kw):
    return c.post(f"/api/directives/{did}/status", json={"status": st, **kw}, headers=h)


def test_full_lifecycle(env):
    c, as_, _ = env
    r = send(c, as_(DESIGN), "task", IMPL)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "delivered" and d["from"] == DESIGN
    did = d["id"]
    for st in ("acked", "in_progress"):
        assert status(c, as_(IMPL), did, st).status_code == 200
    r = status(c, as_(IMPL), did, "done", refs=["feat/svc-a/skeleton@a1b2c3"])
    assert r.json()["status"] == "done" and r.json()["refs"] == ["feat/svc-a/skeleton@a1b2c3"]
    assert [x["to"] for x in r.json()["status_log"]] == ["queued", "delivered", "acked", "in_progress", "done"]
    types = [e["type"] for e in history.query()]
    assert types.count("directive_status") == 4 and "directive_created" in types and "directive_delivered" in types


def test_sender_and_recipient_rules(env):
    c, as_, _ = env
    assert send(c, as_(IMPL), "task", IMPL2).status_code == 403
    assert send(c, as_(DESIGN), "task", REVIEW).status_code == 403
    assert send(c, as_(DESIGN), "launch", IMPL).status_code == 400
    assert send(c, as_(DESIGN), "task", "dev_monitor").status_code == 403
    assert send(c, as_("orchestrator"), "node", REVIEW).status_code == 200
    assert send(c, as_("orchestrator"), "merge", IMPL).status_code == 403
    assert send(c, as_(DESIGN), "task", IMPL, priority="urgent").status_code == 400


def test_only_recipient_changes_status_in_order(env):
    c, as_, _ = env
    did = send(c, as_(DESIGN), "task", IMPL).json()["id"]
    assert status(c, as_(DESIGN), did, "acked").status_code == 403
    assert status(c, as_(IMPL2), did, "acked").status_code == 403
    assert status(c, as_(IMPL), did, "in_progress").status_code == 409
    assert status(c, as_(IMPL), did, "acked").status_code == 200
    assert status(c, as_(IMPL), did, "delivered").status_code == 409
    assert c.post(f"/api/directives/{did}/status", json={"status": "in_progress"}, cookies={"c": "ok"}).status_code == 401


def test_reason_required_and_author_notified(env):
    c, as_, _ = env
    did = send(c, as_(DESIGN), "task", IMPL).json()["id"]
    status(c, as_(IMPL), did, "acked")
    status(c, as_(IMPL), did, "in_progress")
    assert status(c, as_(IMPL), did, "blocked").status_code == 400
    assert status(c, as_(IMPL), did, "blocked", reason="인터페이스 타입 불일치").status_code == 200
    notes = c.get("/api/directives", headers=as_(DESIGN)).json()
    assert len(notes) == 1 and notes[0]["type"] == "notice" and notes[0]["priority"] == "blocking"
    assert "인터페이스 타입 불일치" in notes[0]["body"]


def test_one_in_progress_and_queue_order(env):
    c, as_, _ = env
    a = send(c, as_(DESIGN), "task", IMPL, priority="low").json()["id"]
    b = send(c, as_(DESIGN), "task", IMPL).json()["id"]
    k = send(c, as_(DESIGN), "task", IMPL, priority="blocking").json()["id"]
    assert [d["id"] for d in c.get("/api/directives", headers=as_(IMPL)).json()] == [k, b, a]
    for did in (a, b):
        status(c, as_(IMPL), did, "acked")
    assert status(c, as_(IMPL), a, "in_progress").status_code == 200
    assert status(c, as_(IMPL), b, "in_progress").status_code == 409


def test_inbox_visibility(env):
    c, as_, _ = env
    did = send(c, as_(DESIGN), "task", IMPL).json()["id"]
    assert c.get("/api/directives", params={"to": IMPL}, headers=as_(IMPL2)).status_code == 403
    assert c.get(f"/api/directives/{did}", headers=as_(IMPL2)).status_code == 403
    assert c.get(f"/api/directives/{did}", headers=as_(DESIGN)).status_code == 200
    assert c.get("/api/directives", params={"to": IMPL}, cookies={"c": "ok"}).json()[0]["id"] == did


def test_body_update_versions(env):
    c, as_, _ = env
    did = send(c, as_(DESIGN), "task", IMPL, body="v1").json()["id"]
    r = c.put(f"/api/directives/{did}", json={"body": "v2"}, headers=as_(DESIGN)).json()
    assert r["id"] == did and r["version"] == 2 and r["body"] == "v2"
    assert c.put(f"/api/directives/{did}", json={"body": "x"}, headers=as_(IMPL)).status_code == 403
    status(c, as_(IMPL), did, "acked")
    r = c.put(f"/api/directives/{did}", json={"body": "v3"}, headers=as_(DESIGN)).json()
    assert r["id"] != did and r["supersedes"] == did and r["body"] == "v3"


def test_inbox_copy_to_worktree(env):
    c, as_, tmp = env
    wt = tmp / "wt"
    wt.mkdir()
    sessions_meta.update(IMPL, worktree=str(wt))
    did = send(c, as_(DESIGN), "task", IMPL, body="본문").json()["id"]
    f = wt / "coord" / "inbox" / f"{did}.md"
    assert f.read_text() == "본문"
    assert f.stat().st_mode & 0o222 == 0


def test_queued_until_session_exists(env, monkeypatch):
    c, as_, _ = env
    monkeypatch.setattr(tmuxctl, "session_exists", lambda name: False)
    d = send(c, as_(DESIGN), "task", IMPL).json()
    assert d["status"] == "queued"
    assert c.post(f"/api/directives/deliver/{IMPL}", headers=as_("orchestrator")).json() == {"delivered": 1}
    assert directives.get(d["id"])["status"] == "delivered"


def test_missing_definitions(env):
    c, as_, _ = env
    (tokens.company_dir() / "documents.yaml").unlink()
    assert send(c, as_(DESIGN), "task", IMPL).status_code == 409

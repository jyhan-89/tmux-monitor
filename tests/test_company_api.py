import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import company_api
import store
import tokens

SAMPLE = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")
    app = FastAPI()
    app.include_router(company_api.router)
    c = TestClient(app, client=("127.0.0.1", 5000))
    c.cookies.set("c", "ok")
    return c


def put(c, kind, text):
    return c.put(f"/api/company/{kind}", json={"text": text})


def test_put_all_and_read(client):
    for k in ("org", "process", "documents"):
        assert put(client, k, (SAMPLE / f"{k}.yaml").read_text()).status_code == 200
    s = client.get("/api/company").json()
    assert s["complete"] and s["issues"] == []
    assert "미들웨어" in client.get("/api/company/org").json()["text"]
    log = subprocess.run(["git", "log", "--oneline"], cwd=tokens.company_dir(), capture_output=True, text=True).stdout
    assert log.count("수정") == 3
    assert "secrets/" in (tokens.company_dir() / ".gitignore").read_text()


def test_put_rejected_with_rule_and_location(client):
    for k in ("org", "process", "documents"):
        put(client, k, (SAMPLE / f"{k}.yaml").read_text())
    proc = yaml.safe_load((SAMPLE / "process.yaml").read_text())
    del proc["templates"]["feature_dev"]["nodes"]["review"]["on_fail"]
    r = put(client, "process", yaml.safe_dump(proc))
    assert r.status_code == 400
    issues = r.json()["detail"]["issues"]
    assert {"rule": "on_fail", "where": "process.templates.feature_dev.nodes.review.on_fail"}.items() <= issues[0].items()
    assert (tokens.company_dir() / "process.yaml").read_text() == (SAMPLE / "process.yaml").read_text()


def test_cross_check_only_when_complete(client):
    assert put(client, "process", (SAMPLE / "process.yaml").read_text()).status_code == 200
    assert client.get("/api/company").json()["complete"] is False
    assert put(client, "org", "version: 1\ndivisions: [\n").status_code == 400


def test_unknown_kind_and_auth(client):
    assert client.get("/api/company/secrets").status_code == 404
    client.cookies.clear()
    assert client.get("/api/company/org").status_code == 401
    orch = tokens.issue("orchestrator")
    h = {"Authorization": f"Bearer {orch}"}
    assert client.get("/api/company/org", headers=h).status_code == 200
    assert client.put("/api/company/org", json={"text": ""}, headers=h).status_code == 403


def test_model_and_patch(client):
    for k in ("org", "process", "documents"):
        put(client, k, (SAMPLE / f"{k}.yaml").read_text())
    m = client.get("/api/company/model").json()
    assert m["org"]["divisions"]["mw"]["depts"]["impl"]["members"]["count"] == 2
    r = client.patch("/api/company/org", json={"ops": [
        {"path": ["divisions", "mw", "depts", "impl", "members", "model"], "value": "opus"},
        {"path": ["roles", "impl", "can_edit"], "value": ["src/**"]},
    ]})
    assert r.status_code == 200, r.text
    m = client.get("/api/company/model").json()
    assert m["org"]["divisions"]["mw"]["depts"]["impl"]["members"]["model"] == "opus"
    assert m["org"]["roles"]["impl"]["can_edit"] == ["src/**"]
    r = client.patch("/api/company/process", json={"ops": [
        {"path": ["templates", "feature_dev", "nodes", "review", "on_fail"], "delete": True}]})
    assert r.status_code == 400 and r.json()["detail"]["issues"][0]["rule"] == "on_fail"
    assert "on_fail" in client.get("/api/company/model").json()["process"]["templates"]["feature_dev"]["nodes"]["review"]
    assert client.patch("/api/company/org", json={"ops": [{"path": ["roles", "impl", "allowed_tools", 99], "value": "x"}]}).status_code == 400


@pytest.fixture
def fake_tmux(monkeypatch):
    import subprocess as sp
    import tmuxctl
    live, sent = set(), []

    def tmux(*a):
        sent.append(a)
        if a[0] == "new-session":
            live.add(a[a.index("-s") + 1])
        return sp.CompletedProcess(a, 0, "", "")
    monkeypatch.setattr(tmuxctl, "tmux", tmux)
    monkeypatch.setattr(tmuxctl, "session_exists", lambda n: n in live)
    return sent


def test_init_example_and_empty(client, tmp_path, fake_tmux):
    assert client.post("/api/company/init", json={"template": "nope"}).status_code == 400
    assert client.post("/api/company/init", json={"template": "empty"}).status_code == 200
    assert client.get("/api/company").json()["complete"] is True
    assert (tokens.company_dir() / "prompts" / "common.md").exists()
    assert tokens.token_file("orchestrator").exists()
    assert client.post("/api/company/init", json={"template": "example"}).status_code == 409
    s = client.get("/api/company").json()
    assert s["orchestrator"] == {"alive": False, "last": None}


def test_init_example(client, fake_tmux):
    assert client.post("/api/company/init", json={"template": "example"}).status_code == 200
    assert "mw" in client.get("/api/company/model").json()["org"]["divisions"]


def test_layout_roundtrip(client):
    assert client.get("/api/company/layout").json() == {"templates": {}}
    r = client.put("/api/company/layout", json={"templates": {"feature_dev": {"design": [10.4, 20.6], "bad": [1]}}})
    assert r.status_code == 200
    assert client.get("/api/company/layout").json() == {"templates": {"feature_dev": {"design": [10, 21]}}}


def test_init_creates_ceo_session(client, fake_tmux):
    import json as _json
    import history
    import sessions_meta
    r = client.post("/api/company/init", json={"template": "example"}).json()
    assert r["ceo"]["name"] == "ceo" and r["ceo"]["created"] and r["ceo"]["started"]
    hq = history.DATA_DIR / "hq"
    md = (hq / "CLAUDE.md").read_text()
    assert "사장" in md and "orgctl" in md and "`mw`" in md
    settings = _json.loads((hq / ".claude" / "settings.json").read_text())
    assert "Bash(orgctl:*)" in settings["permissions"]["allow"] and settings["permissions"]["defaultMode"] == "dontAsk"
    token = settings["env"]["TMUX_WEB_TOKEN"]
    assert tokens.lookup(token)["role"] == "ceo"
    meta = sessions_meta.get("ceo")
    assert meta["builtin"] and meta["division"] == "*" and meta["dept"] == "hq"
    keys = [a for a in fake_tmux if a[0] == "send-keys"]
    assert keys and keys[0][-2].endswith("&& claude")
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/company/org", headers=h).status_code == 200
    assert client.post("/api/company/instances", json={"division": "mw", "feature": "f1"}, headers=h).status_code == 200
    assert client.post("/api/company/process/check", json={"text": "version: 2"}, headers=h).status_code == 400
    again = client.post("/api/company/ceo").json()
    assert again["created"] is False and not again["started"]

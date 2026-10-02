import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import control_api
import history
import push
import store
import tmuxctl
import tokens


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tokens, "login_check", lambda request: True)
    monkeypatch.setattr(push, "status", {
        "a": {"state": "working"}, "b": {"state": "idle"}, "c": {"state": "shell"}, "d": {"state": "waiting"}, "e": {"state": "running"},
    })
    sent = []

    def fake_tmux(*args):
        sent.append(args)
        return subprocess.CompletedProcess(args, 1 if args[-2] == "=d:" else 0, "", "")
    monkeypatch.setattr(tmuxctl, "tmux", fake_tmux)
    monkeypatch.setattr(control_api.time, "sleep", lambda s: sent.append(("sleep", s)))
    app = FastAPI()
    app.include_router(control_api.router)
    return TestClient(app, client=("127.0.0.1", 5000)), sent


def test_stop_and_resume(env):
    c, sent = env
    assert c.get("/api/control/status").json() == {"stopped": None}
    r = c.post("/api/control/stop_all").json()
    assert r["sessions"] == ["a", "b", "d"] and r["failed"] == ["d"]
    keys = [a for a in sent if a[0] == "send-keys"]
    assert len(keys) == 6 and all(a[-1] == "Escape" for a in keys)
    assert ("sleep", 0.3) in sent
    assert not any("=c:" in a or "=e:" in a for a in sent)
    assert control_api.flag_path().exists()
    assert c.get("/api/control/status").json()["stopped"]["by"] == "user"
    assert len(history.query(type="emergency_stop")) == 1
    assert c.post("/api/control/resume").json() == {"resumed": True}
    assert not control_api.flag_path().exists()
    assert c.post("/api/control/resume").json() == {"resumed": False}
    assert len(history.query(type="emergency_resume")) == 1


def test_hook_token_cannot_stop(env, monkeypatch):
    c, _ = env
    monkeypatch.setattr(tokens, "login_check", lambda request: False)
    hook = tokens.issue("hook")
    assert c.post("/api/control/stop_all", headers={"Authorization": f"Bearer {hook}"}).status_code == 403
    orch = tokens.issue("orchestrator")
    assert c.post("/api/control/stop_all", headers={"Authorization": f"Bearer {orch}"}).json()["by"] == "orchestrator"

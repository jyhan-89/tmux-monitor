import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import company_api
import directives
import directives_api
import history
import launcher
import sessions_meta
import store
import tmuxctl
import tokens

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "company" / "examples" / "mw-minimal"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")
    tokens.company_dir().mkdir(parents=True)
    for k in ("org", "process", "documents"):
        shutil.copy(SAMPLE / f"{k}.yaml", tokens.company_dir() / f"{k}.yaml")
    live = {"autosar": str(tmp_path), "bsp": str(tmp_path), "mw-impl-impl-proxy": str(tmp_path)}
    monkeypatch.setattr(tmuxctl, "list_sessions", lambda: [{"name": n, "path": p, "command": "claude", "pane_id": "%1"} for n, p in live.items()])
    monkeypatch.setattr(tmuxctl, "session_exists", lambda n: n in live)
    sent = []
    monkeypatch.setattr(tmuxctl, "tmux", lambda *a: sent.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(launcher, "screen", lambda name: "❯ \n ⏵⏵ don't ask on")
    app = FastAPI()
    app.include_router(company_api.router)
    app.include_router(directives_api.router)
    c = TestClient(app, client=("127.0.0.1", 5000))
    c.cookies.set("c", "ok")
    return c, live, sent


def assign(c, session, division="mw", dept="impl", role="impl", suffix="skeleton"):
    return c.post("/api/company/assign", json={"session": session, "division": division, "dept": dept, "role": role, "suffix": suffix})


def test_assign_and_launch_reuses(env):
    c, live, sent = env
    r = assign(c, "autosar")
    assert r.status_code == 200, r.text
    meta = sessions_meta.get("autosar")
    assert meta["assigned"] and meta["role"] == "impl" and meta["suffix"] == "skeleton" and meta["worktree"] == live["autosar"]
    assert oct(tokens.session_token_file("autosar").stat().st_mode & 0o777) == "0o600"
    out = launcher.launch("mw", "impl", "impl", "skeleton", "svc_a")
    assert out["name"] == "autosar" and out["created"] is False and out["assigned"]
    assert not any(a[0] == "new-session" for a in sent)
    assert history.query(type="session_assign")[0]["session"] == "autosar"


def test_assign_rules(env):
    c, live, _ = env
    assert assign(c, "nope").status_code == 400
    assert assign(c, "autosar", role="reviewer").status_code == 400
    assert assign(c, "autosar", division="bsp").status_code == 400
    sessions_meta.update("mw-impl-impl-proxy", division="mw", dept="impl", role="impl", worktree="/wt")
    assert "이미 역할 세션" in assign(c, "mw-impl-impl-proxy").json()["detail"]
    assert assign(c, "autosar").status_code == 200
    assert assign(c, "bsp").status_code == 200
    assert sessions_meta.get("autosar") is None and sessions_meta.assigned_to("mw", "impl", "impl", "skeleton") == "bsp"
    assert not tokens.session_token_file("autosar").exists()
    assert assign(c, "bsp", suffix="proxy").status_code == 200
    assert sessions_meta.assigned_to("mw", "impl", "impl", "skeleton") is None


def test_unassign_and_no_restart(env):
    c, live, sent = env
    assign(c, "autosar")
    out = launcher.restart("autosar")
    assert out["assigned"] and not any(a[0] == "kill-session" for a in sent)
    assert c.delete("/api/company/assign/autosar").status_code == 200
    assert sessions_meta.get("autosar") is None and not tokens.session_token_file("autosar").exists()
    assert c.delete("/api/company/assign/autosar").status_code == 404


def test_wake_text_and_directive_flow(env, monkeypatch):
    c, live, sent = env
    assign(c, "autosar")
    monkeypatch.setattr(launcher.push, "status", {"autosar": {"state": "shell"}})
    assert not launcher.wake("autosar") and not sent
    monkeypatch.setattr(launcher.push, "status", {"autosar": {"state": "idle"}})
    assert launcher.wake("autosar")
    typed = [a[-1] for a in sent if a[0] == "send-keys" and "-l" in a][0]
    assert "bin/directive list" in typed and "common.md" in typed
    orch = {"Authorization": f"Bearer {tokens.issue('orchestrator')}"}
    d = c.post("/api/directives", json={"type": "node", "to": "autosar", "body": "do"}, headers=orch).json()
    assert d["status"] == "delivered"
    tok = tokens.session_token_file("autosar").read_text().strip()
    r = c.post(f"/api/directives/{d['id']}/status", json={"status": "acked"}, headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["status"] == "acked"


def test_cli_reads_token_file(env, tmp_path):
    c, live, _ = env
    assign(c, "autosar")
    env_vars = {"PATH": os.environ["PATH"], "TMUX_WEB_SESSION": "autosar", "TMUX_WEB_DATA": str(history.DATA_DIR),
                "TMUX_WEB_URL": "http://127.0.0.1:9"}
    r = subprocess.run([str(ROOT / "bin" / "directive"), "list"], capture_output=True, text=True, env=env_vars)
    assert "연결할 수 없습니다" in r.stderr
    r = subprocess.run([str(ROOT / "bin" / "directive"), "list"], capture_output=True, text=True,
                       env={**env_vars, "TMUX_WEB_SESSION": "bsp"})
    assert "TMUX_WEB_TOKEN이 없습니다" in r.stderr


def test_shared_assignment_applies_to_every_division(env):
    c, live, _ = env
    assert assign(c, "bsp", division="*", dept="shared", role="analysis", suffix=None).status_code == 200
    assert sessions_meta.get("bsp")["division"] == "*"
    assert launcher.launch("mw", "shared", "analysis", None, "f")["name"] == "bsp"
    assert assign(c, "autosar", division="*", dept="shared", role="impl", suffix=None).status_code == 400

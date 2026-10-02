import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

import event_api
import history
import hooks_install
import push
import sessions_meta
import store
import tmuxctl
import tokens

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")
    monkeypatch.setattr(push, "status", {})
    monkeypatch.setattr(push, "hook_status", {})
    monkeypatch.setattr(push, "_pending", {})
    return tmp_path


def app():
    a = FastAPI()
    a.include_router(event_api.router)
    return a


def test_event_requires_hook_token(env):
    c = TestClient(app(), client=("127.0.0.1", 5000))
    body = {"session": "s", "event": "Stop", "data": {}}
    assert c.post("/api/event", json=body, cookies={"c": "ok"}).status_code == 401
    orch = tokens.issue("orchestrator")
    assert c.post("/api/event", json=body, headers={"Authorization": f"Bearer {orch}"}).status_code == 403
    hook = tokens.ensure_hook_token()
    assert tokens.ensure_hook_token() == hook
    assert oct(tokens.hook_token_file().stat().st_mode & 0o777) == "0o600"
    assert c.post("/api/event", json=body, headers={"Authorization": f"Bearer {hook}"}).json()["state"] == "idle"


def test_event_mapping_and_history(env):
    event_api.handle("s", "SessionStart", {"session_id": "abc"})
    event_api.handle("s", "UserPromptSubmit", {})
    event_api.handle("s", "PostToolUse", {"tool_name": "Read"})
    event_api.handle("s", "PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "git add -A && git commit -m x && git push origin feat/a"}})
    event_api.handle("s", "Notification", {"message": "Claude needs your permission to use Bash"})
    assert push.hook_status["s"]["state"] == "waiting"
    event_api.handle("s", "Notification", {"message": "Claude is waiting for your input"})
    assert push.hook_status["s"]["state"] == "idle"
    event_api.handle("s", "Stop", {})
    types = [e["type"] for e in history.query()]
    assert types.count("session_start") == 1
    assert "git_commit" in types and "git_push" in types
    changes = [(e["from"], e["to"]) for e in history.query(type="status_change")]
    assert changes == [(None, "idle"), ("idle", "working"), ("working", "waiting"), ("waiting", "idle"), ("idle", "idle")]
    assert all(e["source"] == "hook" for e in history.query(type="status_change"))


def test_event_updates_node_only_for_known_sessions(env):
    sessions_meta.update("mw-impl-impl-skeleton", role="impl")
    event_api.handle("mw-impl-impl-skeleton", "Stop", {"node": "implement"})
    event_api.handle("other", "Stop", {"node": "implement"})
    assert sessions_meta.get("mw-impl-impl-skeleton")["node"] == "implement"
    assert sessions_meta.get("other") is None


def fake_sessions(monkeypatch, screen_state):
    monkeypatch.setattr(tmuxctl, "list_sessions", lambda: [{"name": "s", "command": "claude", "pane_id": "%1"}])
    monkeypatch.setattr(tmuxctl, "capture", lambda pane: "")
    monkeypatch.setattr(tmuxctl, "analyze", lambda cmd, text: (screen_state[0], ["x"]))


def test_hook_wins_while_fresh(env, monkeypatch):
    screen = ["working"]
    fake_sessions(monkeypatch, screen)
    push.poll_once(now=1000)
    assert push.status["s"] == {"state": "working", "preview": ["x"], "source": "screen"}
    push.hook_status["s"] = {"state": "idle", "at": 1000, "event": "Stop"}
    notes = push.poll_once(now=1005)
    assert push.status["s"]["state"] == "idle" and push.status["s"]["source"] == "hook"
    assert notes and "작업 완료" in notes[0][0]
    push.poll_once(now=1031)
    assert push.status["s"]["source"] == "screen" and push.status["s"]["state"] == "idle"
    push.poll_once(now=1033)
    assert push.status["s"]["state"] == "working"
    assert history.query(type="status_change")[-1]["source"] == "screen"


def test_shell_ignores_stale_hook(env, monkeypatch):
    screen = ["shell"]
    fake_sessions(monkeypatch, screen)
    push.hook_status["s"] = {"state": "working", "at": 1000, "event": "PostToolUse"}
    push.poll_once(now=1001)
    assert push.status["s"]["state"] == "shell"


def test_install_merges_settings(env, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Read"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}]},
    }))
    hooks_install.install(proj)
    hooks_install.install(proj)
    s = json.loads((proj / ".claude" / "settings.json").read_text())
    assert s["permissions"] == {"allow": ["Read"]}
    stop_cmds = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_cmds == ["notify-send done", f"{hooks_install.SCRIPT} Stop"]
    assert set(s["hooks"]) == set(hooks_install.EVENTS)
    assert s["hooks"]["PostToolUse"][0]["matcher"] == "*"
    assert tokens.hook_token_file().exists()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_script_posts_event(env):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app(), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    try:
        hook = tokens.ensure_hook_token()
        envv = {"PATH": os.environ["PATH"], "HOME": str(env), "TMUX_WEB_URL": f"http://127.0.0.1:{port}",
                "TMUX_WEB_CONFIG": str(store.CONFIG_DIR), "TMUX_WEB_SESSION": 'mw-impl-impl-"x'}
        start = time.time()
        r = subprocess.run([str(ROOT / "hooks" / "claude-event.sh"), "Stop"], input='{"session_id":"abc","stop_hook_active":false}',
                           text=True, env=envv, timeout=5)
        assert r.returncode == 0 and time.time() - start < 1
        for _ in range(40):
            if push.hook_status.get('mw-impl-impl-"x'):
                break
            time.sleep(0.05)
        assert push.hook_status['mw-impl-impl-"x']["state"] == "idle"
        r = subprocess.run([str(ROOT / "hooks" / "claude-event.sh"), "Stop"], input="{}", text=True,
                           env={**envv, "TMUX_WEB_URL": "http://127.0.0.1:9"}, timeout=5)
        assert r.returncode == 0
        assert hook
    finally:
        server.should_exit = True
        t.join(timeout=5)


def test_ensure_ready_accepts_trust_once(monkeypatch):
    import launcher
    screens = iter(["", "Quick safety check\n❯ No, exit\n  Yes, I trust this folder", "Yes, I trust this folder",
                    "❯ \n  ⏵⏵ don't ask on (shift+tab to cycle)"])
    sent = []
    monkeypatch.setattr(launcher, "screen", lambda name: next(screens))
    monkeypatch.setattr(launcher.tmuxctl, "tmux", lambda *a: sent.append(a[-1]))
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(launcher.history, "record", lambda e: e)
    assert launcher.ensure_ready("s", timeout=5)
    assert sent == ["Down", "Enter"]

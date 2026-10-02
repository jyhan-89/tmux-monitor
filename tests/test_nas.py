import json
import subprocess

import pytest

import history
import store
import tokens
from ops import sync_nas


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    tokens.company_dir().mkdir(parents=True)
    (tokens.company_dir() / "org.yaml").write_text("version: 1\n")
    tokens.ensure_token("hook")
    history.record({"type": "x", "session": "s"})
    repo = history.DATA_DIR / "repos" / "mw"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    coord = history.DATA_DIR / "worktrees" / "mw" / "mw-quality-reviewer" / "coord"
    (coord / "review").mkdir(parents=True)
    (coord / "inbox").mkdir()
    (coord / "review" / "a.md").write_text("APPROVED\n")
    (coord / "inbox" / "d-1.md").write_text("secret task\n")
    return tmp_path


def test_skipped_without_root(env, monkeypatch):
    monkeypatch.delenv("TMUX_WEB_NAS_ROOT", raising=False)
    assert sync_nas.sync()["result"] == "skipped"
    monkeypatch.setenv("TMUX_WEB_NAS_ROOT", str(env / "missing"))
    assert sync_nas.sync()["result"] == "skipped"
    assert history.query(type="nas_sync")[-1]["result"] == "skipped"


def test_sync_copies_and_mirrors(env, monkeypatch):
    nas = env / "nas"
    nas.mkdir()
    monkeypatch.setenv("TMUX_WEB_NAS_ROOT", str(nas))
    out = sync_nas.sync()
    assert out["result"] == "ok", out
    assert list((nas / "history").rglob("*.jsonl"))
    assert (nas / "company" / "org.yaml").exists() and not (nas / "company" / "secrets").exists()
    assert (nas / "coord" / "mw" / "mw-quality-reviewer" / "review" / "a.md").exists()
    assert not (nas / "coord" / "mw" / "mw-quality-reviewer" / "inbox").exists()
    log = subprocess.run(["git", "--git-dir", str(nas / "git" / "mw.git"), "log", "--oneline"], capture_output=True, text=True).stdout
    assert "init" in log
    assert sync_nas.sync()["result"] == "ok"
    assert [e["result"] for e in history.query(type="nas_sync")] == ["ok", "ok"]

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import history
import launcher
import sessions_meta
import store
import tmuxctl
import tokens

SAMPLE = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    tokens.company_dir().mkdir(parents=True)
    for k in ("process", "documents"):
        shutil.copy(SAMPLE / f"{k}.yaml", tokens.company_dir() / f"{k}.yaml")
    org = yaml.safe_load((SAMPLE / "org.yaml").read_text())
    org["divisions"]["mw"]["folder"] = str(tmp_path / "work" / "mw")
    org["divisions"]["mw"]["depts"]["quality"]["folder"] = str(tmp_path / "elsewhere")
    (tokens.company_dir() / "org.yaml").write_text(yaml.safe_dump(org, allow_unicode=True))
    live = set()
    sent = []

    def fake_tmux(*a):
        sent.append(a)
        if a[0] == "new-session":
            live.add(a[a.index("-s") + 1])
        return subprocess.CompletedProcess(a, 0, "", "")
    monkeypatch.setattr(tmuxctl, "tmux", fake_tmux)
    monkeypatch.setattr(tmuxctl, "session_exists", lambda n: n in live)
    monkeypatch.setattr(launcher, "screen", lambda name: "❯ \n ⏵⏵ don't ask on")
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    return tmp_path, sent


def test_create_configure_start(env):
    tmp, sent = env
    out = launcher.create("mw", "impl", "impl", "skeleton")
    path = tmp / "work" / "mw" / "impl" / "mw-impl-impl-skeleton"
    assert out["created"] and Path(out["worktree"]) == path and path.is_dir()
    new = [a for a in sent if a[0] == "new-session"][0]
    assert new[new.index("-c") + 1] == str(path)
    assert not any(a[0] == "send-keys" for a in sent)
    assert not (path / "CLAUDE.md").exists()
    with pytest.raises(launcher.LaunchError):
        launcher.start("mw-impl-impl-skeleton")
    launcher.configure("mw-impl-impl-skeleton")
    assert "역할 `impl`" in (path / "CLAUDE.md").read_text()
    settings = json.loads((path / ".claude" / "settings.json").read_text())
    assert settings["permissions"]["defaultMode"] == "dontAsk" and settings["env"]["TMUX_WEB_SESSION"] == "mw-impl-impl-skeleton"
    assert tokens.lookup(settings["env"]["TMUX_WEB_TOKEN"])["session"] == "mw-impl-impl-skeleton"
    assert "Stop" in settings["hooks"] and (path / "coord" / "inbox").is_dir()
    assert sessions_meta.get("mw-impl-impl-skeleton")["configured"]
    out = launcher.start("mw-impl-impl-skeleton")
    keys = [a for a in sent if a[0] == "send-keys"][0]
    assert keys[-2].endswith("&& claude --model sonnet") and "tmux-web.env" in keys[-2] and out["ready"]
    env_file = path / ".claude" / "tmux-web.env"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600" and "export TMUX_WEB_SESSION=mw-impl-impl-skeleton" in env_file.read_text()


def test_dept_folder_and_launch_reuse(env):
    tmp, sent = env
    out = launcher.launch("mw", "quality", "reviewer")
    assert Path(out["worktree"]) == tmp / "elsewhere" / "mw-quality-reviewer"
    assert sessions_meta.get("mw-quality-reviewer")["configured"]
    n = len([a for a in sent if a[0] == "new-session"])
    assert launcher.launch("mw", "quality", "reviewer")["created"] is False
    assert len([a for a in sent if a[0] == "new-session"]) == n


def test_repo_worktree_inside_folder(env):
    tmp, sent = env
    origin = tmp / "origin.git"
    seed = tmp / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    subprocess.run(["git", "-C", str(seed), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    org = yaml.safe_load((tokens.company_dir() / "org.yaml").read_text())
    org["divisions"]["mw"]["repo"] = str(origin)
    (tokens.company_dir() / "org.yaml").write_text(yaml.safe_dump(org, allow_unicode=True))
    out = launcher.create("mw", "impl", "impl", "proxy", "svc")
    path = Path(out["worktree"])
    assert path == tmp / "work" / "mw" / "impl" / "mw-impl-impl-proxy"
    assert subprocess.run(["git", "-C", str(path), "branch", "--show-current"], capture_output=True, text=True).stdout.strip() == "feat/svc/proxy"
    launcher.configure("mw-impl-impl-proxy")
    assert subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_configure_rejects_assigned_or_unknown(env):
    with pytest.raises(launcher.LaunchError):
        launcher.configure("nope")
    sessions_meta.update("autosar", division="mw", dept="impl", role="impl", worktree="/x", assigned=True)
    with pytest.raises(launcher.LaunchError):
        launcher.configure("autosar")

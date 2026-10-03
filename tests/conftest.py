import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import history
import launcher
import store
import tmuxctl


def _no_real_tmux(*args):
    raise RuntimeError(f"테스트에서 실제 tmux를 부를 수 없습니다: tmux {' '.join(args)}")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "_cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "_data")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "_tmux"))
    monkeypatch.setattr(tmuxctl, "tmux", _no_real_tmux)
    monkeypatch.setattr(tmuxctl, "session_exists", lambda name: False)
    monkeypatch.setattr(tmuxctl, "list_sessions", lambda: [])
    monkeypatch.setattr(launcher, "spawn", lambda fn, *args: None)

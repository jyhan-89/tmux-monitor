import json
import threading
from datetime import timedelta

import pytest

import history


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DATA_DIR", tmp_path)


def test_record_and_query():
    ev = history.record({"type": "emergency_stop", "session": "*"})
    assert ev["ts"]
    files = list(history.root().rglob("*.jsonl"))
    assert len(files) == 1
    assert history.query(type="emergency_stop")[0]["session"] == "*"
    assert history.query(type="node_done") == []


def test_required_fields():
    with pytest.raises(ValueError):
        history.record({"type": "x"})


def test_masks_sensitive_keys():
    history.record({"type": "x", "session": "s", "data": {"Token": "abc", "nested": [{"api_key": "k", "ok": 1}]}, "password": "p"})
    line = json.loads(next(history.root().rglob("*.jsonl")).read_text())
    assert line["password"] == history.MASK
    assert line["data"]["Token"] == history.MASK
    assert line["data"]["nested"][0] == {"api_key": history.MASK, "ok": 1}


def test_concurrent_appends_keep_lines_whole():
    def work(i):
        for j in range(50):
            history.record({"type": "status_change", "session": f"s{i}", "n": j, "pad": "x" * 500})
    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = next(history.root().rglob("*.jsonl")).read_text().splitlines()
    assert len(lines) == 200
    assert all(json.loads(x)["type"] == "status_change" for x in lines)


def test_query_filters_since_and_session():
    old = history._now() - timedelta(days=2)
    history.record({"type": "a", "session": "s1", "ts": old.isoformat(timespec="seconds")})
    history.record({"type": "a", "session": "s2"})
    assert [e["session"] for e in history.query(type="a")] == ["s2"]
    assert [e["session"] for e in history.query(since=old - timedelta(minutes=1), session="s1")] == ["s1"]


def test_history_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import history_api
    import store
    import tokens
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(tokens, "login_check", lambda request: True)
    history.record({"type": "a", "session": "s1"})
    history.record({"type": "b", "session": "s2"})
    app = FastAPI()
    app.include_router(history_api.router)
    c = TestClient(app, client=("127.0.0.1", 5000))
    assert [e["session"] for e in c.get("/api/history", params={"session": "s2"}).json()] == ["s2"]
    assert len(c.get("/api/history", params={"since": "2000-01-01T00:00:00"}).json()) == 2
    assert c.get("/api/history", params={"since": "어제"}).status_code == 400

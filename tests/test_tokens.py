import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import store
import tokens


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(tokens, "login_check", lambda request: request.cookies.get("c") == "ok")


def app():
    a = FastAPI()

    @a.get("/x")
    def x(who: dict = Depends(tokens.require("company.read"))):
        return who

    @a.get("/event")
    def event(who: dict = Depends(tokens.require("event", allow_login=False))):
        return who
    return a


def client():
    return TestClient(app(), client=("127.0.0.1", 5000))


def test_issue_and_file_mode():
    t = tokens.issue("orchestrator")
    assert tokens.lookup(t)["role"] == "orchestrator"
    assert t not in tokens._file().read_text()
    assert oct(tokens._file().stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ValueError):
        tokens.issue("root")
    with pytest.raises(ValueError):
        tokens.issue("session")


def test_session_token_replaced_and_revoked():
    a = tokens.issue("session", "mw-impl-impl-1")
    b = tokens.issue("session", "mw-impl-impl-1")
    assert tokens.lookup(a) is None and tokens.lookup(b)["session"] == "mw-impl-impl-1"
    tokens.rename_session("mw-impl-impl-1", "mw-impl-impl-2")
    assert tokens.lookup(b)["session"] == "mw-impl-impl-2"
    tokens.revoke_session("mw-impl-impl-2")
    assert tokens.lookup(b) is None


def test_require_scopes():
    c = client()
    orch = tokens.issue("orchestrator")
    hook = tokens.issue("hook")
    assert c.get("/x").status_code == 401
    assert c.get("/x", cookies={"c": "ok"}).json()["role"] == "user"
    assert c.get("/x", headers={"Authorization": f"Bearer {orch}"}).json()["role"] == "orchestrator"
    assert c.get("/x", headers={"Authorization": f"Bearer {hook}"}).status_code == 403
    assert c.get("/x", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/event", cookies={"c": "ok"}).status_code == 401
    assert c.get("/event", headers={"Authorization": f"Bearer {hook}"}).status_code == 200


def test_token_rejected_through_proxy_or_remote():
    orch = tokens.issue("orchestrator")
    h = {"Authorization": f"Bearer {orch}"}
    assert client().get("/x", headers={**h, "X-Forwarded-For": "10.0.0.5"}).status_code == 403
    remote = TestClient(app(), client=("192.168.0.9", 5000))
    assert remote.get("/x", headers=h).status_code == 403

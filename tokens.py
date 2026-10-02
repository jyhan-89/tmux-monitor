import hashlib
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException, Request

import store

LOOPBACK = {"127.0.0.1", "::1"}
HEADER = "authorization"

SCOPES: dict[str, set[str]] = {
    "orchestrator": {"company.read", "control", "directives.manage", "sessions.meta", "history.read", "approvals.manage"},
    "hook": {"event"},
    "session": {"directives.self"},
}

login_check: Callable[[Request], bool] = lambda request: False


def company_dir() -> Path:
    return store.CONFIG_DIR / "company"


def secrets_dir() -> Path:
    return company_dir() / "secrets"


def _file() -> Path:
    return secrets_dir() / "tokens.json"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load() -> dict[str, dict]:
    try:
        return json.loads(_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, dict]) -> None:
    d = secrets_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    tmp = d / "tokens.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(_file())


def issue(role: str, session: str | None = None) -> str:
    if role not in SCOPES:
        raise ValueError(f"알 수 없는 토큰 역할: {role}")
    if role == "session" and not session:
        raise ValueError("session 토큰에는 세션 이름이 필요합니다")
    token = secrets.token_urlsafe(32)
    data = _load()
    if role == "session":
        data = {k: v for k, v in data.items() if v.get("session") != session}
    data[_digest(token)] = {"role": role, "session": session, "created": int(time.time())}
    _save(data)
    return token


def lookup(token: str | None) -> dict | None:
    if not token:
        return None
    return _load().get(_digest(token))


def revoke_session(session: str) -> None:
    data = _load()
    kept = {k: v for k, v in data.items() if v.get("session") != session}
    if len(kept) != len(data):
        _save(kept)


def rename_session(old: str, new: str) -> None:
    data = _load()
    changed = False
    for v in data.values():
        if v.get("session") == old:
            v["session"] = new
            changed = True
    if changed:
        _save(data)


def allowed(role: str, scope: str) -> bool:
    return scope in SCOPES.get(role, set())


def from_loopback(request: Request) -> bool:
    if not request.client or request.client.host not in LOOPBACK:
        return False
    return not (request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"))


def bearer(request: Request) -> str | None:
    value = request.headers.get(HEADER, "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None


def require(scope: str, allow_login: bool = True) -> Callable[[Request], dict]:
    def dependency(request: Request) -> dict:
        token = bearer(request)
        if token is None and allow_login and login_check(request):
            return {"role": "user", "session": None}
        if token is None:
            raise HTTPException(401, "로그인 또는 토큰이 필요합니다")
        if not from_loopback(request):
            raise HTTPException(403, "토큰은 이 PC 안에서만 쓸 수 있습니다")
        principal = lookup(token)
        if principal is None:
            raise HTTPException(401, "토큰이 올바르지 않습니다")
        if not allowed(principal["role"], scope):
            raise HTTPException(403, f"'{principal['role']}' 토큰으로는 이 API를 쓸 수 없습니다")
        return principal
    return dependency

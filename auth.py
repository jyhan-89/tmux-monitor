import getpass
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

AUTH_FILE = Path(os.environ.get("TMUX_WEB_AUTH", "~/.config/tmux-web/auth.json")).expanduser()
SESSION_TTL = 30 * 24 * 3600
MAX_FAILS = 5
FAIL_WINDOW = 300

SESSIONS_FILE = AUTH_FILE.with_name("sessions.json")
_sessions: dict[str, float] = {}
_loaded_mtime = 0.0
_fails: dict[str, list[float]] = {}


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_sessions() -> None:
    global _loaded_mtime
    try:
        mtime = SESSIONS_FILE.stat().st_mtime
        if mtime != _loaded_mtime:
            _sessions.clear()
            _sessions.update(json.loads(SESSIONS_FILE.read_text()))
            _loaded_mtime = mtime
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _save_sessions() -> None:
    global _loaded_mtime
    now = time.time()
    live = {k: v for k, v in _sessions.items() if v > now}
    _sessions.clear()
    _sessions.update(live)
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(SESSIONS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(live, f)
    _loaded_mtime = SESSIONS_FILE.stat().st_mtime


_load_sessions()


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def set_password(username: str, password: str) -> None:
    salt = secrets.token_bytes(16)
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"username": username, "salt": salt.hex(), "hash": _hash(password, salt).hex()}
    fd = os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    _sessions.clear()
    _save_sessions()


def is_configured() -> bool:
    return AUTH_FILE.exists()


def username() -> str | None:
    try:
        return json.loads(AUTH_FILE.read_text())["username"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def verify(username: str, password: str) -> bool:
    if not is_configured():
        return False
    data = json.loads(AUTH_FILE.read_text())
    expected = bytes.fromhex(data["hash"])
    actual = _hash(password, bytes.fromhex(data["salt"]))
    user_ok = secrets.compare_digest(username, data["username"])
    return secrets.compare_digest(actual, expected) and user_ok


def locked_out(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    _fails[ip] = recent
    return len(recent) >= MAX_FAILS


def record_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def create_session() -> str:
    _load_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[_key(token)] = time.time() + SESSION_TTL
    _save_sessions()
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    _load_sessions()
    expiry = _sessions.get(_key(token))
    return expiry is not None and expiry > time.time()


def drop_session(token: str | None) -> None:
    _load_sessions()
    if token and _sessions.pop(_key(token), None) is not None:
        _save_sessions()


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else getpass.getuser()
    if sys.stdin.isatty():
        pw = getpass.getpass(f"'{username}' 새 비밀번호: ")
        if pw != getpass.getpass("비밀번호 확인: "):
            sys.exit("비밀번호가 일치하지 않습니다")
    else:
        pw = sys.stdin.readline().rstrip("\n")
    if len(pw) < 8:
        sys.exit("비밀번호는 8자 이상이어야 합니다")
    set_password(username, pw)
    print(f"저장됨: {AUTH_FILE} (사용자: {username})")

import asyncio
import base64
import json
import logging
import os

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

import store
import tmuxctl

log = logging.getLogger("tmux-web")

POLL_INTERVAL = 2.0
VAPID_FILE = store.path("vapid.pem")
SUBS_FILE = "push_subs.json"
VAPID_SUB = os.environ.get("TMUX_WEB_VAPID_SUB", "https://github.com/jyhan-89/tmux-web-monitor")

status: dict[str, dict] = {}
_pending: dict[str, str] = {}


def _vapid() -> Vapid:
    if not VAPID_FILE.exists():
        store.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        v = Vapid()
        v.generate_keys()
        v.save_key(str(VAPID_FILE))
        os.chmod(VAPID_FILE, 0o600)
    return Vapid.from_file(str(VAPID_FILE))


def public_key() -> str:
    raw = _vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscriptions() -> list[dict]:
    return store.load(SUBS_FILE, [])


def subscribe(sub: dict) -> None:
    subs = [s for s in subscriptions() if s["endpoint"] != sub["endpoint"]]
    store.save(SUBS_FILE, subs + [sub])


def unsubscribe(endpoint: str) -> None:
    store.save(SUBS_FILE, [s for s in subscriptions() if s["endpoint"] != endpoint])


def send_all(title: str, body: str, session: str | None = None) -> int:
    payload = json.dumps({"title": title, "body": body, "session": session, "tag": session or "test"})
    subs, dead, sent = subscriptions(), [], 0
    for sub in subs:
        try:
            webpush(sub, payload, vapid_private_key=str(VAPID_FILE), vapid_claims={"sub": VAPID_SUB}, ttl=300)
            sent += 1
        except WebPushException as e:
            code = e.response.status_code if e.response is not None else None
            if code in (404, 410):
                dead.append(sub["endpoint"])
            else:
                log.warning("push 실패: %s", e)
    if dead:
        store.save(SUBS_FILE, [s for s in subs if s["endpoint"] not in dead])
    return sent


def _notify_change(name: str, old: str | None, new: str, preview: list[str]) -> tuple[str, str] | None:
    last = preview[-1] if preview else ""
    if new == "waiting" and old != "waiting":
        return f"⏳ {name}: 확인 필요", last
    if new == "idle" and old == "working":
        body = next((p for p in reversed(preview) if not p.startswith("✻")), last)
        return f"✅ {name}: 작업 완료", body
    return None


def poll_once() -> list[tuple[str, str, str]]:
    notes = []
    sessions = tmuxctl.list_sessions()
    for s in sessions:
        name = s["name"]
        state, preview = tmuxctl.analyze(s["command"], tmuxctl.capture(s["pane_id"]))
        prev = status.get(name)
        if prev is None:
            status[name] = {"state": state, "preview": preview}
            continue
        prev["preview"] = preview
        if state == prev["state"]:
            _pending.pop(name, None)
        elif _pending.get(name) == state:
            _pending.pop(name)
            note = _notify_change(name, prev["state"], state, preview)
            prev["state"] = state
            if note:
                notes.append((note[0], note[1], name))
        else:
            _pending[name] = state
    for gone in set(status) - {s["name"] for s in sessions}:
        status.pop(gone, None)
    return notes


async def monitor() -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            notes = await loop.run_in_executor(None, poll_once)
            for title, body, name in notes:
                if subscriptions():
                    await loop.run_in_executor(None, send_all, title, body, name)
        except Exception:
            log.exception("monitor 오류")
        await asyncio.sleep(POLL_INTERVAL)

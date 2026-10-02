import re
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import history
import push
import sessions_meta
import tokens

router = APIRouter(prefix="/api")

GIT = re.compile(r"\bgit\s+(commit|merge|tag|push)\b")
STATE_OF = {"SessionStart": "idle", "UserPromptSubmit": "working", "PreToolUse": "working",
            "PostToolUse": "working", "Stop": "idle", "SubagentStop": None}
RECORD_ALWAYS = {"SessionStart", "Stop", "Notification"}


def notification_state(data: dict) -> str:
    kind = str(data.get("notification_type") or "")
    message = str(data.get("message") or "").lower()
    if kind == "idle_prompt" or "waiting for your input" in message:
        return "idle"
    return "waiting"


def handle(session: str, event: str, data: dict) -> dict:
    state = notification_state(data) if event == "Notification" else STATE_OF.get(event)
    prev = push.hook_status.get(session, {}).get("state")
    if state:
        push.hook_status[session] = {"state": state, "at": time.time(), "event": event}
    recorded = []
    if event == "SessionStart":
        recorded.append(history.record({"type": "session_start", "session": session, "source": "hook",
                                        "claude_session": data.get("session_id")}))
    if state and (event in RECORD_ALWAYS or state != prev):
        recorded.append(history.record({"type": "status_change", "session": session, "from": prev, "to": state,
                                        "source": "hook", "event": event,
                                        "message": data.get("message") if event == "Notification" else None}))
    if event == "PostToolUse" and data.get("tool_name") == "Bash":
        command = str((data.get("tool_input") or {}).get("command") or "")
        for m in GIT.finditer(command):
            recorded.append(history.record({"type": f"git_{m.group(1)}", "session": session, "source": "hook",
                                            "command": command[:300]}))
    node = data.get("node")
    if isinstance(node, str) and node and sessions_meta.get(session) is not None:
        sessions_meta.update(session, node=node)
    return {"state": state, "recorded": len(recorded)}


class Event(BaseModel):
    session: str
    event: str
    data: dict = {}


@router.post("/event")
def api_event(body: Event, _: dict = Depends(tokens.require("event", allow_login=False))):
    return handle(body.session, body.event, body.data)

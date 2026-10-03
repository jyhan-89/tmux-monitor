import json
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import commands
import history
import launcher
import push
import tmuxctl
import tokens

router = APIRouter(prefix="/api/control")
CLAUDE_STATES = {"working", "waiting", "idle"}
ESC_GAP = 0.3


def flag_path():
    return tokens.company_dir() / "STOPPED"


def stopped() -> dict | None:
    try:
        return json.loads(flag_path().read_text() or "{}")
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {}


def claude_sessions() -> list[str]:
    return sorted(name for name, st in push.status.items() if st.get("state") in CLAUDE_STATES)


def send_escape(names: list[str]) -> list[str]:
    failed = set()
    for i in range(2):
        if i:
            time.sleep(ESC_GAP)
        for name in names:
            if tmuxctl.tmux("send-keys", "-t", f"={name}:", "Escape").returncode != 0:
                failed.add(name)
    return sorted(failed)


def stop_all(by: str) -> dict:
    targets = claude_sessions()
    failed = send_escape(targets)
    info = {"at": int(time.time()), "by": by, "sessions": targets}
    folder = tokens.company_dir()
    folder.mkdir(parents=True, exist_ok=True)
    flag_path().write_text(json.dumps(info, ensure_ascii=False))
    history.record({"type": "emergency_stop", "session": "*", "by": by, "targets": targets, "failed": failed})
    return {**info, "failed": failed}


def resume(by: str) -> bool:
    if stopped() is None:
        return False
    flag_path().unlink(missing_ok=True)
    history.record({"type": "emergency_resume", "session": "*", "by": by})
    return True


@router.get("/status")
def api_status(_: dict = Depends(tokens.require("control"))):
    return {"stopped": stopped()}


@router.post("/stop_all")
def api_stop_all(who: dict = Depends(tokens.require("control"))):
    return stop_all(who["role"])


@router.post("/resume")
def api_resume(who: dict = Depends(tokens.require("control"))):
    return {"resumed": resume(who["role"])}


class Wake(BaseModel):
    text: str = "inbox 확인"


@router.post("/wake/{session}")
def api_wake(session: str, body: Wake | None = None, _: dict = Depends(tokens.require("control"))):
    if stopped() is not None:
        return {"woken": False, "reason": "stopped"}
    return {"woken": launcher.wake(session, (body or Wake()).text)}


class Notice(BaseModel):
    title: str
    body: str = ""


@router.post("/notify")
def api_notify(body: Notice, _: dict = Depends(tokens.require("control"))):
    return {"sent": push.send_all(body.title, body.body)}


class CeoNotice(BaseModel):
    text: str


@router.post("/ceo")
def api_ceo(body: CeoNotice, _: dict = Depends(tokens.require("control"))):
    return {"woken": launcher.wake_ceo(body.text)}


@router.post("/restored")
def api_restored(_: dict = Depends(tokens.require("control"))):
    history.record({"type": "session_start", "session": "*", "source": "tmux-persist"})
    return commands.put("restored")

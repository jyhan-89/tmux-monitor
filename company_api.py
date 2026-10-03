import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import commands
import json
import history
import time
import yaml
import launcher
import models
import push
import sessions_meta
import tmuxctl
import tokens

log = logging.getLogger("tmux-web")
router = APIRouter(prefix="/api/company")
KINDS = tuple(models.PARSERS)


_org_cache: dict = {"mtime": None, "org": None}


def current_org() -> models.Org | None:
    p = kind_path("org")
    try:
        mtime = p.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    if _org_cache["mtime"] != mtime:
        try:
            _org_cache["org"] = models.parse_org(p.read_text())
        except models.DefinitionError:
            _org_cache["org"] = None
        _org_cache["mtime"] = mtime
    return _org_cache["org"]


def role_known(parsed: dict) -> bool:
    org = current_org()
    if not org or parsed["role"] not in org.roles:
        return False
    div = org.divisions.get(parsed["division"])
    if not div:
        return False
    if parsed["dept"] == "shared":
        return parsed["role"] in org.shared_roles()
    dept = div.depts.get(parsed["dept"])
    return bool(dept) and any(m.role == parsed["role"] for m in dept.all_members())


def kind_path(kind: str) -> Path:
    return tokens.company_dir() / f"{kind}.yaml"


def check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(404, f"정의 종류는 {', '.join(KINDS)} 중 하나입니다")


def read_texts() -> dict[str, str]:
    return {k: kind_path(k).read_text() for k in KINDS if kind_path(k).exists()}


def validate(texts: dict[str, str]) -> list[models.Issue]:
    if all(k in texts for k in KINDS):
        return models.parse_texts(texts).warnings
    issues, warnings = [], []
    for k, text in texts.items():
        try:
            warnings += getattr(models.PARSERS[k](text), "warnings", [])
        except models.DefinitionError as e:
            issues += e.issues
    if issues:
        raise models.DefinitionError(issues)
    return warnings


def git_commit(kind: str) -> None:
    folder = tokens.company_dir()
    try:
        if not (folder / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True, capture_output=True)
            (folder / ".gitignore").write_text("secrets/\n")
            subprocess.run(["git", "add", ".gitignore"], cwd=folder, check=True, capture_output=True)
        subprocess.run(["git", "add", f"{kind}.yaml"], cwd=folder, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"{kind}.yaml 수정"], cwd=folder, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("company git commit 실패: %s", getattr(e, "stderr", e))


EMPTY = {"org": "version: 1\nshared: {}\ndivisions: {}\nprofiles: {}\nroles: {}\n",
         "process": "version: 1\ntemplates: {}\n",
         "documents": "version: 1\ndocuments: {}\ndirectives:\n  node: {from: orchestrator, to: any}\n  merge: {from: orchestrator, to: any}\n  status: {from: any, to: any}\n"}
EXAMPLES = Path(__file__).resolve().parent / "company"


def copy_missing(src: Path, dst: Path) -> None:
    for f in src.rglob("*"):
        if f.is_file():
            target = dst / f.relative_to(src)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f.read_bytes())


class Init(BaseModel):
    template: str = "example"


@router.post("/init")
def init(body: Init, _: dict = Depends(tokens.require("company.write"))):
    if any(kind_path(k).exists() for k in KINDS):
        raise HTTPException(409, "이미 조직 정의가 있습니다")
    if body.template == "example":
        texts = {k: (EXAMPLES / "examples" / "mw-minimal" / f"{k}.yaml").read_text() for k in KINDS}
    elif body.template == "empty":
        texts = dict(EMPTY)
    else:
        raise HTTPException(400, "template은 example 또는 empty입니다")
    validate(texts)
    folder = tokens.company_dir()
    folder.mkdir(parents=True, exist_ok=True)
    copy_missing(EXAMPLES / "prompts", folder / "prompts")
    for k, text in texts.items():
        kind_path(k).write_text(text)
        git_commit(k)
    tokens.ensure_token("orchestrator")
    tokens.ensure_token("hook")
    return {"ok": True}


def orchestrator_alive() -> dict:
    p = history.DATA_DIR / "state" / "heartbeat"
    try:
        at = float(p.read_text())
    except (FileNotFoundError, ValueError):
        return {"alive": False, "last": None}
    return {"alive": time.time() - at < 60, "last": at}


@router.get("")
def summary(_: dict = Depends(tokens.require("company.read"))):
    texts = read_texts()
    try:
        issues = [i.as_dict() for i in validate(texts)]
    except models.DefinitionError as e:
        issues = [i.as_dict() for i in e.issues]
    return {"exists": {k: k in texts for k in KINDS}, "complete": len(texts) == len(KINDS), "issues": issues,
            "orchestrator": orchestrator_alive()}


@router.get("/divisions")
def divisions(_: dict = Depends(tokens.require("company.read"))):
    p = kind_path("org")
    if not p.exists():
        return []
    try:
        org = models.parse_org(p.read_text())
    except models.DefinitionError:
        return []
    return [{"id": d.id, "name": d.name} for d in org.divisions.values()]


@router.get("/sessions")
def role_sessions(_: dict = Depends(tokens.require("company.read"))):
    metas = sessions_meta.all_meta()
    out = []
    for s in tmuxctl.list_sessions():
        meta = metas.get(s["name"])
        if not meta:
            continue
        st = push.status.get(s["name"], {})
        out.append({"name": s["name"], "meta": meta, "state": st.get("state", ""), "source": st.get("source", "")})
    return out


class Launch(BaseModel):
    division: str
    dept: str
    role: str
    index: str | None = None
    feature: str = ""


@router.post("/sessions")
def launch_session(body: Launch, _: dict = Depends(tokens.require("sessions.launch"))):
    try:
        return launcher.launch(body.division, body.dept, body.role, body.index, body.feature)
    except (launcher.LaunchError, ValueError) as e:
        raise HTTPException(400, str(e))


class MetaUpdate(BaseModel):
    node: str | None = None


@router.patch("/sessions/{name}/meta")
def update_meta(name: str, body: MetaUpdate, _: dict = Depends(tokens.require("sessions.meta"))):
    if sessions_meta.get(name) is None:
        raise HTTPException(404, "역할 세션이 아닙니다")
    return sessions_meta.update(name, node=body.node)


class Assign(BaseModel):
    session: str
    division: str
    dept: str
    role: str
    suffix: str | None = None


@router.post("/assign")
def assign_session(body: Assign, _: dict = Depends(tokens.require("company.write"))):
    try:
        return launcher.assign(body.session, body.division, body.dept, body.role, body.suffix)
    except (launcher.LaunchError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.delete("/assign/{name}")
def unassign_session(name: str, _: dict = Depends(tokens.require("company.write"))):
    meta = launcher.unassign(name)
    if meta is None:
        raise HTTPException(404, "배정된 세션이 아닙니다")
    return {"ok": True}


class Slot(BaseModel):
    division: str
    dept: str
    role: str
    suffix: str | None = None


def launcher_call(fn, *args):
    try:
        return fn(*args)
    except (launcher.LaunchError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/sessions/create")
def create_session(body: Slot, _: dict = Depends(tokens.require("sessions.launch"))):
    return launcher_call(launcher.create, body.division, body.dept, body.role, body.suffix)


@router.post("/sessions/{name}/configure")
def configure_session(name: str, _: dict = Depends(tokens.require("sessions.launch"))):
    return launcher_call(launcher.configure, name)


@router.post("/sessions/{name}/start")
def start_session(name: str, _: dict = Depends(tokens.require("sessions.launch"))):
    return launcher_call(launcher.start, name)


@router.post("/sessions/{name}/restart")
def restart_session(name: str, _: dict = Depends(tokens.require("sessions.launch"))):
    try:
        return launcher.restart(name)
    except (launcher.LaunchError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.get("/instances")
def list_instances(_: dict = Depends(tokens.require("company.read"))):
    return commands.instances()


class StartInstance(BaseModel):
    division: str
    feature: str
    brief: str = ""


@router.post("/instances")
def start_instance(body: StartInstance, _: dict = Depends(tokens.require("company.write"))):
    if not models.IDENT.match(body.feature):
        raise HTTPException(400, "기능 이름은 영소문자·숫자·밑줄로 입력하세요")
    return commands.put("start", division=body.division, feature=body.feature, brief=body.brief)


class Transition(BaseModel):
    to: str
    reason: str = ""


@router.post("/instances/{division}/{feature}/transition")
def transition(division: str, feature: str, body: Transition, _: dict = Depends(tokens.require("company.write"))):
    return commands.put("transition", division=division, feature=feature, to=body.to, reason=body.reason)


@router.get("/model")
def model(_: dict = Depends(tokens.require("company.read"))):
    out = {}
    for k in KINDS:
        p = kind_path(k)
        try:
            out[k] = yaml.safe_load(p.read_text()) if p.exists() else None
        except yaml.YAMLError:
            out[k] = None
    return out


def layout_path() -> Path:
    return tokens.company_dir() / "layout.json"


@router.get("/layout")
def get_layout(_: dict = Depends(tokens.require("company.read"))):
    try:
        return json.loads(layout_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"templates": {}}


class Layout(BaseModel):
    templates: dict[str, dict[str, list[float]]] = {}


@router.put("/layout")
def put_layout(body: Layout, _: dict = Depends(tokens.require("company.write"))):
    clean = {t: {k: [round(float(v[0])), round(float(v[1]))] for k, v in nodes.items() if len(v) == 2}
             for t, nodes in body.templates.items()}
    folder = tokens.company_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = layout_path().with_suffix(".tmp")
    tmp.write_text(json.dumps({"templates": clean}, ensure_ascii=False, indent=1))
    tmp.replace(layout_path())
    return {"ok": True}


@router.get("/{kind}")
def get_kind(kind: str, _: dict = Depends(tokens.require("company.read"))):
    check_kind(kind)
    p = kind_path(kind)
    return {"kind": kind, "exists": p.exists(), "text": p.read_text() if p.exists() else ""}


class Definition(BaseModel):
    text: str


class Op(BaseModel):
    path: list[str | int]
    value: object = None
    delete: bool = False


class Patch(BaseModel):
    ops: list[Op]


def apply_op(data: dict, op: Op) -> None:
    if not op.path:
        raise HTTPException(400, "path가 비어 있습니다")
    cur = data
    for key in op.path[:-1]:
        if isinstance(cur, dict):
            cur = cur.setdefault(key, {})
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            raise HTTPException(400, f"경로를 찾을 수 없습니다: {op.path}")
    last = op.path[-1]
    if not isinstance(cur, (dict, list)):
        raise HTTPException(400, f"경로를 찾을 수 없습니다: {op.path}")
    if op.delete:
        if isinstance(cur, dict):
            cur.pop(last, None)
        elif isinstance(last, int) and 0 <= last < len(cur):
            cur.pop(last)
    elif isinstance(cur, dict):
        cur[last] = op.value
    elif isinstance(last, int) and 0 <= last < len(cur):
        cur[last] = op.value
    else:
        raise HTTPException(400, f"경로를 찾을 수 없습니다: {op.path}")


@router.patch("/{kind}")
def patch_kind(kind: str, body: Patch, who: dict = Depends(tokens.require("company.write"))):
    check_kind(kind)
    p = kind_path(kind)
    if not p.exists():
        raise HTTPException(404, f"{kind}.yaml이 없습니다")
    data = yaml.safe_load(p.read_text()) or {}
    for op in body.ops:
        apply_op(data, op)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=None, width=120)
    return put_kind(kind, Definition(text=text), who)


@router.put("/{kind}")
def put_kind(kind: str, body: Definition, _: dict = Depends(tokens.require("company.write"))):
    check_kind(kind)
    texts = {**read_texts(), kind: body.text}
    try:
        warnings = validate(texts)
    except models.DefinitionError as e:
        raise HTTPException(400, {"message": "정의 검증에 실패했습니다", "issues": [i.as_dict() for i in e.issues]})
    folder = tokens.company_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = kind_path(kind).with_suffix(".yaml.tmp")
    tmp.write_text(body.text)
    os.replace(tmp, kind_path(kind))
    git_commit(kind)
    return {"ok": True, "warnings": [w.as_dict() for w in warnings]}

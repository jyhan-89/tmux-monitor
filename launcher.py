import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import directives
import history
import hooks_install
import models
import push
import sessions_meta
import tmuxctl
import tokens

ROOT = Path(__file__).resolve().parent
BIN = ROOT / "bin"
WIDE_TOOLS = {"Bash", "*", "Edit", "Write"}


class LaunchError(Exception):
    pass


@dataclass
class Placement:
    division: models.Division
    dept: str
    member: models.Member
    role: models.Role


def server_url() -> str:
    port = os.environ.get("PORT", "8765")
    base = os.environ.get("BASE_PATH", "/dev").rstrip("/")
    return os.environ.get("TMUX_WEB_URL", f"http://127.0.0.1:{port}{base}")


def claude_command() -> str:
    return os.environ.get("TMUX_WEB_CLAUDE_CMD", "claude")


def load_company() -> models.Company:
    try:
        return models.load_dir(tokens.company_dir())
    except FileNotFoundError:
        raise LaunchError("조직 정의(org/process/documents.yaml)가 없습니다")


def place(company: models.Company, division: str, dept: str, role: str) -> Placement:
    div = company.org.divisions.get(division)
    if not div:
        raise LaunchError(f"본부 '{division}'이(가) 없습니다")
    d = div.depts.get(dept)
    member = next((m for m in d.all_members() if m.role == role), None) if d else None
    if member is None:
        member = next((m for m in company.org.shared.values() if m.role == role), None)
    if member is None:
        raise LaunchError(f"'{division}/{dept}'에 역할 '{role}'이(가) 없습니다")
    return Placement(div, dept, member, company.org.roles[role])


def prompt_file(rel: str) -> Path | None:
    for base in (tokens.company_dir(), ROOT / "company"):
        p = base / rel
        if rel and p.exists():
            return p
    return None


def edit_rules(globs: list[str]) -> list[str]:
    out = []
    for g in globs:
        path = g if g.startswith("/") else f"/{g}"
        out.append(f"Edit({path})")
    return out


def permissions(company: models.Company, role: models.Role) -> dict:
    wide = [t for t in role.allowed_tools if t in WIDE_TOOLS - {"Edit", "Write"}]
    if wide:
        raise LaunchError(f"역할 '{role.id}'의 allowed_tools가 너무 넓습니다: {wide}")
    tools = [t for t in role.allowed_tools if t not in ("Edit", "Write")]
    if "Bash(directive:*)" in tools:
        tools.append(f"Bash({BIN / 'directive'}:*)")
    can_edit = role.can_edit if {"Edit", "Write"} & set(role.allowed_tools) else []
    others = [d.pattern for d in company.documents.documents if d.owner != role.id]
    deny = edit_rules(role.cannot_edit) + edit_rules([p for p in others if p not in can_edit])
    for private in (history.DATA_DIR / "directives", history.DATA_DIR / "history", tokens.secrets_dir()):
        deny.append(f"Read(/{private.resolve().as_posix()}/**)")
    return {"defaultMode": "dontAsk", "allow": tools + edit_rules(can_edit), "deny": list(dict.fromkeys(deny))}


def claude_md(company: models.Company, p: Placement) -> str:
    parts = []
    for rel in ("prompts/common.md", p.role.prompt, p.division.depts.get(p.dept, models.Dept()).rules):
        f = prompt_file(rel) if rel else None
        if f:
            parts.append(f.read_text().strip())
    profile = company.org.profiles.get(p.division.profile)
    if profile:
        parts.append(f"# 본부 프로파일: {profile.id}\n\n적용 표준: {', '.join(profile.standards) or '없음'}")
    owned = [d.pattern for d in company.documents.documents if d.owner == p.role.id]
    parts.append("# 이 세션의 범위\n\n"
                 f"- 세션: 본부 `{p.division.id}`, 부서 `{p.dept}`, 역할 `{p.role.id}`\n"
                 f"- 수정 가능: {', '.join(f'`{x}`' for x in p.role.can_edit) or '없음'}\n"
                 f"- 수정 금지: {', '.join(f'`{x}`' for x in p.role.cannot_edit) or '없음'}\n"
                 f"- 소유 문서: {', '.join(f'`{x}`' for x in owned) or '없음'}\n"
                 f"- 지시서 도구: `directive` (list, show, ack, start, done, block, reject, send). 경로: `{BIN / 'directive'}`")
    return "\n\n".join(parts) + "\n"


def run_git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise LaunchError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r.stdout.strip()


def repo_dir(div: models.Division) -> Path:
    local = Path(div.repo).expanduser()
    if div.repo and local.is_dir() and (local / ".git").exists():
        return local
    if not div.repo:
        raise LaunchError(f"본부 '{div.id}'에 repo가 없습니다")
    clone = history.DATA_DIR / "repos" / div.id
    if not (clone / ".git").exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        run_git("clone", div.repo, str(clone), cwd=clone.parent)
    return clone


def slot_base(div: models.Division, dept: str) -> Path:
    d = div.depts.get(dept)
    root = Path(div.folder).expanduser() if div.folder else history.DATA_DIR / "worktrees" / div.id
    if d and d.folder:
        p = Path(d.folder).expanduser()
        return p if p.is_absolute() else root / p
    return root / dept if div.folder else root


def session_folder(div: models.Division, dept: str, name: str, branch: str, base: str) -> Path:
    path = slot_base(div, dept) / name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not div.repo:
        path.mkdir(parents=True)
        return path
    repo = repo_dir(div)
    exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo).returncode == 0
    if exists:
        run_git("worktree", "add", str(path), branch, cwd=repo)
    else:
        run_git("worktree", "add", "-b", branch, str(path), base, cwd=repo)
    return path


def write_settings(path: Path, perms: dict, env: dict | None = None) -> None:
    f = path / ".claude" / "settings.json"
    try:
        settings = json.loads(f.read_text())
    except FileNotFoundError:
        settings = {}
    settings["permissions"] = perms
    if env:
        settings["env"] = {**settings.get("env", {}), **env}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    hooks_install.install(path)


def assign(name: str, division: str, dept: str, role: str, suffix: str | None = None) -> dict:
    company = load_company()
    if dept == "shared":
        if role not in company.org.shared_roles():
            raise LaunchError(f"공통 역할 '{role}'이(가) 없습니다")
        division, suffix = "*", None
    else:
        place(company, division, dept, role)
    sessions = {s["name"]: s for s in tmuxctl.list_sessions()}
    if name not in sessions:
        raise LaunchError(f"세션이 없습니다: {name}")
    current = sessions_meta.get(name)
    if current and not current.get("assigned"):
        raise LaunchError(f"이미 역할 세션입니다: {name}")
    prev = sessions_meta.assigned_to(division, dept, role, suffix)
    if prev and prev != name:
        unassign(prev)
    if current:
        sessions_meta.unassign(name)
    meta = sessions_meta.update(name, division=division, dept=dept, role=role, suffix=suffix or None,
                                worktree=sessions[name]["path"], assigned=True, grouped=True)
    tokens.write_session_token(name)
    history.record({"type": "session_assign", "session": name, "division": division, "dept": dept, "role": role,
                    "suffix": suffix})
    directives.deliver_pending(name)
    return {"name": name, **meta}


def unassign(name: str) -> dict | None:
    meta = sessions_meta.unassign(name)
    if meta:
        tokens.drop_session_token(name)
        history.record({"type": "session_unassign", "session": name, "division": meta.get("division"),
                        "dept": meta.get("dept"), "role": meta.get("role")})
    return meta


def create(division: str, dept: str, role: str, suffix: str | None = None, feature: str = "", base: str = "main") -> dict:
    company = load_company()
    p = place(company, division, dept, role)
    name = tmuxctl.role_session_name(division, dept, role, suffix)
    if tmuxctl.session_exists(name):
        return {"name": name, "created": False, **(sessions_meta.get(name) or {})}
    branch = f"feat/{feature or 'work'}/{suffix or role}"
    path = session_folder(p.division, dept, name, branch, base)
    r = tmuxctl.tmux("new-session", "-d", "-s", name, "-c", str(path))
    if r.returncode != 0:
        raise LaunchError(f"tmux 세션 생성 실패: {r.stderr.strip()}")
    meta = sessions_meta.update(name, division=division, dept=dept, role=role, suffix=suffix or None,
                                branch=branch if p.division.repo else None, worktree=str(path), grouped=True)
    history.record({"type": "session_start", "session": name, "source": "launcher", "folder": str(path)})
    return {"name": name, "created": True, **meta}


def configure(name: str) -> dict:
    meta = sessions_meta.get(name)
    if not meta or meta.get("assigned") or not meta.get("worktree"):
        raise LaunchError(f"조직에서 만든 세션이 아닙니다: {name}")
    company = load_company()
    p = place(company, meta["division"], meta["dept"], meta["role"])
    path = Path(meta["worktree"])
    if not path.is_dir():
        raise LaunchError(f"세션 폴더가 없습니다: {path}")
    perms = permissions(company, p.role)
    token = tokens.write_session_token(name)
    env = {"TMUX_WEB_SESSION": name, "TMUX_WEB_TOKEN": token, "TMUX_WEB_URL": server_url(),
           "PATH": f"{BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    write_settings(path, perms, env)
    md = claude_md(company, p)
    (path / "CLAUDE.md").write_text(md)
    (path / "coord" / "inbox").mkdir(parents=True, exist_ok=True)
    if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=path, capture_output=True).returncode == 0:
        exclude = Path(run_git("rev-parse", "--git-path", "info/exclude", cwd=path))
        exclude = exclude if exclude.is_absolute() else path / exclude
        lines = exclude.read_text().splitlines() if exclude.exists() else []
        for pat in ("coord/inbox/", ".claude/", "CLAUDE.md"):
            if pat not in lines:
                lines.append(pat)
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(lines) + "\n")
    for k, v in env.items():
        tmuxctl.tmux("set-environment", "-t", f"={name}", k, v)
    env_file = path / ".claude" / "tmux-web.env"
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items()))
    meta = sessions_meta.update(name, configured=True)
    history.record({"type": "session_configure", "session": name, "source": "launcher",
                    "claude_md_sha256": hashlib.sha256(md.encode()).hexdigest()[:16]})
    directives.deliver_pending(name)
    return {"name": name, **meta, "permissions": perms}


def start(name: str) -> dict:
    meta = sessions_meta.get(name)
    if not meta or not meta.get("configured"):
        raise LaunchError("먼저 설정을 적용하세요 (CLAUDE.md·권한)")
    company = load_company()
    p = place(company, meta["division"], meta["dept"], meta["role"])
    cmd = claude_command()
    if p.member.model and cmd == "claude":
        cmd += f" --model {shlex.quote(p.member.model)}"
    env_file = Path(meta["worktree"]) / ".claude" / "tmux-web.env"
    line = f". {shlex.quote(str(env_file))} && {cmd}" if env_file.exists() else cmd
    tmuxctl.tmux("send-keys", "-t", f"={name}:", line, "Enter")
    ready = ensure_ready(name) if cmd.split()[0] == "claude" else True
    history.record({"type": "status_change", "session": name, "to": "started", "source": "launcher", "ready": ready})
    return {"name": name, "ready": ready, **meta}


def launch(division: str, dept: str, role: str, suffix: str | None = None, feature: str = "", base: str = "main") -> dict:
    company = load_company()
    place(company, division, dept, role)
    assigned = sessions_meta.assigned_to(division, dept, role, suffix)
    if assigned and tmuxctl.session_exists(assigned):
        return {"name": assigned, "created": False, "assigned": True, **(sessions_meta.get(assigned) or {})}
    name = tmuxctl.role_session_name(division, dept, role, suffix)
    if tmuxctl.session_exists(name) and (sessions_meta.get(name) or {}).get("configured"):
        return {"name": name, "created": False, **(sessions_meta.get(name) or {})}
    created = create(division, dept, role, suffix, feature, base)
    configure(name)
    started = start(name)
    return {**started, "created": created["created"]}


TRUST_PROMPT = re.compile(r"trust this folder|Do you trust the files")
READY = re.compile(r"\? for shortcuts|shift\+tab to cycle|don't ask on|bypass permissions on|accept edits on")


def screen(name: str) -> str:
    return tmuxctl.capture(f"={name}:")


def ensure_ready(name: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    trusted = False
    while time.time() < deadline:
        text = screen(name)
        if TRUST_PROMPT.search(text):
            if not trusted:
                tmuxctl.tmux("send-keys", "-t", f"={name}:", "Down")
                time.sleep(0.3)
                tmuxctl.tmux("send-keys", "-t", f"={name}:", "Enter")
                trusted = True
                history.record({"type": "status_change", "session": name, "to": "trusted", "source": "launcher"})
        elif READY.search(text):
            return True
        time.sleep(0.5)
    return False


def assigned_wake_text(text: str) -> str:
    common = prompt_file("prompts/common.md")
    rule = f" 절차는 {common}를 따른다." if common else ""
    return (f"{text}: 이 세션은 조직 역할에 배정되어 있다. `{BIN / 'directive'} list`로 지시서를 확인하고,"
            f" `{BIN / 'directive'} ack/start/done <id> --ref <브랜치@커밋>`으로 처리한다.{rule}")


def wake(name: str, text: str = "inbox 확인") -> bool:
    if not tmuxctl.session_exists(name):
        return False
    if (sessions_meta.get(name) or {}).get("assigned"):
        state = push.status.get(name, {}).get("state")
        if state not in ("idle", "working", "waiting"):
            history.record({"type": "status_change", "session": name, "to": state or "unknown", "source": "launcher",
                            "reason": "wake_skipped_not_claude"})
            return False
        text = assigned_wake_text(text)
    if TRUST_PROMPT.search(screen(name)) and not ensure_ready(name, 15):
        return False
    return tmuxctl.tmux("send-keys", "-t", f"={name}:", "-l", text).returncode == 0 and \
        tmuxctl.tmux("send-keys", "-t", f"={name}:", "Enter").returncode == 0


def restart(name: str) -> dict:
    meta = sessions_meta.get(name)
    if meta and meta.get("assigned"):
        history.record({"type": "session_stop", "session": name, "source": "launcher", "reason": "restart_skipped_assigned"})
        return {"name": name, "created": False, "assigned": True, **meta}
    parsed = tmuxctl.parse_role_session(name)
    if not meta or not parsed:
        raise LaunchError(f"역할 세션이 아닙니다: {name}")
    branch = meta.get("branch", "")
    feature = branch.split("/")[1] if branch.startswith("feat/") and branch.count("/") >= 2 else ""
    tmuxctl.tmux("kill-session", "-t", f"={name}")
    tokens.revoke_session(name)
    history.record({"type": "session_stop", "session": name, "source": "launcher", "reason": "restart"})
    return launch(parsed["division"], parsed["dept"], parsed["role"], parsed["suffix"], feature)

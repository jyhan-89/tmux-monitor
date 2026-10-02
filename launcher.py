import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import directives
import history
import hooks_install
import models
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
        out += [f"Edit({path})", f"Write({path})"]
    return out


def permissions(company: models.Company, role: models.Role) -> dict:
    wide = [t for t in role.allowed_tools if t in WIDE_TOOLS - {"Edit", "Write"}]
    if wide:
        raise LaunchError(f"역할 '{role.id}'의 allowed_tools가 너무 넓습니다: {wide}")
    tools = [t for t in role.allowed_tools if t not in ("Edit", "Write")]
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
                 "- 지시서 도구: `directive` (list, show, ack, start, done, block, reject, send)")
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


def worktree(div: models.Division, name: str, branch: str, base: str) -> Path:
    repo = repo_dir(div)
    path = history.DATA_DIR / "worktrees" / div.id / name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo).returncode == 0
    if exists:
        run_git("worktree", "add", str(path), branch, cwd=repo)
    else:
        run_git("worktree", "add", "-b", branch, str(path), base, cwd=repo)
    return path


def write_settings(path: Path, perms: dict) -> None:
    f = path / ".claude" / "settings.json"
    try:
        settings = json.loads(f.read_text())
    except FileNotFoundError:
        settings = {}
    settings["permissions"] = perms
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    hooks_install.install(path)


def launch(division: str, dept: str, role: str, suffix: str | None = None, feature: str = "", base: str = "main") -> dict:
    company = load_company()
    p = place(company, division, dept, role)
    name = tmuxctl.role_session_name(division, dept, role, suffix)
    if tmuxctl.session_exists(name):
        return {"name": name, "created": False, **(sessions_meta.get(name) or {})}
    perms = permissions(company, p.role)
    branch = f"feat/{feature or 'work'}/{suffix or role}"
    path = worktree(p.division, name, branch, base)
    write_settings(path, perms)
    md = claude_md(company, p)
    (path / "CLAUDE.md").write_text(md)
    (path / "coord" / "inbox").mkdir(parents=True, exist_ok=True)
    exclude = Path(run_git("rev-parse", "--git-path", "info/exclude", cwd=path))
    exclude = exclude if exclude.is_absolute() else path / exclude
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    for pat in ("coord/inbox/", ".claude/settings.json", "CLAUDE.md"):
        if pat not in lines:
            lines.append(pat)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(lines) + "\n")
    token = tokens.issue("session", name)
    env = {"TMUX_WEB_SESSION": name, "TMUX_WEB_TOKEN": token, "TMUX_WEB_URL": server_url(),
           "PATH": f"{BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    args = ["new-session", "-d", "-s", name, "-c", str(path)]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    r = tmuxctl.tmux(*args)
    if r.returncode != 0:
        tokens.revoke_session(name)
        raise LaunchError(f"tmux 세션 생성 실패: {r.stderr.strip()}")
    cmd = claude_command()
    if p.member.model and cmd == "claude":
        cmd += f" --model {shlex.quote(p.member.model)}"
    tmuxctl.tmux("send-keys", "-t", f"={name}:", cmd, "Enter")
    meta = sessions_meta.update(name, division=division, dept=dept, role=role, branch=branch, worktree=str(path))
    sessions_meta.adopt([name])
    history.record({"type": "session_start", "session": name, "source": "launcher", "branch": branch,
                    "claude_md_sha256": hashlib.sha256(md.encode()).hexdigest()[:16]})
    directives.deliver_pending(name)
    return {"name": name, "created": True, **meta, "permissions": perms}


def wake(name: str, text: str = "inbox 확인") -> bool:
    if not tmuxctl.session_exists(name):
        return False
    return tmuxctl.tmux("send-keys", "-t", f"={name}:", "-l", text).returncode == 0 and \
        tmuxctl.tmux("send-keys", "-t", f"={name}:", "Enter").returncode == 0

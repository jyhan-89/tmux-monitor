import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import history
import tokens


def nas_root() -> Path | None:
    value = os.environ.get("TMUX_WEB_NAS_ROOT", "").strip()
    return Path(value).expanduser() if value else None


def rsync(src: Path, dst: Path, *extra: str) -> tuple[bool, str]:
    dst.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["rsync", "-a", *extra, f"{src}/", f"{dst}/"], capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()[-300:]


def mirror(repo: Path, dst: Path) -> tuple[bool, str]:
    if not (dst / "HEAD").exists():
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(dst)], check=True)
    r = subprocess.run(["git", "push", "-q", "--mirror", str(dst)], cwd=repo, capture_output=True, text=True)
    head = subprocess.run(["git", "symbolic-ref", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    if r.returncode == 0 and head:
        subprocess.run(["git", "--git-dir", str(dst), "symbolic-ref", "HEAD", head], capture_output=True)
    return r.returncode == 0, r.stderr.strip()[-300:]


def notify(title: str, body: str) -> None:
    token_file = tokens.token_file("orchestrator")
    if not token_file.exists():
        return
    port = os.environ.get("PORT", "8765")
    url = os.environ.get("TMUX_WEB_URL", f"http://127.0.0.1:{port}/dev").rstrip("/") + "/api/control/notify"
    req = urllib.request.Request(url, data=json.dumps({"title": title, "body": body}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token_file.read_text().strip()}",
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).close()
    except OSError:
        pass


def sync() -> dict:
    root = nas_root()
    if root is None:
        return {"result": "skipped", "reason": "TMUX_WEB_NAS_ROOT 미설정"}
    if not root.is_dir() or not os.access(root, os.W_OK):
        result = {"result": "skipped", "reason": f"NAS 경로가 없거나 쓸 수 없습니다: {root}"}
        history.record({"type": "nas_sync", "session": "-", **result})
        return result
    started = time.time()
    errors = []
    jobs = []
    if history.root().exists():
        jobs.append(("history", history.root(), root / "history", ()))
    if tokens.company_dir().exists():
        jobs.append(("company", tokens.company_dir(), root / "company", ("--exclude", "secrets/")))
    for coord in sorted((history.DATA_DIR / "worktrees").glob("*/*/coord")):
        div, name = coord.parent.parent.name, coord.parent.name
        jobs.append((f"coord:{name}", coord, root / "coord" / div / name, ("--exclude", "inbox/")))
    for label, src, dst, extra in jobs:
        ok, err = rsync(src, dst, *extra)
        if not ok:
            errors.append(f"{label}: {err}")
    repos = sorted((history.DATA_DIR / "repos").glob("*/.git"))
    for git_dir in repos:
        ok, err = mirror(git_dir.parent, root / "git" / f"{git_dir.parent.name}.git")
        if not ok:
            errors.append(f"git:{git_dir.parent.name}: {err}")
    result = {"result": "fail" if errors else "ok", "jobs": len(jobs), "repos": len(repos),
              "seconds": round(time.time() - started, 1), "errors": errors}
    history.record({"type": "nas_sync", "session": "-", **result})
    if errors:
        notify("⚠️ NAS 동기화 실패", "; ".join(errors)[:200])
    return result


if __name__ == "__main__":
    out = sync()
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if out["result"] == "fail" else 0)

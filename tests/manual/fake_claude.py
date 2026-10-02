import json
import time
import os
import subprocess
import sys
from pathlib import Path

DIRECTIVE = Path(__file__).resolve().parents[2] / "bin" / "directive"
SESSION = os.environ.get("TMUX_WEB_SESSION", "")
ROLE = SESSION.split("-")[2] if SESSION.count("-") >= 2 else ""


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def directive(*args: str) -> str:
    out = sh(str(DIRECTIVE), *args)
    print(f"$ directive {' '.join(args)}\n{out}", flush=True)
    return out


def header(body: str) -> dict:
    return dict(line.split(": ", 1) for line in body.splitlines()[:3] if ": " in line)


def commit(f: Path, text: str, msg: str) -> str:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    sh("git", "add", str(f))
    sh("git", "commit", "-q", "-m", msg)
    return f"{sh('git', 'branch', '--show-current')}@{sh('git', 'rev-parse', '--short', 'HEAD')}"


def work(h: dict) -> str:
    feature, layer, node = h.get("feature", "x"), h.get("layer", "-"), h.get("node", "")
    stamp = time.time_ns()
    if ROLE == "impl":
        return commit(Path("src") / f"{layer}.txt", f"{feature} {layer} {stamp}\n", f"impl: {feature} {layer}")
    if ROLE == "reviewer":
        f = Path("coord") / "review" / f"{feature}.md"
        verdict = "CHANGES_REQUESTED" if os.environ.get("FAKE_REJECT_FIRST") and not f.exists() else "APPROVED"
        return commit(f, f"{verdict}\n가짜 리뷰 {stamp}\n", f"review: {feature}")
    if ROLE == "feature_design":
        return commit(Path("coord") / "design" / f"{feature}.md", f"# {feature}\n{stamp}\n", f"design: {feature}")
    if ROLE == "standards_checker":
        return commit(Path("coord") / "standards-check" / f"impl-{feature}.md", f"PASS\n{stamp}\n", f"std: {feature}")
    if ROLE == "sil":
        f = Path("reports") / node / f"{feature}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"결과: PASS\n{stamp}\n")
        return str(f)
    if ROLE == "integrator":
        sh("git", "fetch", "-q", "origin")
        sh("git", "merge", "-q", "--no-edit", "origin/main")
        me = sh("git", "branch", "--show-current")
        for b in sh("git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/feat/{feature}/").split():
            if b != me:
                sh("git", "merge", "-q", "--no-ff", "--no-edit", b)
        sh("git", "push", "-q", "origin", "HEAD:main")
        return f"main@{sh('git', 'rev-parse', '--short', 'HEAD')}"
    return commit(Path("coord") / "issue" / f"{feature}-{ROLE}.md", f"{ROLE} {stamp}\n", f"{ROLE}: {feature}")


def check_inbox() -> None:
    for line in directive("list").splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in ("delivered", "acked"):
            continue
        did = parts[0]
        body = sh(str(DIRECTIVE), "show", did).split("\n\n", 1)[-1]
        if parts[1] == "delivered":
            directive("ack", did)
        directive("start", did)
        ref = work(header(body))
        directive("done", did, "--ref", ref)
        print(f"결과: done ({did})\n산출물: {ref}", flush=True)


print(f"fake claude: {SESSION} ({ROLE})", flush=True)
check_inbox()
for _ in sys.stdin:
    check_inbox()

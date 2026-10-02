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


def work(h: dict) -> str:
    feature, layer = h.get("feature", "x"), h.get("layer", "-")
    if ROLE == "impl":
        f = Path("src") / f"{layer}.txt"
    elif ROLE == "reviewer":
        f = Path("coord") / "review" / f"{feature}.md"
    else:
        f = Path("coord") / "issue" / f"{feature}-{ROLE}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    verdict = "APPROVED"
    if ROLE == "reviewer" and os.environ.get("FAKE_REJECT_FIRST") and not f.exists():
        verdict = "CHANGES_REQUESTED"
    f.write_text(f"{verdict}\n가짜 리뷰 {time.time_ns()}\n" if ROLE == "reviewer" else f"{ROLE} {feature} {layer} {time.time_ns()}\n")
    sh("git", "add", str(f))
    sh("git", "commit", "-q", "-m", f"{ROLE}: {feature} {layer}")
    return f"{sh('git', 'branch', '--show-current')}@{sh('git', 'rev-parse', '--short', 'HEAD')}"


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

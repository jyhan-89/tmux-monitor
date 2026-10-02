import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import history
import models
import tokens

ROOT = Path(__file__).resolve().parent
TICK = 5.0
GATE_TIMEOUT = 30 * 60
NUDGE_AFTER = 120.0
log = logging.getLogger("orchestrator")


class ApiError(Exception):
    pass


class Server:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}/api{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise ApiError(f"{method} {path}: {e.code} {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            raise ApiError(f"{method} {path}: {e.reason}")

    def stopped(self) -> bool:
        return self.call("GET", "/control/status")["stopped"] is not None

    def company(self) -> models.Company:
        return models.parse_texts({k: self.call("GET", f"/company/{k}")["text"] for k in models.PARSERS})

    def role_sessions(self) -> dict[str, dict]:
        return {s["name"]: s for s in self.call("GET", "/company/sessions")}

    def launch(self, division: str, dept: str, role: str, index: str | None, feature: str) -> dict:
        return self.call("POST", "/company/sessions", {"division": division, "dept": dept, "role": role, "index": index, "feature": feature})

    def send(self, dtype: str, to: str, body: str, priority: str = "normal") -> dict:
        return self.call("POST", "/directives", {"type": dtype, "to": to, "body": body, "priority": priority})

    def directive(self, did: str) -> dict:
        return self.call("GET", f"/directives/{did}")

    def deliver(self, session: str) -> None:
        self.call("POST", f"/directives/deliver/{session}")

    def wake(self, session: str) -> bool:
        return self.call("POST", f"/control/wake/{session}")["woken"]


def state_dir() -> Path:
    return history.DATA_DIR / "state"


def state_path(division: str, feature: str) -> Path:
    return state_dir() / division / f"{feature}.json"


def save(inst: dict) -> None:
    p = state_path(inst["division"], inst["feature"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(inst, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(p)


def instances() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(state_dir().glob("*/*.json"))] if state_dir().exists() else []


def new_instance(company: models.Company, division: str, feature: str, brief: str = "") -> dict:
    div = company.org.divisions.get(division)
    if not div:
        raise ValueError(f"본부 '{division}'이(가) 없습니다")
    tkey = div.template or next(iter(company.process.templates))
    if state_path(division, feature).exists():
        raise ValueError(f"이미 있는 인스턴스: {division}/{feature}")
    inst = {"division": division, "feature": feature, "template": tkey, "brief": brief, "status": "running",
            "node": company.process.templates[tkey].start, "entered": time.time(), "directives": {}, "attempt": 0,
            "counters": {}, "source_node": None, "nudged": 0, "last_wake": 0, "note": "", "outputs": {}}
    save(inst)
    history.record({"type": "node_enter", "session": "-", "division": division, "feature": feature, "node": inst["node"]})
    return inst


def placement(company: models.Company, division: str, role: str) -> tuple[str, models.Dept | None]:
    div = company.org.divisions[division]
    for key, dept in div.depts.items():
        if any(m.role == role for m in dept.all_members()):
            return key, dept
    return "shared", None


def gate_path(gate: str, div: models.Division) -> Path:
    rel = models.resolve_gate(gate, div)
    for base in (tokens.company_dir(), ROOT):
        p = base / rel
        if p.exists():
            return p
    return Path(rel)


def tracked_state(wt: str) -> str:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=wt, capture_output=True, text=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True)
    return r.stdout + head.stdout


def run_gate(gate: str, div: models.Division, worktree: str, feature: str, node: str) -> tuple[bool, str]:
    path = gate_path(gate, div)
    if not path.exists():
        return False, f"게이트 스크립트가 없습니다: {path}"
    out_dir = history.DATA_DIR / "gate-out" / div.id / feature / node
    out_dir.mkdir(parents=True, exist_ok=True)
    before = tracked_state(worktree)
    try:
        r = subprocess.run([str(path), worktree, feature, str(out_dir)], cwd=worktree, capture_output=True, text=True,
                           timeout=GATE_TIMEOUT)
        ok, text = r.returncode == 0, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        ok, text = False, "게이트 시간 초과"
    if tracked_state(worktree) != before:
        ok, text = False, text + "\n게이트가 저장소 상태를 바꿨습니다 (게이트는 읽기 전용이어야 합니다)"
    return ok, "\n".join(text.splitlines()[-20:])


def node_body(company: models.Company, inst: dict, node: models.Node, layer: str | None) -> str:
    header = f"feature: {inst['feature']}\nnode: {node.id}\nlayer: {layer or '-'}\n"
    for base in (tokens.company_dir(), ROOT / "company"):
        p = base / "prompts" / "nodes" / f"{node.id}.md"
        if p.exists():
            text = p.read_text()
            break
    else:
        text = "노드 '{node}' 작업을 수행한다. 기능: {feature}, 계층: {layer}\n"
    text = text.format(feature=inst["feature"], node=node.id, layer=layer or "-", division=inst["division"])
    extra = []
    if inst.get("brief"):
        extra.append(f"## 요청\n\n{inst['brief']}")
    outputs = inst.get("outputs") or {}
    if outputs:
        lines = [f"- {k}: {', '.join(v)}" for k, v in outputs.items()]
        extra.append("## 이전 단계 산출물\n\n" + "\n".join(lines))
    if inst.get("note"):
        extra.append(f"## 이전 시도 결과\n\n{inst['note']}")
    return header + "\n" + text.strip() + ("\n\n" + "\n\n".join(extra) if extra else "") + "\n"


class Orchestrator:
    def __init__(self, server: Server):
        self.server = server

    def tick(self) -> None:
        if self.server.stopped():
            return
        company = self.server.company()
        sessions = self.server.role_sessions()
        for inst in instances():
            if inst["status"] != "running":
                continue
            try:
                self.step(company, sessions, inst)
            except ApiError as e:
                log.warning("%s/%s: %s", inst["division"], inst["feature"], e)

    def step(self, company: models.Company, sessions: dict, inst: dict) -> None:
        template = company.process.templates[inst["template"]]
        div = company.org.divisions[inst["division"]]
        node = template.nodes[inst["node"]]
        if node.type == "terminal":
            self.finish(inst, "done")
            return
        if node.type == "approval":
            self.finish(inst, "escalated")
            return
        if not inst["directives"]:
            self.start_node(company, sessions, inst, node)
            return
        ds = {key: self.server.directive(did) for key, did in inst["directives"].items()}
        bad = [d for d in ds.values() if d["status"] in ("blocked", "rejected")]
        if bad:
            reasons = "; ".join(f"{d['to']} {d['status']}: {d['status_log'][-1].get('reason', '')}" for d in bad)
            self.fail(template, inst, node, reasons)
            return
        if all(d["status"] == "done" for d in ds.values()):
            missing = [d["to"] for d in ds.values() if not d.get("refs")]
            if missing:
                self.fail(template, inst, node, f"산출물 참조(--ref) 없이 done: {', '.join(missing)}")
                return
            ok, report = True, []
            for key, d in ds.items():
                wt = (sessions.get(d["to"], {}).get("meta") or {}).get("worktree", "")
                for g in (node.pre_gate, node.gate):
                    if not g:
                        continue
                    passed, tail = run_gate(g, div, wt, inst["feature"], node.id)
                    history.record({"type": "gate_result", "session": d["to"], "division": inst["division"],
                                    "feature": inst["feature"], "node": node.id, "gate": g,
                                    "result": "pass" if passed else "fail", "tail": tail})
                    if not passed:
                        ok = False
                        report.append(f"[{d['to']}] {g}\n{tail}")
                        break
            if ok:
                inst.setdefault("outputs", {})[node.id] = [r for d in ds.values() for r in d.get("refs", [])]
                self.advance(template, inst, node, node.next, passed=True)
            else:
                self.fail(template, inst, node, "\n\n".join(report))
            return
        self.nudge(sessions, inst, ds)

    def nudge(self, sessions: dict, inst: dict, ds: dict) -> None:
        now = time.time()
        idle = [d["to"] for d in ds.values() if d["status"] in ("delivered", "acked", "in_progress")
                and sessions.get(d["to"], {}).get("state") == "idle"]
        if not idle or now - inst["last_wake"] < NUDGE_AFTER:
            return
        for name in idle:
            self.server.wake(name)
        inst["last_wake"] = now
        inst["nudged"] += 1
        save(inst)

    def start_node(self, company: models.Company, sessions: dict, inst: dict, node: models.Node) -> None:
        dept_key, dept = placement(company, inst["division"], node.role)
        layers = (dept.layers if dept and node.parallel else []) or [None]
        sent = {}
        for layer in layers:
            index = layer
            if index is None:
                members = dept.all_members() if dept else list(company.org.shared.values())
                count = next((m.count for m in members if m.role == node.role), 1)
                index = "1" if count > 1 else None
            launched = self.server.launch(inst["division"], dept_key, node.role, index, inst["feature"])
            name = launched["name"]
            d = self.server.send("node", name, node_body(company, inst, node, layer))
            if d["status"] == "queued":
                self.server.deliver(name)
            self.server.wake(name)
            sent[layer or node.role] = d["id"]
        inst.update(directives=sent, last_wake=time.time(), nudged=0)
        save(inst)
        history.record({"type": "node_enter", "session": ",".join(sent), "division": inst["division"],
                        "feature": inst["feature"], "node": node.id, "directives": list(sent.values())})

    def fail(self, template: models.Template, inst: dict, node: models.Node, reason: str) -> None:
        inst["note"] = reason
        if inst["attempt"] < node.retry:
            inst["attempt"] += 1
            inst["directives"] = {}
            save(inst)
            history.record({"type": "loop_count", "session": "-", "division": inst["division"], "feature": inst["feature"],
                            "node": node.id, "retry": inst["attempt"]})
            return
        target = template.nodes.get(node.on_fail)
        if target and target.loop:
            inst["source_node"] = node.id
        self.advance(template, inst, node, node.on_fail, passed=False)

    def advance(self, template: models.Template, inst: dict, node: models.Node, target: str, passed: bool) -> None:
        if passed and node.loop and inst.get("source_node"):
            src = inst["source_node"]
            inst["counters"][src] = inst["counters"].get(src, 0) + 1
            history.record({"type": "loop_count", "session": "-", "division": inst["division"], "feature": inst["feature"],
                            "node": node.id, "source_node": src, "count": inst["counters"][src], "max": node.loop.max.get(src)})
            if inst["counters"][src] > node.loop.max.get(src, 0):
                target = node.loop.on_exceed
            inst["source_node"] = None
        history.record({"type": "node_done", "session": "-", "division": inst["division"], "feature": inst["feature"],
                        "node": node.id, "result": "pass" if passed else "fail", "next": target})
        if passed:
            inst["note"] = ""
        inst.update(node=target, directives={}, attempt=0, entered=time.time(), nudged=0)
        save(inst)
        history.record({"type": "node_enter", "session": "-", "division": inst["division"], "feature": inst["feature"], "node": target})

    def finish(self, inst: dict, status: str) -> None:
        inst["status"] = status
        save(inst)
        history.record({"type": "escalate" if status == "escalated" else "node_done", "session": "-",
                        "division": inst["division"], "feature": inst["feature"], "node": inst["node"], "result": status})


def dry_run(folder: Path) -> int:
    try:
        company = models.load_dir(folder)
    except models.DefinitionError as e:
        for i in e.issues:
            print(f"오류 {i.rule} @ {i.where}: {i.message}")
        return 1
    for tkey, t in company.process.templates.items():
        print(f"[{tkey}] start: {t.start}")
        for key, n in t.nodes.items():
            if n.type == "terminal":
                print(f"  {key}: 종료")
            elif n.type == "approval":
                print(f"  {key}: 결재 {n.options}")
            else:
                loop = f" loop→{n.loop.on_exceed} {n.loop.max}" if n.loop else ""
                print(f"  {key} ({n.role}): pass→{n.next} fail→{n.on_fail}{' retry ' + str(n.retry) if n.retry else ''}{loop}")
    return 0


def server_from_env() -> Server:
    port = os.environ.get("PORT", "8765")
    base = os.environ.get("BASE_PATH", "/dev").rstrip("/")
    url = os.environ.get("TMUX_WEB_URL", f"http://127.0.0.1:{port}{base}")
    return Server(url, os.environ.get("TMUX_WEB_ORCH_TOKEN") or tokens.ensure_token("orchestrator"))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(prog="orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true")
    s = sub.add_parser("start")
    s.add_argument("division")
    s.add_argument("feature")
    s.add_argument("--brief", default="")
    sub.add_parser("list")
    d = sub.add_parser("dry-run")
    d.add_argument("folder")
    a = p.parse_args(argv)
    if a.cmd == "dry-run":
        return dry_run(Path(a.folder))
    if a.cmd == "list":
        for i in instances():
            print(f"{i['division']}/{i['feature']}  {i['status']:<10} node={i['node']} attempt={i['attempt']} counters={i['counters']}")
        return 0
    server = server_from_env()
    if a.cmd == "start":
        inst = new_instance(server.company(), a.division, a.feature, a.brief)
        print(f"{inst['division']}/{inst['feature']} 시작: {inst['node']}")
        return 0
    orch = Orchestrator(server)
    while True:
        try:
            orch.tick()
        except ApiError as e:
            log.warning("%s", e)
        if a.once:
            return 0
        time.sleep(TICK)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

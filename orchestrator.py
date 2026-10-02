import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import commands
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
            with urllib.request.urlopen(req, timeout=90) as r:
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

    def wake(self, session: str, text: str | None = None) -> bool:
        return self.call("POST", f"/control/wake/{session}", {"text": text} if text else None)["woken"]

    def set_node(self, session: str, node: str) -> None:
        self.call("PATCH", f"/company/sessions/{session}/meta", {"node": node})

    def restart(self, session: str) -> dict:
        return self.call("POST", f"/company/sessions/{session}/restart")

    def approval_create(self, kind: str, instance: str, node: str, summary: str, evidence: list[str],
                        options: list[str] | None = None, session: str | None = None) -> dict:
        return self.call("POST", "/approvals", {"kind": kind, "instance": instance, "node": node, "summary": summary,
                                                 "evidence": evidence, "options": options, "session": session})

    def approval(self, aid: str) -> dict:
        return self.call("GET", f"/approvals/{aid}")

    def approval_close(self, aid: str, reason: str) -> dict:
        return self.call("POST", f"/approvals/{aid}/close", {"reason": reason})


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
    return commands.instances()


def load(division: str, feature: str) -> dict:
    return json.loads(state_path(division, feature).read_text())


def new_instance(company: models.Company, division: str, feature: str, brief: str = "") -> dict:
    div = company.org.divisions.get(division)
    if not div:
        raise ValueError(f"본부 '{division}'이(가) 없습니다")
    tkey = div.template or next(iter(company.process.templates))
    if state_path(division, feature).exists():
        raise ValueError(f"이미 있는 인스턴스: {division}/{feature}")
    inst = {"division": division, "feature": feature, "template": tkey, "brief": brief, "status": "running",
            "node": company.process.templates[tkey].start, "entered": time.time(), "directives": {}, "attempt": 0,
            "counters": {}, "source_node": None, "nudged": 0, "last_wake": 0, "note": "", "outputs": {},
            "approval": None, "approved": None, "paused": 0, "wait_started": None, "asks": {}, "prev_node": None}
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


PRIORITY_ROLES = {"sil": 0, "hil": 0, "analysis": 1}


def priority(company: models.Company, inst: dict) -> int:
    t = company.process.templates[inst["template"]]
    node = t.nodes.get(inst["node"])
    return PRIORITY_ROLES.get(node.role if node else "", 2)


def escalate_node(template: models.Template) -> str | None:
    if "escalate" in template.nodes and template.nodes["escalate"].type == "approval":
        return "escalate"
    return next((k for k, n in template.nodes.items() if n.type == "approval"), None)


def iso_age(ts: str, now: float) -> float:
    try:
        return now - datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return 0.0


class Orchestrator:
    def __init__(self, server: Server, max_active: int | None = None):
        self.server = server
        self.max_active = max_active or int(os.environ.get("TMUX_WEB_MAX_ACTIVE", "4"))

    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        company = self.server.company()
        for cmd in commands.take():
            self.command(company, cmd)
        if self.server.stopped():
            return
        sessions = self.server.role_sessions()
        active = sum(1 for s in sessions.values() if s.get("state") == "working")
        running = [i for i in instances() if i["status"] == "running"]
        running.sort(key=lambda i: (priority(company, i), i.get("entered", 0)))
        for inst in running:
            try:
                active += self.step(company, sessions, inst, now, active)
            except ApiError as e:
                log.warning("%s/%s: %s", inst["division"], inst["feature"], e)

    def command(self, company: models.Company, cmd: dict) -> None:
        try:
            if cmd["cmd"] == "start":
                new_instance(company, cmd["division"], cmd["feature"], cmd.get("brief", ""))
            elif cmd["cmd"] == "transition":
                inst = load(cmd["division"], cmd["feature"])
                template = company.process.templates[inst["template"]]
                if cmd["to"] not in template.nodes:
                    raise ValueError(f"노드 '{cmd['to']}'이(가) 없습니다")
                history.record({"type": "manual_transition", "session": "-", "division": inst["division"],
                                "feature": inst["feature"], "from": inst["node"], "to": cmd["to"], "reason": cmd.get("reason")})
                inst["status"] = "running"
                self.move(inst, cmd["to"], note=cmd.get("reason", ""))
            elif cmd["cmd"] == "restored":
                for inst in instances():
                    if inst["status"] == "running" and inst["directives"]:
                        inst["restored"] = True
                        save(inst)
        except (ValueError, KeyError, FileNotFoundError, ApiError) as e:
            log.warning("명령 실패 %s: %s", cmd, e)

    def step(self, company: models.Company, sessions: dict, inst: dict, now: float, active: int) -> int:
        template = company.process.templates[inst["template"]]
        div = company.org.divisions[inst["division"]]
        node = template.nodes[inst["node"]]
        if node.type == "terminal":
            self.finish(inst, "done")
            return 0
        if node.type == "approval":
            self.escalation(template, inst, node)
            return 0
        if node.requires_approval and inst.get("approved") != node.id:
            self.gate_approval(template, inst, node, now)
            return 0
        if self.timed_out(template, inst, now):
            return 0
        if not inst["directives"]:
            if active >= self.max_active:
                if not inst.get("queued"):
                    inst["queued"] = True
                    save(inst)
                    history.record({"type": "status_change", "session": "-", "division": inst["division"],
                                    "feature": inst["feature"], "node": node.id, "to": "queued"})
                return 0
            inst["queued"] = False
            return self.start_node(company, sessions, inst, node)
        ds = {key: self.server.directive(did) for key, did in inst["directives"].items()}
        if inst.pop("restored", False):
            self.recover(company, sessions, inst, ds)
            return 0
        self.needs_input(sessions, inst, node, ds)
        if self.ack_timeout(template, inst, ds, now):
            return 0
        bad = [d for d in ds.values() if d["status"] in ("blocked", "rejected")]
        if bad:
            reasons = "; ".join(f"{d['to']} {d['status']}: {d['status_log'][-1].get('reason', '')}" for d in bad)
            self.fail(template, inst, node, reasons)
            return 0
        if all(d["status"] == "done" for d in ds.values()):
            self.judge(template, div, sessions, inst, node, ds)
            return 0
        self.nudge(sessions, inst, ds, now)
        return 0

    def judge(self, template, div, sessions, inst, node, ds) -> None:
        missing = [d["to"] for d in ds.values() if not d.get("refs")]
        if missing:
            self.fail(template, inst, node, f"산출물 참조(--ref) 없이 done: {', '.join(missing)}")
            return
        ok, report = True, []
        for d in ds.values():
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

    def instance_id(self, inst: dict) -> str:
        return f"{inst['division']}/{inst['feature']}"

    def evidence(self, inst: dict) -> list[str]:
        return [r for refs in (inst.get("outputs") or {}).values() for r in refs]

    def wait_begin(self, inst: dict, now: float) -> None:
        if not inst.get("wait_started"):
            inst["wait_started"] = now

    def wait_end(self, inst: dict, now: float) -> None:
        if inst.get("wait_started"):
            inst["paused"] = inst.get("paused", 0) + now - inst["wait_started"]
            inst["wait_started"] = None

    def gate_approval(self, template, inst, node, now) -> None:
        aid = inst.get("approval")
        if not aid:
            outputs = inst.get("outputs") or {}
            summary = (f"{self.instance_id(inst)} '{node.id}' 진행 승인 요청. 통과한 단계: {', '.join(outputs) or '없음'}."
                       + (f" 참고: {inst['note'][:200]}" if inst.get("note") else ""))
            a = self.server.approval_create("gate", self.instance_id(inst), node.id, summary, self.evidence(inst))
            inst["approval"] = a["id"]
            self.wait_begin(inst, now)
            save(inst)
            return
        a = self.server.approval(aid)
        if a["status"] == "pending":
            return
        inst["approval"] = None
        self.wait_end(inst, now)
        decision, reason = a.get("decision"), a.get("reason") or ""
        if decision == "approve":
            inst["approved"] = node.id
            save(inst)
        elif decision == "revise":
            inst["note"] = f"결재 수정 요청: {reason}"
            prev = inst.get("prev_node")
            if prev and prev in template.nodes:
                self.move(inst, prev, note=inst["note"])
            else:
                save(inst)
        else:
            self.fail(template, inst, node, f"결재 반려: {reason}", allow_retry=False)

    def escalation(self, template, inst, node) -> None:
        aid = inst.get("approval")
        if not aid:
            summary = (f"{self.instance_id(inst)} 에스컬레이션 (발생 노드: {inst.get('escalated_from') or inst.get('prev_node') or '-'}). "
                       f"{(inst.get('note') or '')[:300]}")
            a = self.server.approval_create("escalate", self.instance_id(inst), node.id, summary, self.evidence(inst), node.options)
            inst["approval"] = a["id"]
            inst["status_detail"] = "escalated"
            save(inst)
            history.record({"type": "escalate", "session": "-", "division": inst["division"], "feature": inst["feature"],
                            "node": node.id, "from": inst.get("escalated_from"), "approval": a["id"]})
            return
        a = self.server.approval(aid)
        if a["status"] == "pending":
            return
        inst["approval"] = None
        inst["status_detail"] = None
        decision, reason = a.get("decision"), a.get("reason") or ""
        if decision == "redesign":
            inst["counters"] = {}
            self.move(inst, template.start, note=f"재설계 지시: {reason}")
        elif decision == "drop":
            inst["note"] = f"중단: {reason}"
            self.finish(inst, "dropped")
        elif decision == "override":
            src = template.nodes.get(inst.get("escalated_from") or "")
            target = src.next if src and src.next else template.start
            self.move(inst, target, note=f"결재로 통과 처리: {reason}")
        elif decision in template.nodes:
            self.move(inst, decision, note=reason)

    def needs_input(self, sessions, inst, node, ds) -> None:
        asks = inst.setdefault("asks", {})
        for d in ds.values():
            name = d["to"]
            state = sessions.get(name, {}).get("state")
            if state == "waiting" and name not in asks:
                a = self.server.approval_create("needs_input", self.instance_id(inst), node.id,
                                                f"{name} 세션이 입력을 기다립니다. 터미널에서 답하면 자동으로 닫힙니다.", [], None, name)
                asks[name] = a["id"]
                save(inst)
            elif state != "waiting" and name in asks:
                self.server.approval_close(asks.pop(name), "세션이 다시 진행됨")
                save(inst)

    def timed_out(self, template, inst, now) -> bool:
        limit = template.limits.get("node_timeout_h")
        if not limit:
            return False
        spent = now - inst["entered"] - inst.get("paused", 0)
        if spent <= limit * 3600:
            return False
        node = template.nodes[inst["node"]]
        self.to_escalate(template, inst, node, f"노드 시간 상한 {limit}시간 초과")
        return True

    def ack_timeout(self, template, inst, ds, now) -> bool:
        limit = template.limits.get("ack_timeout_h")
        if not limit:
            return False
        late = [d for d in ds.values() if d["status"] == "delivered"
                and iso_age(next((x["at"] for x in reversed(d["status_log"]) if x["to"] == "delivered"), ""), now) > limit * 3600]
        if not late:
            return False
        node = template.nodes[inst["node"]]
        if inst.get("ack_restarted"):
            self.to_escalate(template, inst, node, f"지시서 확인 없음 (재시작 후에도): {', '.join(d['to'] for d in late)}")
            return True
        for d in late:
            self.server.restart(d["to"])
            self.server.deliver(d["to"])
            self.server.wake(d["to"])
        inst["ack_restarted"] = True
        save(inst)
        history.record({"type": "session_stop", "session": ",".join(d["to"] for d in late), "reason": "ack_timeout_restart",
                        "division": inst["division"], "feature": inst["feature"], "node": node.id})
        return True

    def to_escalate(self, template, inst, node, reason) -> None:
        target = escalate_node(template)
        inst["note"] = reason
        inst["escalated_from"] = node.id
        history.record({"type": "node_done", "session": "-", "division": inst["division"], "feature": inst["feature"],
                        "node": node.id, "result": "timeout", "next": target, "reason": reason})
        if target:
            self.move(inst, target, note=reason)
        else:
            self.finish(inst, "escalated")

    def recover(self, company, sessions, inst, ds) -> None:
        for d in ds.values():
            name = d["to"]
            if name in sessions:
                self.server.restart(name)
            else:
                parsed = name.split("-")
                self.server.launch(parsed[0], parsed[1], parsed[2], parsed[3] if len(parsed) > 3 else None, inst["feature"])
            self.server.deliver(name)
            self.server.wake(name, "inbox 지시서 상태 확인 후 계속")
        save(inst)

    def nudge(self, sessions: dict, inst: dict, ds: dict, now: float) -> None:
        idle = [d["to"] for d in ds.values() if d["status"] in ("delivered", "acked", "in_progress")
                and sessions.get(d["to"], {}).get("state") == "idle"]
        if not idle or now - inst["last_wake"] < NUDGE_AFTER:
            return
        for name in idle:
            self.server.wake(name)
        inst["last_wake"] = now
        inst["nudged"] += 1
        save(inst)

    def start_node(self, company: models.Company, sessions: dict, inst: dict, node: models.Node) -> int:
        dept_key, dept = placement(company, inst["division"], node.role)
        layers = (dept.layers if dept and node.parallel else []) or [None]
        dtype = "merge" if node.role == "integrator" and "merge" in company.documents.directives else "node"
        sent = {}
        for layer in layers:
            index = layer
            if index is None:
                members = dept.all_members() if dept else list(company.org.shared.values())
                count = next((m.count for m in members if m.role == node.role), 1)
                index = "1" if count > 1 else None
            launched = self.server.launch(inst["division"], dept_key, node.role, index, inst["feature"])
            name = launched["name"]
            self.server.set_node(name, node.id)
            d = self.server.send(dtype, name, node_body(company, inst, node, layer))
            if d["status"] == "queued":
                self.server.deliver(name)
            self.server.wake(name)
            sent[layer or node.role] = d["id"]
        inst.update(directives=sent, last_wake=time.time(), nudged=0, ack_restarted=False)
        save(inst)
        history.record({"type": "node_enter", "session": ",".join(sent), "division": inst["division"],
                        "feature": inst["feature"], "node": node.id, "directives": list(sent.values())})
        return len(sent)

    def fail(self, template: models.Template, inst: dict, node: models.Node, reason: str, allow_retry: bool = True) -> None:
        inst["note"] = reason
        if allow_retry and inst["attempt"] < node.retry:
            inst["attempt"] += 1
            inst["directives"] = {}
            save(inst)
            history.record({"type": "loop_count", "session": "-", "division": inst["division"], "feature": inst["feature"],
                            "node": node.id, "retry": inst["attempt"]})
            return
        target = template.nodes.get(node.on_fail)
        if target and target.loop:
            inst["source_node"] = node.id
        if target and target.type == "approval":
            inst["escalated_from"] = node.id
        self.advance(template, inst, node, node.on_fail, passed=False)

    def advance(self, template: models.Template, inst: dict, node: models.Node, target: str, passed: bool) -> None:
        if passed and node.loop and inst.get("source_node"):
            src = inst["source_node"]
            inst["counters"][src] = inst["counters"].get(src, 0) + 1
            history.record({"type": "loop_count", "session": "-", "division": inst["division"], "feature": inst["feature"],
                            "node": node.id, "source_node": src, "count": inst["counters"][src], "max": node.loop.max.get(src)})
            if inst["counters"][src] > node.loop.max.get(src, 0):
                target = node.loop.on_exceed
                inst["escalated_from"] = src
            inst["source_node"] = None
        history.record({"type": "node_done", "session": "-", "division": inst["division"], "feature": inst["feature"],
                        "node": node.id, "result": "pass" if passed else "fail", "next": target})
        self.move(inst, target, note="" if passed else inst.get("note", ""))

    def move(self, inst: dict, target: str, note: str = "") -> None:
        inst["prev_node"] = inst["node"]
        inst.update(node=target, directives={}, attempt=0, entered=time.time(), nudged=0, note=note,
                    approval=None, approved=None, paused=0, wait_started=None, ack_restarted=False, asks={})
        save(inst)
        history.record({"type": "node_enter", "session": "-", "division": inst["division"], "feature": inst["feature"], "node": target})

    def finish(self, inst: dict, status: str) -> None:
        inst["status"] = status
        save(inst)
        history.record({"type": "node_done", "session": "-", "division": inst["division"], "feature": inst["feature"],
                        "node": inst["node"], "result": status})


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
    last_error = ""
    while True:
        try:
            orch.tick()
            last_error = ""
        except (ApiError, models.DefinitionError) as e:
            if str(e) != last_error:
                log.warning("대기: %s", e)
                last_error = str(e)
        if a.once:
            return 0
        time.sleep(TICK)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

from pathlib import Path

import pytest
import yaml

import history
import models
import orchestrator
import store
from tmuxctl import role_session_name

SAMPLE = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"

MINI = """
version: 1
templates:
  mini:
    start: implement
    nodes:
      implement:
        role: impl
        parallel: true
        retry: 1
        gate: gates/common/has_new_commit.sh
        next: review
        on_fail: analyze
      review:
        role: reviewer
        gate: gates/common/review_approved.sh
        next: done
        on_fail: analyze
      analyze:
        role: analysis
        next: implement
        on_fail: escalate
        loop:
          max: {implement: 1, review: 1}
          on_exceed: escalate
      escalate:
        type: approval
        options: [redesign, drop]
      done:
        type: terminal
    limits:
      node_timeout_h: 24
"""


class FakeServer:
    def __init__(self, company):
        self._company = company
        self.sessions: dict[str, dict] = {}
        self.directives: dict[str, dict] = {}
        self.woken: list[str] = []
        self.is_stopped = False
        self.n = 0
        self.wake_texts = []
        self.restarted = []
        self.approvals = {}

    def stopped(self):
        return self.is_stopped

    def company(self):
        return self._company

    def role_sessions(self):
        return self.sessions

    def launch(self, division, dept, role, index, feature):
        name = role_session_name(division, dept, role, index)
        self.sessions.setdefault(name, {"name": name, "meta": {"worktree": f"/wt/{name}"}, "state": "idle"})
        return {"name": name}

    def send(self, dtype, to, body, priority="normal"):
        self.n += 1
        d = {"id": f"d-{self.n}", "type": dtype, "to": to, "body": body, "status": "delivered", "refs": [],
             "status_log": [{"to": "delivered"}]}
        self.directives[d["id"]] = d
        return d

    def directive(self, did):
        return self.directives[did]

    def deliver(self, session):
        pass

    def wake(self, session, text=None):
        self.woken.append(session)
        self.wake_texts.append(text)
        return True

    def set_node(self, session, node):
        self.sessions[session].setdefault("meta", {})["node"] = node

    def restart(self, session):
        self.restarted.append(session)
        return {"name": session}

    def approval_create(self, kind, instance, node, summary, evidence, options=None, session=None):
        for a in self.approvals.values():
            if a["status"] == "pending" and (a["kind"], a["instance"], a["node"]) == (kind, instance, node):
                return a
        aid = f"ap-{len(self.approvals) + 1}"
        self.approvals[aid] = {"id": aid, "kind": kind, "instance": instance, "node": node, "summary": summary,
                               "evidence": evidence, "options": options, "session": session, "status": "pending"}
        return self.approvals[aid]

    def approval(self, aid):
        return self.approvals[aid]

    def approval_close(self, aid, reason):
        self.approvals[aid]["status"] = "closed"
        return self.approvals[aid]

    def decide(self, decision, reason="사유", kind=None):
        for a in self.approvals.values():
            if a["status"] == "pending" and (kind is None or a["kind"] == kind):
                a.update(status="decided", decision=decision, reason=reason)
                return a
        raise AssertionError("pending approval 없음")

    def finish_all(self, status="done", refs=("feat/x@1",), reason=None):
        for d in self.directives.values():
            if d["status"] == "delivered":
                d["status"] = status
                d["refs"] = list(refs)
                d["status_log"].append({"to": status, "reason": reason})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(history, "DATA_DIR", tmp_path / "data")
    texts = {k: (SAMPLE / f"{k}.yaml").read_text() for k in models.PARSERS}
    org = yaml.safe_load(texts["org"])
    org["divisions"]["mw"]["template"] = "mini"
    texts["org"] = yaml.safe_dump(org, allow_unicode=True)
    texts["process"] = MINI
    company = models.parse_texts(texts)
    server = FakeServer(company)
    gates: dict[str, list[bool]] = {}
    calls: list[tuple[str, str]] = []

    def fake_gate(gate, div, wt, feature, node, env=None):
        calls.append((node, wt))
        results = gates.get(node, [])
        ok = results.pop(0) if results else True
        return ok, "" if ok else f"{node} 게이트 실패"
    monkeypatch.setattr(orchestrator, "run_gate", fake_gate)
    orch = orchestrator.Orchestrator(server)
    orchestrator.new_instance(company, "mw", "svc_a", "svc-a 구현")
    return orch, server, gates, calls


def inst():
    return orchestrator.instances()[0]


def test_happy_path_parallel_layers(env):
    orch, server, gates, calls = env
    orch.tick()
    assert set(server.sessions) == {"mw-impl-impl-skeleton", "mw-impl-impl-proxy"}
    assert set(inst()["directives"]) == {"skeleton", "proxy"}
    body = next(iter(server.directives.values()))["body"]
    assert "feature: svc_a" in body and "svc-a 구현" in body
    assert set(server.woken) == set(server.sessions)
    assert all(s["meta"]["node"] == "implement" for s in server.sessions.values())
    orch.tick()
    assert inst()["node"] == "implement"
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "review"
    assert sorted(w for _, w in calls) == ["/wt/mw-impl-impl-proxy", "/wt/mw-impl-impl-skeleton"]
    orch.tick()
    assert "mw-quality-reviewer" in server.sessions
    review_body = list(server.directives.values())[-1]["body"]
    assert "이전 단계 산출물" in review_body and "implement: feat/x@1" in review_body
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "done"
    orch.tick()
    assert inst()["status"] == "done"
    types = [e["type"] for e in history.query()]
    assert types.count("gate_result") == 3 and "node_enter" in types


def test_retry_then_on_fail_and_loop_counter(env):
    orch, server, gates, _ = env
    gates["implement"] = [False, True, False, False, False, False, False, False]
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "implement" and inst()["attempt"] == 1 and inst()["directives"] == {}
    assert "게이트 실패" in inst()["note"]
    orch.tick()
    assert "이전 시도 결과" in list(server.directives.values())[-1]["body"]
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "analyze" and inst()["source_node"] == "implement"
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "implement" and inst()["counters"] == {"implement": 1}
    for _ in range(2):
        orch.tick()
        server.finish_all()
        orch.tick()
    assert inst()["node"] == "analyze"
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "escalate" and inst()["counters"] == {"implement": 2}
    orch.tick()
    a = next(iter(server.approvals.values()))
    assert a["kind"] == "escalate" and a["options"] == ["redesign", "drop"] and inst()["status_detail"] == "escalated"
    assert "implement" in a["summary"]


def test_blocked_and_missing_refs_fail(env):
    orch, server, _, _ = env
    orch.tick()
    server.finish_all(status="blocked", reason="타입 불일치")
    orch.tick()
    assert inst()["attempt"] == 1 and "타입 불일치" in inst()["note"]
    orch.tick()
    server.finish_all(refs=())
    orch.tick()
    assert inst()["node"] == "analyze" and "--ref" in inst()["note"]


def test_stopped_does_nothing(env):
    orch, server, _, _ = env
    server.is_stopped = True
    orch.tick()
    assert server.sessions == {} and inst()["directives"] == {}
    server.is_stopped = False
    orch.tick()
    assert inst()["directives"]


def test_nudge_idle_sessions(env, monkeypatch):
    orch, server, _, _ = env
    orch.tick()
    server.woken.clear()
    orch.tick()
    assert server.woken == []
    state = inst()
    state["last_wake"] -= orchestrator.NUDGE_AFTER + 1
    orchestrator.save(state)
    orch.tick()
    assert set(server.woken) == {"mw-impl-impl-skeleton", "mw-impl-impl-proxy"} and inst()["nudged"] == 1
    server.woken.clear()
    for s in server.sessions.values():
        s["state"] = "working"
    state = inst()
    state["last_wake"] -= orchestrator.NUDGE_AFTER + 1
    orchestrator.save(state)
    orch.tick()
    assert server.woken == []


def test_duplicate_instance_rejected(env):
    orch, server, _, _ = env
    with pytest.raises(ValueError):
        orchestrator.new_instance(server.company(), "mw", "svc_a")


def test_dry_run(capsys):
    assert orchestrator.dry_run(SAMPLE) == 0
    out = capsys.readouterr().out
    assert "analyze (analysis): pass→design" in out and "escalate: 결재" in out


def run_to_escalate(orch, server, gates):
    gates["review"] = [False]
    for _ in range(3):
        orch.tick()
        server.finish_all()
    orch.tick()
    assert inst()["node"] == "analyze"
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "implement"
    gates["review"] = [False]
    for _ in range(4):
        orch.tick()
        server.finish_all()
    orch.tick()
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "escalate", inst()
    orch.tick()


@pytest.mark.parametrize("decision, node, status", [("redesign", "implement", "running"), ("drop", "escalate", "dropped")])
def test_escalation_decisions(env, decision, node, status):
    orch, server, gates, _ = env
    run_to_escalate(orch, server, gates)
    server.decide(decision)
    orch.tick()
    assert inst()["node"] == node and inst()["status"] == status
    if decision == "redesign":
        assert inst()["counters"] == {} and "재설계" in inst()["note"]


def test_override_goes_to_next_of_source(env, monkeypatch):
    orch, server, gates, _ = env
    company = server.company()
    company.process.templates["mini"].nodes["escalate"].options = ["redesign", "drop", "override"]
    run_to_escalate(orch, server, gates)
    assert inst()["escalated_from"] == "review"
    server.decide("override")
    orch.tick()
    assert inst()["node"] == "done"


def test_gate_approval_before_start(env):
    orch, server, gates, _ = env
    company = server.company()
    company.process.templates["mini"].nodes["review"].requires_approval = True
    orch.tick()
    server.finish_all()
    orch.tick()
    assert inst()["node"] == "review"
    orch.tick()
    a = next(a for a in server.approvals.values() if a["kind"] == "gate")
    assert a["evidence"] == ["feat/x@1", "feat/x@1"] and inst()["directives"] == {}
    orch.tick()
    assert "mw-quality-reviewer" not in server.sessions
    server.decide("approve")
    orch.tick()
    assert inst()["approved"] == "review"
    orch.tick()
    assert "mw-quality-reviewer" in server.sessions


def test_gate_approval_reject_and_revise(env):
    orch, server, gates, _ = env
    company = server.company()
    company.process.templates["mini"].nodes["review"].requires_approval = True
    orch.tick()
    server.finish_all()
    orch.tick()
    orch.tick()
    server.decide("revise", "테스트 보강")
    orch.tick()
    assert inst()["node"] == "implement" and "테스트 보강" in inst()["note"]
    orch.tick()
    assert "테스트 보강" in list(server.directives.values())[-1]["body"]
    server.finish_all()
    orch.tick()
    orch.tick()
    server.decide("reject", "범위 초과")
    orch.tick()
    assert inst()["node"] == "analyze" and "범위 초과" in inst()["note"]


def test_needs_input_opens_and_closes(env):
    orch, server, _, _ = env
    orch.tick()
    server.sessions["mw-impl-impl-proxy"]["state"] = "waiting"
    orch.tick()
    ni = [a for a in server.approvals.values() if a["kind"] == "needs_input"]
    assert len(ni) == 1 and ni[0]["session"] == "mw-impl-impl-proxy"
    orch.tick()
    assert len([a for a in server.approvals.values() if a["kind"] == "needs_input"]) == 1
    server.sessions["mw-impl-impl-proxy"]["state"] = "working"
    orch.tick()
    assert ni[0]["status"] == "closed"


def test_node_timeout_escalates_excluding_wait(env):
    orch, server, _, _ = env
    import time as _t
    orch.tick()
    state = inst()
    state["entered"] -= 24 * 3600 + 10
    state["paused"] = 20
    orchestrator.save(state)
    orch.tick()
    assert inst()["node"] == "implement"
    state = inst()
    state["paused"] = 0
    orchestrator.save(state)
    orch.tick()
    assert inst()["node"] == "escalate" and "시간 상한" in inst()["note"]


def test_ack_timeout_restarts_once_then_escalates(env):
    orch, server, _, _ = env
    company = server.company()
    company.process.templates["mini"].limits["ack_timeout_h"] = 1
    orch.tick()
    old = "2000-01-01T00:00:00+09:00"
    for d in server.directives.values():
        d["status_log"] = [{"to": "delivered", "at": old}]
    orch.tick()
    assert sorted(server.restarted) == ["mw-impl-impl-proxy", "mw-impl-impl-skeleton"] and inst()["ack_restarted"]
    orch.tick()
    assert inst()["node"] == "escalate" and "확인 없음" in inst()["note"]


def test_queue_when_active_limit_reached(env):
    orch, server, _, _ = env
    orch.max_active = 2
    orchestrator.new_instance(server.company(), "mw", "svc_b")
    orch.tick()
    states = {i["feature"]: i for i in orchestrator.instances()}
    assert states["svc_a"]["directives"] and not states["svc_b"]["directives"] and states["svc_b"]["queued"]
    for s in server.sessions.values():
        s["state"] = "idle"
    server.finish_all()
    orch.tick()
    states = {i["feature"]: i for i in orchestrator.instances()}
    assert states["svc_b"]["directives"]


def test_commands_start_transition_restored(env):
    orch, server, _, _ = env
    import commands
    commands.put("start", division="mw", feature="svc_c", brief="")
    orch.tick()
    assert {i["feature"] for i in orchestrator.instances()} == {"svc_a", "svc_c"}
    commands.put("transition", division="mw", feature="svc_a", to="review", reason="수동")
    orch.tick()
    a = orchestrator.load("mw", "svc_a")
    assert a["node"] == "review" and a["directives"]
    assert history.query(type="manual_transition")[0]["to"] == "review"
    server.wake_texts.clear()
    commands.put("restored")
    orch.tick()
    assert "inbox 지시서 상태 확인 후 계속" in server.wake_texts
    assert sorted(server.restarted) == ["mw-impl-impl-proxy", "mw-impl-impl-skeleton", "mw-quality-reviewer"]
    commands.put("transition", division="mw", feature="svc_a", to="nowhere")
    orch.tick()
    assert orchestrator.load("mw", "svc_a")["node"] == "review"

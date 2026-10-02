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
"""


class FakeServer:
    def __init__(self, company):
        self._company = company
        self.sessions: dict[str, dict] = {}
        self.directives: dict[str, dict] = {}
        self.woken: list[str] = []
        self.is_stopped = False
        self.n = 0

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

    def wake(self, session):
        self.woken.append(session)
        return True

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

    def fake_gate(gate, div, wt, feature, node):
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
    assert inst()["status"] == "escalated"


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

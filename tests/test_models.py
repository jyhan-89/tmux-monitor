import copy
from pathlib import Path

import pytest
import yaml

import models

SAMPLE = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"


def sample() -> dict[str, dict]:
    return {k: yaml.safe_load((SAMPLE / f"{k}.yaml").read_text()) for k in models.PARSERS}


def dump(data: dict[str, dict]) -> dict[str, str]:
    return {k: yaml.safe_dump(v, allow_unicode=True) for k, v in data.items()}


def rules_of(data: dict[str, dict]) -> set[str]:
    with pytest.raises(models.DefinitionError) as e:
        models.parse_texts(dump(data))
    return {i.rule for i in e.value.issues}


def test_load_org():
    org = models.parse_org((SAMPLE / "org.yaml").read_text())
    mw = org.divisions["mw"]
    assert mw.profile == "adaptive"
    assert mw.depts["impl"].members.count == 2
    assert mw.depts["impl"].layers == ["skeleton", "proxy"]
    assert org.shared["ops"].always_on is True
    assert "Bash(directive:*)" in org.roles["impl"].allowed_tools


def test_load_process():
    proc = models.parse_process((SAMPLE / "process.yaml").read_text())
    t = proc.templates["feature_dev"]
    assert t.start == "design"
    assert t.nodes["implement"].retry == 2 and t.nodes["implement"].parallel
    assert t.nodes["analyze"].loop.max["review"] == 3
    assert t.nodes["escalate"].type == "approval"
    assert t.limits["node_timeout_h"] == 24


def test_load_documents_and_all():
    company = models.load_dir(SAMPLE)
    assert company.documents.directives["std_check"].to == ["feature_design", "analysis"]
    owners = {d.pattern: d.owner for d in company.documents.documents}
    assert owners["coord/review/*.md"] == "reviewer"
    gate = company.process.templates["feature_dev"].nodes["implement"].gate
    assert models.resolve_gate(gate, company.org.divisions["mw"]) == "gates/adaptive/unit_test.sh"


def nodes(d):
    return d["process"]["templates"]["feature_dev"]["nodes"]


def mw(d):
    return d["org"]["divisions"]["mw"]


def _set(path, value):
    def apply(d):
        cur = d
        for k in path[:-1]:
            cur = cur[k]
        if value is DELETE:
            del cur[path[-1]]
        else:
            cur[path[-1]] = value
    return apply


DELETE = object()

CASES = {
    "version": _set(["org", "version"], 2),
    "type": _set(["org", "roles", "impl", "allowed_tools"], {"a": 1}),
    "ident": _set(["org", "divisions", "mw", "depts", "impl", "layers"], ["Skeleton"]),
    "member_role": _set(["org", "divisions", "mw", "depts", "quality", "members"], {"model": "sonnet"}),
    "count": _set(["org", "divisions", "mw", "depts", "impl", "members", "count"], 0),
    "profile_ref": _set(["org", "divisions", "mw", "profile"], "classic"),
    "dept_members": _set(["org", "divisions", "mw", "depts", "quality"], {"rules": "x.md"}),
    "role_ref": _set(["org", "divisions", "mw", "depts", "verify", "members", "role"], "hil"),
    "allowed_tools": _set(["org", "roles", "sil", "allowed_tools"], []),
    "start": _set(["process", "templates", "feature_dev", "start"], "plan"),
    "node_type": lambda d: nodes(d)["done"].update(type="finish"),
    "approval_options": lambda d: nodes(d)["escalate"].update(options=["retry_all"]),
    "escalate_exit": lambda d: nodes(d)["escalate"].update(options=["override"]),
    "node_role": lambda d: nodes(d)["review"].pop("role"),
    "next": lambda d: nodes(d)["sil2"].pop("next"),
    "node_ref": lambda d: nodes(d)["sil1"].update(next="sil3"),
    "on_fail": lambda d: nodes(d)["review"].pop("on_fail"),
    "retry": lambda d: nodes(d)["implement"].update(retry=-1),
    "loop_max": lambda d: nodes(d)["analyze"]["loop"].pop("max"),
    "loop_on_exceed": lambda d: nodes(d)["analyze"]["loop"].pop("on_exceed"),
    "loop_max_missing": lambda d: nodes(d)["analyze"]["loop"]["max"].pop("sil1"),
    "unreachable": lambda d: nodes(d).update(orphan={"role": "sil", "next": "done", "on_fail": "analyze"}),
    "terminal": lambda d: (nodes(d)["done"].update(type="approval", options=["redesign"])),
    "yaml": None,
    "owner": lambda d: d["documents"]["documents"]["coord/spec.md"].pop("owner"),
    "directive_from": lambda d: d["documents"]["directives"]["task"].pop("from"),
    "directive_to": lambda d: d["documents"]["directives"]["task"].pop("to"),
    "template_ref": lambda d: mw(d).update(template="hotfix"),
    "node_role_ref": lambda d: (mw(d)["depts"].pop("verify")),
    "parallel_layers": lambda d: mw(d)["depts"]["impl"].pop("layers"),
    "owner_ref": lambda d: d["documents"]["documents"]["coord/spec.md"].update(owner="cto"),
    "directive_role_ref": lambda d: d["documents"]["directives"]["task"].update(to="pm"),
}


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule(rule):
    if rule == "yaml":
        texts = dump(sample())
        texts["org"] = "version: 1\nshared: [unclosed"
        with pytest.raises(models.DefinitionError) as e:
            models.parse_texts(texts)
        assert "yaml" in {i.rule for i in e.value.issues}
        return
    data = copy.deepcopy(sample())
    CASES[rule](data)
    assert rule in rules_of(data)


def test_issue_has_location():
    data = sample()
    nodes(data)["review"].pop("on_fail")
    with pytest.raises(models.DefinitionError) as e:
        models.parse_texts(dump(data))
    issue = next(i for i in e.value.issues if i.rule == "on_fail")
    assert issue.where == "process.templates.feature_dev.nodes.review.on_fail"
    assert issue.as_dict()["message"]


def test_every_role_has_prompt_template():
    org = models.parse_org((SAMPLE / "org.yaml").read_text())
    prompts = SAMPLE.parent.parent
    assert (prompts / "prompts" / "common.md").exists()
    for role in org.roles.values():
        assert (prompts / role.prompt).exists(), role.prompt
        text = (prompts / role.prompt).read_text()
        for section in ("## 책임", "## 수정 가능", "## 산출물", "## 금지"):
            assert section in text, (role.id, section)

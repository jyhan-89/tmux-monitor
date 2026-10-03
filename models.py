import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VERSION = 1
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
APPROVAL_OPTIONS = {"redesign", "drop", "override"}
SPECIAL_SENDERS = {"orchestrator", "any"}
WARN_RULES = {"unreachable"}


@dataclass
class Issue:
    rule: str
    where: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "where": self.where, "message": self.message}


class DefinitionError(Exception):
    def __init__(self, issues: list[Issue]):
        super().__init__("; ".join(f"{i.rule} @ {i.where}: {i.message}" for i in issues))
        self.issues = issues


@dataclass
class Member:
    role: str
    model: str = ""
    count: int = 1
    scope: str = ""
    always_on: bool = False


@dataclass
class Dept:
    lead: Member | None = None
    members: Member | None = None
    layers: list[str] = field(default_factory=list)
    rules: str = ""
    folder: str = ""

    def all_members(self) -> list[Member]:
        return [m for m in (self.lead, self.members) if m]


@dataclass
class Division:
    id: str
    name: str
    profile: str
    repo: str = ""
    template: str = ""
    folder: str = ""
    depts: dict[str, Dept] = field(default_factory=dict)

    def roles(self) -> set[str]:
        return {m.role for d in self.depts.values() for m in d.all_members()}


@dataclass
class Profile:
    id: str
    standards: list[str] = field(default_factory=list)
    gates_dir: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Role:
    id: str
    prompt: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    can_edit: list[str] = field(default_factory=list)
    cannot_edit: list[str] = field(default_factory=list)


@dataclass
class Org:
    version: int
    shared: dict[str, Member]
    divisions: dict[str, Division]
    profiles: dict[str, Profile]
    roles: dict[str, Role]

    def shared_roles(self) -> set[str]:
        return {m.role for m in self.shared.values()}


@dataclass
class Loop:
    counter_by: str = "source_node"
    max: dict[str, int] = field(default_factory=dict)
    on_exceed: str = ""


@dataclass
class Node:
    id: str
    type: str = "work"
    role: str = ""
    gate: str = ""
    pre_gate: str = ""
    next: str = ""
    on_fail: str = ""
    retry: int = 0
    parallel: bool = False
    requires_approval: bool = False
    options: list[str] = field(default_factory=list)
    output: str = ""
    loop: Loop | None = None


@dataclass
class Template:
    id: str
    start: str
    nodes: dict[str, Node]
    limits: dict[str, float] = field(default_factory=dict)


@dataclass
class Process:
    version: int
    templates: dict[str, Template]


@dataclass
class DocRule:
    pattern: str
    owner: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DirectiveType:
    id: str
    sender: str
    to: list[str]


@dataclass
class Documents:
    documents: list[DocRule]
    directives: dict[str, DirectiveType]


class _Reader:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def add(self, rule: str, where: str, message: str) -> None:
        self.issues.append(Issue(rule, where, message))

    def mapping(self, value: Any, where: str) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.add("type", where, "매핑이어야 합니다")
            return {}
        return value

    def str_list(self, value: Any, where: str) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.add("type", where, "문자열 목록이어야 합니다")
            return []
        return list(value)

    def integer(self, value: Any, where: str, default: int) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            self.add("type", where, "정수여야 합니다")
            return default
        return value

    def ident(self, value: str, where: str) -> None:
        if not IDENT.match(value):
            self.add("ident", where, f"'{value}'는 영소문자·숫자·밑줄로 된 이름이어야 합니다 (세션 이름에 쓰임)")


def _parse(text: str, where: str, r: _Reader) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        r.add("yaml", where, str(e).splitlines()[0])
        return {}
    data = r.mapping(data, where)
    if data and data.get("version") != VERSION:
        r.add("version", f"{where}.version", f"version {VERSION}만 지원합니다")
    return data


def _finish(r: _Reader, value):
    if any(i.rule not in WARN_RULES for i in r.issues):
        raise DefinitionError(r.issues)
    if value is not None:
        value.warnings = [i for i in r.issues if i.rule in WARN_RULES]
    return value


def _member(raw: Any, where: str, r: _Reader) -> Member | None:
    m = r.mapping(raw, where)
    if not m:
        return None
    role = m.get("role")
    if not isinstance(role, str) or not role:
        r.add("member_role", f"{where}.role", "role이 필요합니다")
        role = ""
    count = r.integer(m.get("count"), f"{where}.count", 1)
    if count < 1:
        r.add("count", f"{where}.count", "count는 1 이상이어야 합니다")
    return Member(role=role, model=str(m.get("model") or ""), count=count, scope=str(m.get("scope") or ""),
                  always_on=bool(m.get("always_on")))


def parse_org(text: str) -> Org:
    r = _Reader()
    data = _parse(text, "org", r)
    shared = {}
    for key, raw in r.mapping(data.get("shared"), "org.shared").items():
        r.ident(key, f"org.shared.{key}")
        if m := _member(raw, f"org.shared.{key}", r):
            shared[key] = m
    profiles = {}
    for key, raw in r.mapping(data.get("profiles"), "org.profiles").items():
        p = dict(r.mapping(raw, f"org.profiles.{key}"))
        profiles[key] = Profile(id=key, standards=r.str_list(p.pop("standards", None), f"org.profiles.{key}.standards"),
                                gates_dir=str(p.pop("gates_dir", "") or ""), extra=p)
    roles = {}
    for key, raw in r.mapping(data.get("roles"), "org.roles").items():
        w = f"org.roles.{key}"
        r.ident(key, w)
        m = r.mapping(raw, w)
        roles[key] = Role(id=key, prompt=str(m.get("prompt") or ""),
                          allowed_tools=r.str_list(m.get("allowed_tools"), f"{w}.allowed_tools"),
                          can_edit=r.str_list(m.get("can_edit"), f"{w}.can_edit"),
                          cannot_edit=r.str_list(m.get("cannot_edit"), f"{w}.cannot_edit"))
    divisions = {}
    for key, raw in r.mapping(data.get("divisions"), "org.divisions").items():
        w = f"org.divisions.{key}"
        r.ident(key, w)
        d = r.mapping(raw, w)
        depts = {}
        for dkey, draw in r.mapping(d.get("depts"), f"{w}.depts").items():
            dw = f"{w}.depts.{dkey}"
            r.ident(dkey, dw)
            dd = r.mapping(draw, dw)
            dept = Dept(lead=_member(dd.get("lead"), f"{dw}.lead", r), members=_member(dd.get("members"), f"{dw}.members", r),
                        layers=r.str_list(dd.get("layers"), f"{dw}.layers"), rules=str(dd.get("rules") or ""),
                        folder=str(dd.get("folder") or ""))
            for layer in dept.layers:
                r.ident(layer, f"{dw}.layers")
            depts[dkey] = dept
        divisions[key] = Division(id=key, name=str(d.get("name") or key), profile=str(d.get("profile") or ""),
                                  repo=str(d.get("repo") or ""), template=str(d.get("template") or ""),
                                  folder=str(d.get("folder") or ""), depts=depts)
    org = Org(version=VERSION, shared=shared, divisions=divisions, profiles=profiles, roles=roles)
    _check_org(org, r)
    return _finish(r, org)


def _check_org(org: Org, r: _Reader) -> None:
    for key, div in org.divisions.items():
        if div.profile not in org.profiles:
            r.add("profile_ref", f"org.divisions.{key}.profile", f"profile '{div.profile}'이(가) profiles에 없습니다")
        for dkey, dept in div.depts.items():
            if not dept.all_members():
                r.add("dept_members", f"org.divisions.{key}.depts.{dkey}", "lead 또는 members가 필요합니다")
            for slot, m in (("lead", dept.lead), ("members", dept.members)):
                if m and m.role and m.role not in org.roles:
                    r.add("role_ref", f"org.divisions.{key}.depts.{dkey}.{slot}.role", f"role '{m.role}'이(가) roles에 없습니다")
    for key, m in org.shared.items():
        if m.role and m.role not in org.roles:
            r.add("role_ref", f"org.shared.{key}.role", f"role '{m.role}'이(가) roles에 없습니다")
    for key, role in org.roles.items():
        if not role.allowed_tools:
            r.add("allowed_tools", f"org.roles.{key}.allowed_tools", "allowed_tools가 비어 있습니다")


def parse_process(text: str) -> Process:
    r = _Reader()
    data = _parse(text, "process", r)
    templates = {}
    for tkey, traw in r.mapping(data.get("templates"), "process.templates").items():
        tw = f"process.templates.{tkey}"
        t = r.mapping(traw, tw)
        nodes = {}
        for nkey, nraw in r.mapping(t.get("nodes"), f"{tw}.nodes").items():
            nw = f"{tw}.nodes.{nkey}"
            n = r.mapping(nraw, nw)
            loop = None
            if "loop" in n:
                lp = r.mapping(n.get("loop"), f"{nw}.loop")
                mx = {}
                for k, v in r.mapping(lp.get("max"), f"{nw}.loop.max").items():
                    mx[k] = r.integer(v, f"{nw}.loop.max.{k}", 0)
                loop = Loop(counter_by=str(lp.get("counter_by") or "source_node"), max=mx, on_exceed=str(lp.get("on_exceed") or ""))
            nodes[nkey] = Node(id=nkey, type=str(n.get("type") or "work"), role=str(n.get("role") or ""),
                               gate=str(n.get("gate") or ""), pre_gate=str(n.get("pre_gate") or ""),
                               next=str(n.get("next") or ""), on_fail=str(n.get("on_fail") or ""),
                               retry=r.integer(n.get("retry"), f"{nw}.retry", 0), parallel=bool(n.get("parallel")),
                               requires_approval=bool(n.get("requires_approval")),
                               options=r.str_list(n.get("options"), f"{nw}.options"), output=str(n.get("output") or ""),
                               loop=loop)
        limits = {k: v for k, v in r.mapping(t.get("limits"), f"{tw}.limits").items() if isinstance(v, (int, float))}
        templates[tkey] = Template(id=tkey, start=str(t.get("start") or ""), nodes=nodes, limits=limits)
    proc = Process(version=VERSION, templates=templates)
    for t in templates.values():
        _check_template(t, r)
    return _finish(r, proc)


def _edges(t: Template, n: Node) -> list[str]:
    if n.type == "approval":
        out = [o for o in n.options if o in t.nodes]
        if "redesign" in n.options:
            out.append(t.start)
        if "drop" in n.options:
            out += [k for k, v in t.nodes.items() if v.type == "terminal"]
        return out
    out = [x for x in (n.next, n.on_fail) if x]
    if n.loop and n.loop.on_exceed:
        out.append(n.loop.on_exceed)
    return out


def _check_template(t: Template, r: _Reader) -> None:
    tw = f"process.templates.{t.id}"
    if t.start not in t.nodes:
        r.add("start", f"{tw}.start", f"start '{t.start}' 노드가 없습니다")
    for key, n in t.nodes.items():
        nw = f"{tw}.nodes.{key}"
        if n.type not in ("work", "approval", "terminal"):
            r.add("node_type", f"{nw}.type", f"알 수 없는 type '{n.type}'")
            continue
        if n.type == "terminal":
            continue
        if n.type == "approval":
            if not n.options:
                r.add("approval_options", f"{nw}.options", "결재 노드에는 options가 필요합니다")
            bad = [o for o in n.options if o not in APPROVAL_OPTIONS and o not in t.nodes]
            if bad:
                r.add("approval_options", f"{nw}.options", f"알 수 없는 선택지 {bad}")
            if n.options and not ({"redesign", "drop"} & set(n.options) or any(o in t.nodes for o in n.options)):
                r.add("escalate_exit", f"{nw}.options", "done 또는 재진입 노드로 가는 선택지가 없습니다")
            continue
        if not n.role:
            r.add("node_role", f"{nw}.role", "role이 필요합니다")
        if not n.next:
            r.add("next", f"{nw}.next", "next 또는 type: terminal이 필요합니다")
        elif n.next not in t.nodes:
            r.add("node_ref", f"{nw}.next", f"노드 '{n.next}'이(가) 없습니다")
        if not n.on_fail:
            r.add("on_fail", f"{nw}.on_fail", "on_fail이 필요합니다")
        elif n.on_fail not in t.nodes:
            r.add("node_ref", f"{nw}.on_fail", f"노드 '{n.on_fail}'이(가) 없습니다")
        if n.retry < 0:
            r.add("retry", f"{nw}.retry", "retry는 0 이상이어야 합니다")
        if n.loop:
            if not n.loop.max:
                r.add("loop_max", f"{nw}.loop.max", "loop에는 max가 필요합니다")
            if not n.loop.on_exceed:
                r.add("loop_on_exceed", f"{nw}.loop.on_exceed", "loop에는 on_exceed가 필요합니다")
            elif n.loop.on_exceed not in t.nodes:
                r.add("node_ref", f"{nw}.loop.on_exceed", f"노드 '{n.loop.on_exceed}'이(가) 없습니다")
            for k, v in n.loop.max.items():
                if k not in t.nodes:
                    r.add("node_ref", f"{nw}.loop.max.{k}", f"노드 '{k}'이(가) 없습니다")
                if v < 1:
                    r.add("loop_max", f"{nw}.loop.max.{k}", "max는 1 이상이어야 합니다")
    for key, n in t.nodes.items():
        target = t.nodes.get(n.on_fail)
        if n.type == "work" and target and target.loop and key not in target.loop.max:
            r.add("loop_max_missing", f"{tw}.nodes.{n.on_fail}.loop.max",
                  f"on_fail로 '{n.on_fail}'에 오는 노드 '{key}'의 상한이 없습니다")
    if t.start in t.nodes:
        seen, stack = set(), [t.start]
        while stack:
            k = stack.pop()
            if k in seen or k not in t.nodes:
                continue
            seen.add(k)
            stack += _edges(t, t.nodes[k])
        for key in t.nodes:
            if key not in seen:
                r.add("unreachable", f"{tw}.nodes.{key}", f"start에서 '{key}'에 도달할 수 없습니다")
    if not any(n.type == "terminal" for n in t.nodes.values()):
        r.add("terminal", f"{tw}.nodes", "type: terminal 노드가 없습니다")


def parse_documents(text: str) -> Documents:
    r = _Reader()
    data = _parse(text, "documents", r)
    docs = []
    for pattern, raw in r.mapping(data.get("documents"), "documents.documents").items():
        m = dict(r.mapping(raw, f"documents.documents.{pattern}"))
        owner = m.pop("owner", None)
        if not isinstance(owner, str) or not owner:
            r.add("owner", f"documents.documents.{pattern}.owner", "owner가 필요합니다")
            owner = ""
        docs.append(DocRule(pattern=str(pattern), owner=owner, extra=m))
    directives = {}
    for key, raw in r.mapping(data.get("directives"), "documents.directives").items():
        w = f"documents.directives.{key}"
        r.ident(key, w)
        m = r.mapping(raw, w)
        sender = m.get("from")
        if not isinstance(sender, str) or not sender:
            r.add("directive_from", f"{w}.from", "from이 필요합니다")
            sender = ""
        to = r.str_list(m.get("to"), f"{w}.to")
        if not to:
            r.add("directive_to", f"{w}.to", "to가 필요합니다")
        directives[key] = DirectiveType(id=key, sender=sender, to=to)
    return _finish(r, Documents(documents=docs, directives=directives))


def check_all(org: Org, process: Process, documents: Documents) -> None:
    r = _Reader()
    all_roles = set(org.roles)
    for key, div in org.divisions.items():
        w = f"org.divisions.{key}"
        tkey = div.template or (next(iter(process.templates)) if len(process.templates) == 1 else "")
        if not div.template and not process.templates:
            continue
        t = process.templates.get(tkey)
        if not t:
            r.add("template_ref", f"{w}.template", f"template '{div.template}'이(가) process에 없습니다 (템플릿이 여럿이면 지정 필요)")
            continue
        available = div.roles() | org.shared_roles()
        for nkey, n in t.nodes.items():
            if n.type == "work" and n.role and n.role not in available:
                r.add("node_role_ref", f"process.templates.{tkey}.nodes.{nkey}.role",
                      f"본부 '{key}'와 shared 어디에도 role '{n.role}'이(가) 없습니다")
            if n.parallel and not any(n.role in {m.role for m in d.all_members()} and d.layers for d in div.depts.values()):
                r.add("parallel_layers", f"process.templates.{tkey}.nodes.{nkey}.parallel",
                      f"본부 '{key}'에서 role '{n.role}' 부서에 layers가 없습니다")
    for d in documents.documents:
        if d.owner and d.owner not in all_roles:
            r.add("owner_ref", f"documents.documents.{d.pattern}.owner", f"role '{d.owner}'이(가) roles에 없습니다")
    for key, dt in documents.directives.items():
        if dt.sender and dt.sender not in all_roles | SPECIAL_SENDERS:
            r.add("directive_role_ref", f"documents.directives.{key}.from", f"role '{dt.sender}'이(가) roles에 없습니다")
        for to in dt.to:
            if to not in all_roles | SPECIAL_SENDERS:
                r.add("directive_role_ref", f"documents.directives.{key}.to", f"role '{to}'이(가) roles에 없습니다")
    _finish(r, None)


def resolve_gate(gate: str, division: Division) -> str:
    return gate.replace("{profile}", division.profile)


@dataclass
class Company:
    org: Org
    process: Process
    documents: Documents


PARSERS = {"org": parse_org, "process": parse_process, "documents": parse_documents}


def load_dir(folder: Path) -> Company:
    texts = {k: (folder / f"{k}.yaml").read_text() for k in PARSERS}
    return parse_texts(texts)


def parse_texts(texts: dict[str, str]) -> Company:
    issues: list[Issue] = []
    parsed: dict[str, Any] = {}
    for key, fn in PARSERS.items():
        try:
            parsed[key] = fn(texts[key])
        except DefinitionError as e:
            issues += e.issues
    if issues:
        raise DefinitionError(issues)
    company = Company(**parsed)
    check_all(company.org, company.process, company.documents)
    company.warnings = [w for v in parsed.values() for w in getattr(v, "warnings", [])]
    return company

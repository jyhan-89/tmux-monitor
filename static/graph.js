const graph = {
  view: 'org',
  model: null,
  summary: null,
  insts: [],
  division: null,
  instance: null,
  selected: null,
};

const NW = 112;
const NH = 30;
const GAP = 8;
const PAD = 10;
const ROW = 64;
const STATE_TEXT = { working: '작업 중', waiting: '확인 필요', idle: '대기', shell: '셸', running: '실행 중' };
const IDENT = /^[a-z][a-z0-9_]*$/;
const DEFAULT_TOOLS = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'Bash(git log:*)', 'Bash(git diff:*)', 'Bash(git show:*)',
  'Bash(git status:*)', 'Bash(git add:*)', 'Bash(git commit:*)', 'Bash(directive:*)'];

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const listText = (v) => (Array.isArray(v) ? v.join('\n') : '');
const textList = (v) => v.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

function sessionInfo(name) {
  return sessions.find((s) => s.name === name) || null;
}

function org() {
  return graph.model.org;
}

function templates() {
  return graph.model.process?.templates || {};
}

function memberSlots(dept, slot, m) {
  if (slot === 'members' && dept.layers?.length) return dept.layers;
  const count = Math.max(1, +m.count || 1);
  return count > 1 ? Array.from({ length: count }, (_, i) => String(i + 1)) : [null];
}

function roleNodes(div, dept, slot, m) {
  return memberSlots(dept, slot, m).map((suffix) => {
    const name = [div, dept.key, m.role, suffix].filter(Boolean).join('-');
    const s = sessionInfo(name);
    return { kind: 'role', div, dept: dept.key, slot, role: m.role, suffix, name, state: s?.state || 'none', model: m.model };
  });
}

function nodeSvg(n, x, y, w = NW) {
  const label = n.suffix ? `${n.suffix} · ${n.role}` : n.role;
  const sel = graph.selected?.kind === 'role' && graph.selected.name === n.name ? ' sel' : '';
  return `<g class="gnode st-${esc(n.state)}${sel}" data-i="${n.i}" transform="translate(${x},${y})">
    <title>${esc(n.name)} · ${esc(STATE_TEXT[n.state] || '세션 없음')}${n.model ? ` · ${esc(n.model)}` : ''}</title>
    <rect width="${w}" height="${NH}" rx="6"></rect><circle cx="10" cy="${NH / 2}" r="4"></circle>
    <text x="20" y="${NH / 2 + 4}">${esc(label.length > 15 ? `${label.slice(0, 14)}…` : label)}</text></g>`;
}

function renderOrg() {
  const o = org();
  const nodes = [];
  const parts = [];
  const divs = Object.entries(o.divisions || {});
  const first = divs[0]?.[0] || 'x';
  const shared = Object.entries(o.shared || {}).map(([key, m]) => {
    const real = sessions.find((s) => s.meta?.role === m.role && s.meta?.dept === 'shared');
    return { kind: 'role', sharedKey: key, div: first, dept: 'shared', slot: 'shared', role: m.role, suffix: null,
      name: real?.name || `${first}-shared-${m.role}`, state: real?.state || 'none', model: m.model };
  });
  const divW = 2 * NW + GAP + 4 * PAD;
  const totalW = Math.max(divs.length, 1) * (divW + GAP) - GAP;
  const cols = Math.max(2, Math.floor((totalW - 2 * PAD + GAP) / (NW + GAP)));
  let y = 8;
  const rows = Math.max(1, Math.ceil(shared.length / cols));
  const sh = 26 + rows * (NH + GAP) + PAD;
  const selShared = graph.selected?.kind === 'shared' ? ' sel' : '';
  parts.push(`<g transform="translate(8,${y})"><rect class="gbox shared${selShared}" width="${totalW}" height="${sh}" rx="8" data-act="shared"></rect>
    <text class="gtitle click" x="${PAD}" y="18" data-act="shared">전사 공통 ✎</text>`);
  shared.forEach((n, i) => {
    n.i = nodes.push(n) - 1;
    parts.push(nodeSvg(n, PAD + (i % cols) * (NW + GAP), 26 + Math.floor(i / cols) * (NH + GAP)));
  });
  if (!shared.length) parts.push(`<text class="gsub" x="${PAD}" y="44">공통 역할 없음</text>`);
  parts.push('</g>');
  y += sh + 12;
  let maxH = 0;
  divs.forEach(([divKey, div], di) => {
    const x = 8 + di * (divW + GAP);
    const inner = [];
    let dy = 30;
    for (const [deptKey, dept] of Object.entries(div.depts || {})) {
      const d = { ...dept, key: deptKey };
      const items = ['lead', 'members'].filter((slot) => dept[slot]).flatMap((slot) => roleNodes(divKey, d, slot, dept[slot]));
      const r = Math.max(1, Math.ceil(items.length / 2));
      const h = 24 + r * (NH + GAP) + 4;
      const sel = graph.selected?.kind === 'dept' && graph.selected.div === divKey && graph.selected.dept === deptKey ? ' sel' : '';
      inner.push(`<g transform="translate(${PAD},${dy})"><rect class="gbox dept${sel}" width="${divW - 2 * PAD}" height="${h}" rx="6" data-act="dept" data-div="${esc(divKey)}" data-dept="${esc(deptKey)}"></rect>
        <text class="gsub click" x="${PAD}" y="16" data-act="dept" data-div="${esc(divKey)}" data-dept="${esc(deptKey)}">${esc(deptKey)}${dept.layers?.length ? ` · ${esc(dept.layers.join(', '))}` : ''} ✎</text>`);
      items.forEach((n, i) => {
        n.i = nodes.push(n) - 1;
        inner.push(nodeSvg(n, PAD + (i % 2) * (NW + GAP), 22 + Math.floor(i / 2) * (NH + GAP)));
      });
      inner.push('</g>');
      dy += h + GAP;
    }
    if (!Object.keys(div.depts || {}).length) {
      inner.push(`<text class="gsub" x="${PAD}" y="${dy + 14}">부서 없음 · 본부 이름을 눌러 추가</text>`);
      dy += 26;
    }
    const h = dy + 4;
    maxH = Math.max(maxH, h);
    const sel = graph.selected?.kind === 'div' && graph.selected.div === divKey ? ' sel' : '';
    parts.push(`<g transform="translate(${x},${y})"><rect class="gbox div${sel}" width="${divW}" height="${h}" rx="8" data-act="div" data-div="${esc(divKey)}"></rect>
      <text class="gtitle click" x="${PAD}" y="20" data-act="div" data-div="${esc(divKey)}">${esc(divKey)} · ${esc(div.name || '')} <tspan class="gdim">(${esc(div.profile || '')})</tspan> ✎</text>${inner.join('')}</g>`);
  });
  if (!divs.length) {
    parts.push(`<text class="gsub" x="16" y="${y + 20}">본부가 없습니다. 위의 ＋ 본부로 추가하세요</text>`);
    maxH = 40;
  }
  const width = 16 + Math.max(divs.length, 1) * (divW + GAP);
  return { svg: `<svg width="${width}" height="${y + maxH + 16}" xmlns="http://www.w3.org/2000/svg">${parts.join('')}</svg>`, nodes };
}

function templateKeyOf(divKey) {
  const div = org()?.divisions?.[divKey];
  const keys = Object.keys(templates());
  if (div?.template && templates()[div.template]) return div.template;
  return keys[0] || null;
}

function renderProcess() {
  const key = templateKeyOf(graph.division);
  if (!key) return { svg: '<p class="gempty">프로세스 템플릿이 없습니다. 위의 ＋ 템플릿으로 만드세요</p>', nodes: [] };
  const t = templates()[key];
  const ns = t.nodes || {};
  const inst = graph.insts.find((i) => `${i.division}/${i.feature}` === graph.instance);
  const main = [];
  for (let k = t.start; k && ns[k] && !main.includes(k); k = ns[k].next) {
    main.push(k);
    if (ns[k].type === 'terminal') break;
  }
  const rest = Object.keys(ns).filter((k) => !main.includes(k));
  const left = rest.filter((k) => ns[k].type !== 'approval' && ns[k].type !== 'terminal');
  const right = rest.filter((k) => ns[k].type === 'approval' || ns[k].type === 'terminal');
  const W = 150;
  const cx = 230;
  const lx = 20;
  const rx = 440;
  const pos = {};
  main.forEach((k, i) => { pos[k] = { x: cx, y: 20 + i * ROW }; });
  const midY = 20 + Math.max(0, Math.floor((main.length - 1) / 2)) * ROW;
  left.forEach((k, i) => { pos[k] = { x: lx, y: midY + i * ROW }; });
  right.forEach((k, i) => { pos[k] = { x: rx, y: midY + ROW + i * ROW }; });
  const edges = [];
  const arrow = (from, to, cls, label = '') => {
    const a = pos[from];
    const b = pos[to];
    if (!a || !b) return;
    let d;
    if (a.x === b.x) {
      d = b.y > a.y ? `M${a.x + W / 2},${a.y + NH} L${b.x + W / 2},${b.y}`
        : `M${a.x},${a.y + NH / 2} C${a.x - 40},${a.y + NH / 2} ${b.x - 40},${b.y + NH / 2} ${b.x},${b.y + NH / 2}`;
    } else if (b.x < a.x) {
      d = `M${a.x},${a.y + NH / 2} C${a.x - 30},${a.y + NH / 2} ${b.x + W + 30},${b.y + NH / 2} ${b.x + W},${b.y + NH / 2}`;
    } else {
      d = `M${a.x + W},${a.y + NH / 2} C${a.x + W + 30},${a.y + NH / 2} ${b.x - 30},${b.y + NH / 2} ${b.x},${b.y + NH / 2}`;
    }
    edges.push(`<path class="gedge ${cls}" d="${d}" marker-end="url(#arr-${cls})"></path>`);
    if (label) edges.push(`<text class="glabel ${cls}" x="${(a.x + b.x + W) / 2}" y="${(a.y + b.y + NH) / 2}">${esc(label)}</text>`);
  };
  for (const [k, n] of Object.entries(ns)) {
    if (n.next) arrow(k, n.next, left.includes(k) ? 'loop' : 'next');
    if (n.on_fail) arrow(k, n.on_fail, ns[n.on_fail]?.type === 'approval' ? 'esc' : 'fail');
    if (n.loop?.on_exceed) arrow(k, n.loop.on_exceed, 'esc', '상한 초과');
    if (n.type === 'approval' && (n.options || []).includes('redesign')) arrow(k, t.start, 'loop', '재설계');
  }
  const nodes = [];
  const boxes = Object.entries(pos).map(([k, p]) => {
    const n = ns[k];
    const item = { kind: 'node', template: key, key: k };
    item.i = nodes.push(item) - 1;
    const cur = inst?.node === k ? ' cur' : '';
    const sel = graph.selected?.kind === 'node' && graph.selected.key === k ? ' sel' : '';
    const type = n.type === 'approval' ? 'approval' : n.type === 'terminal' ? 'terminal' : 'work';
    const sub = n.type === 'approval' ? '결재' : n.type === 'terminal' ? '종료' : `${n.role || ''}${n.parallel ? ' ×계층' : ''}${n.requires_approval ? ' · 결재' : ''}`;
    let counter = '';
    if (n.loop?.max) {
      counter = Object.entries(n.loop.max).map(([src, mx]) => (inst ? `${src} ${inst.counters?.[src] || 0}/${mx}` : `${src} ≤${mx}`)).join(' · ');
    }
    return `<g class="pnode ${type}${cur}${sel}" data-i="${item.i}" transform="translate(${p.x},${p.y})">
      <title>${esc(k)}${n.gate ? ` · gate ${esc(n.gate)}` : ''}</title>
      <rect width="${W}" height="${NH}" rx="${type === 'work' ? 6 : 15}"></rect>
      <text x="10" y="13" class="pk">${esc(k)}${cur ? ' ●' : ''}</text><text x="10" y="25" class="ps">${esc(sub)}</text>
      ${counter ? `<text x="0" y="${NH + 12}" class="pc">${esc(counter)}</text>` : ''}</g>`;
  });
  const h = 40 + Math.max(main.length, midY / ROW + left.length + 1, midY / ROW + right.length + 2) * ROW;
  const defs = ['next', 'fail', 'loop', 'esc'].map((c) => `<marker id="arr-${c}" class="gm ${c}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"></path></marker>`).join('');
  return { svg: `<svg width="${rx + W + 20}" height="${h}" xmlns="http://www.w3.org/2000/svg"><defs>${defs}</defs>${edges.join('')}${boxes.join('')}</svg>`, nodes };
}

function graphLegend() {
  if (graph.view === 'org') {
    return ['working', 'waiting', 'idle', 'none'].map((s) => `<span class="lg st-${s}"><i></i>${STATE_TEXT[s] || '세션 없음'}</span>`).join('');
  }
  return '<span class="lg next"><i></i>통과</span><span class="lg fail"><i></i>실패</span><span class="lg loop"><i></i>되돌아감</span><span class="lg esc"><i></i>결재</span>';
}

function renderActions() {
  const box = $('gactions');
  box.innerHTML = '';
  const add = (label, sel) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = () => selectGraphNode(sel);
    box.appendChild(b);
  };
  if (!graph.model?.org) return;
  if (graph.view === 'org') {
    add('＋ 본부', { kind: 'newdiv' });
  } else {
    if (templateKeyOf(graph.division)) {
      add('＋ 단계', { kind: 'newnode', template: templateKeyOf(graph.division) });
      add('템플릿 설정', { kind: 'template', template: templateKeyOf(graph.division) });
    }
    add('＋ 템플릿', { kind: 'newtemplate' });
  }
}

function renderOrchStatus() {
  const el = $('gorch');
  const o = graph.summary?.orchestrator;
  if (!graph.model?.org || !o) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.className = o.alive ? 'on' : 'off';
  el.textContent = o.alive ? '● 오케스트레이터 실행 중' : '○ 오케스트레이터 꺼짐';
  el.title = o.alive ? '' : '자동 진행이 멈춰 있습니다. 서버 PC에서 systemctl --user start tmux-web-orchestrator (설치: install/ubuntu.sh --with-orchestrator)';
}

function renderEmpty() {
  $('gcanvas').innerHTML = `<div class="ginit">
    <h3>조직 정의가 없습니다</h3>
    <p>여러 Claude 세션을 본부·부서·역할과 프로세스에 따라 운영하려면 조직을 먼저 구성하세요.</p>
    <div class="opts"><button id="ginitex" class="primary">예시로 시작 (미들웨어 본부)</button><button id="ginitempty">빈 조직으로 시작</button></div>
    <p class="gdim">예시는 설계·구현·리뷰·표준 검사·SIL·통합으로 이루어진 본부 하나와 전체 프로세스입니다. 시작한 뒤 화면에서 고칠 수 있습니다.</p></div>`;
  const init = async (template) => {
    try {
      await api('POST', '/company/init', { template });
    } catch (e) {
      return toast(e.message, 4000);
    }
    companyReady = false;
    loadInboxBadge();
    toast('조직 정의를 만들었습니다');
    loadGraph();
  };
  $('ginitex').onclick = () => init('example');
  $('ginitempty').onclick = () => init('empty');
}

function renderGraph() {
  renderActions();
  renderOrchStatus();
  if (!graph.model?.org) {
    $('gdivsel').hidden = true;
    $('ginstsel').hidden = true;
    $('glegend').innerHTML = '';
    renderEmpty();
    return;
  }
  const divs = Object.keys(org().divisions || {});
  if (!divs.includes(graph.division)) graph.division = divs[0] || null;
  $('gdivsel').innerHTML = divs.map((d) => `<option value="${esc(d)}"${d === graph.division ? ' selected' : ''}>${esc(d)}</option>`).join('');
  const insts = graph.insts.filter((i) => i.division === graph.division);
  if (!insts.some((i) => `${i.division}/${i.feature}` === graph.instance)) graph.instance = insts[0] ? `${insts[0].division}/${insts[0].feature}` : '';
  $('ginstsel').innerHTML = '<option value="">인스턴스 없음</option>'
    + insts.map((i) => `<option value="${esc(`${i.division}/${i.feature}`)}"${`${i.division}/${i.feature}` === graph.instance ? ' selected' : ''}>${esc(i.feature)} · ${esc(i.node)}</option>`).join('');
  $('gdivsel').hidden = graph.view !== 'process' || !divs.length;
  $('ginstsel').hidden = graph.view !== 'process' || !divs.length;
  for (const b of document.querySelectorAll('#graph .gtab')) b.classList.toggle('on', b.dataset.view === graph.view);
  const { svg, nodes } = graph.view === 'org' ? renderOrg() : renderProcess();
  const box = $('gcanvas');
  box.innerHTML = svg;
  $('glegend').innerHTML = graphLegend();
  for (const el of box.querySelectorAll('[data-i]')) {
    el.addEventListener('click', (e) => { e.stopPropagation(); selectGraphNode(nodes[+el.dataset.i]); });
  }
  for (const el of box.querySelectorAll('[data-act]')) {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const a = el.dataset.act;
      if (a === 'shared') selectGraphNode({ kind: 'shared' });
      if (a === 'div') selectGraphNode({ kind: 'div', div: el.dataset.div });
      if (a === 'dept') selectGraphNode({ kind: 'dept', div: el.dataset.div, dept: el.dataset.dept });
    });
    if (el.dataset.act === 'div') {
      el.addEventListener('dblclick', () => {
        graph.division = el.dataset.div;
        graph.view = 'process';
        selectGraphNode(null);
      });
    }
  }
}

function field(label, id, value, type = 'text', extra = '') {
  if (type === 'textarea') return `<label>${esc(label)}<textarea id="${id}" rows="4"${extra}>${esc(value)}</textarea></label>`;
  if (type === 'checkbox') return `<label class="chk"><input id="${id}" type="checkbox"${value ? ' checked' : ''}${extra}> ${esc(label)}</label>`;
  return `<label>${esc(label)}<input id="${id}" type="${type}" value="${esc(value)}"${extra}></label>`;
}

function selectField(label, id, value, options, extra = '') {
  const opts = options.map((o) => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(t)}</option>`;
  }).join('');
  return `<label>${esc(label)}<select id="${id}"${extra}>${opts}</select></label>`;
}

function roleOptions(withNew = true) {
  const roles = Object.keys(org().roles || {}).sort();
  return [...roles.map((r) => [r, r]), ...(withNew ? [['__new__', '＋ 새 역할…']] : [])];
}

function roleFieldHtml(id, value) {
  return `${selectField('역할', id, value ?? Object.keys(org().roles || {})[0] ?? '__new__', roleOptions())}
    <label id="${id}-newbox" class="newrole" hidden>새 역할 이름 (영소문자·숫자·_)<input id="${id}-new" type="text"></label>`;
}

function bindRoleField(id) {
  const sel = $(id);
  const sync = () => { $(`${id}-newbox`).hidden = sel.value !== '__new__'; };
  sel.onchange = sync;
  sync();
}

function readRole(id, ops) {
  let role = $(id).value;
  if (role === '__new__') {
    role = $(`${id}-new`).value.trim();
    if (!IDENT.test(role)) throw new Error('역할 이름은 영소문자로 시작하는 영소문자·숫자·_로 입력하세요');
    if (!org().roles?.[role]) ops.push({ path: ['roles', role], value: { prompt: `prompts/${role}.md`, allowed_tools: DEFAULT_TOOLS, can_edit: [] } });
  }
  return role;
}

function need(id, label) {
  const v = $(id).value.trim();
  if (!IDENT.test(v)) throw new Error(`${label}은(는) 영소문자로 시작하는 영소문자·숫자·_로 입력하세요`);
  return v;
}

function panelHead(title, sub) {
  return `<div class="gph"><b>${esc(title)}</b><span>${esc(sub || '')}</span><button id="gpclose">×</button></div>`;
}

const PANELS = {
  role(sel) {
    const o = org();
    const role = o.roles?.[sel.role] || {};
    const member = sel.sharedKey ? o.shared[sel.sharedKey] : o.divisions[sel.div].depts[sel.dept][sel.slot];
    const s = sessionInfo(sel.name);
    const base = sel.sharedKey ? ['shared', sel.sharedKey] : ['divisions', sel.div, 'depts', sel.dept, sel.slot];
    return {
      html: `${panelHead(sel.role, sel.name)}
        <p class="gdim">${s ? `세션 ${esc(STATE_TEXT[s.state] || s.state || '')}${s.meta?.node ? ` · 노드 ${esc(s.meta.node)}` : ''}` : '세션 없음'}</p>
        ${s ? '<button id="gpopen" class="primary">세션 열기</button>' : ''}
        <h4>이 자리 (${esc(sel.sharedKey ? `공통 ${sel.sharedKey}` : `${sel.dept} ${sel.slot === 'lead' ? '책임자' : '구성원'}`)})</h4>
        ${field('모델', 'gf-model', member.model || '')}${field('인원 (count)', 'gf-count', member.count || 1, 'number', ' min="1"')}
        <h4>역할 ${esc(sel.role)} (같은 역할의 모든 자리에 적용)</h4>
        ${field('프롬프트', 'gf-prompt', role.prompt || '')}
        ${field('allowed_tools (한 줄에 하나)', 'gf-tools', listText(role.allowed_tools), 'textarea')}
        ${field('can_edit (한 줄에 하나)', 'gf-can', listText(role.can_edit), 'textarea')}
        ${field('cannot_edit (한 줄에 하나)', 'gf-cannot', listText(role.cannot_edit), 'textarea')}
        <div class="gpactions"><button id="gpsave" class="primary">저장</button><button id="gpdel" class="danger">이 자리 삭제</button></div>`,
      bind() {
        if (s) $('gpopen').onclick = () => { closeGraph(); openSession(s.name); };
        $('gpsave').onclick = () => {
          const count = Math.max(1, parseInt($('gf-count').value, 10) || 1);
          const lists = { allowed_tools: textList($('gf-tools').value), can_edit: textList($('gf-can').value), cannot_edit: textList($('gf-cannot').value) };
          saveGraph('org', [
            $('gf-model').value.trim() ? { path: [...base, 'model'], value: $('gf-model').value.trim() } : { path: [...base, 'model'], delete: true },
            { path: [...base, 'count'], value: count },
            $('gf-prompt').value.trim() ? { path: ['roles', sel.role, 'prompt'], value: $('gf-prompt').value.trim() } : { path: ['roles', sel.role, 'prompt'], delete: true },
            { path: ['roles', sel.role, 'allowed_tools'], value: lists.allowed_tools },
            lists.can_edit.length ? { path: ['roles', sel.role, 'can_edit'], value: lists.can_edit } : { path: ['roles', sel.role, 'can_edit'], delete: true },
            lists.cannot_edit.length ? { path: ['roles', sel.role, 'cannot_edit'], value: lists.cannot_edit } : { path: ['roles', sel.role, 'cannot_edit'], delete: true },
          ]);
        };
        $('gpdel').onclick = () => {
          if (sel.sharedKey) {
            if (!confirm(`공통 역할 '${sel.sharedKey}'를 삭제할까요?`)) return;
            return saveGraph('org', [{ path: ['shared', sel.sharedKey], delete: true }], null);
          }
          const dept = o.divisions[sel.div].depts[sel.dept];
          const last = ['lead', 'members'].filter((k) => dept[k]).length === 1;
          if (!confirm(last ? `'${sel.dept}' 부서의 마지막 역할입니다. 부서도 함께 삭제할까요?` : `'${sel.dept}'의 ${sel.role} 자리를 삭제할까요?`)) return;
          saveGraph('org', [{ path: last ? ['divisions', sel.div, 'depts', sel.dept] : base, delete: true }], null);
        };
      },
    };
  },
  shared() {
    const o = org();
    const rows = Object.entries(o.shared || {}).map(([k, m]) => `<li>${esc(k)} · ${esc(m.role)}${m.count > 1 ? ` ×${m.count}` : ''}${m.model ? ` · ${esc(m.model)}` : ''}</li>`).join('');
    return {
      html: `${panelHead('전사 공통', '모든 본부가 함께 쓰는 역할')}<ul class="glist">${rows || '<li class="gdim">없음</li>'}</ul>
        <h4>공통 역할 추가</h4>${field('자리 이름 (예: analysis)', 'gf-key', '')}${roleFieldHtml('gf-role', null)}
        ${field('모델', 'gf-model', 'sonnet')}${field('인원', 'gf-count', 1, 'number', ' min="1"')}
        <div class="gpactions"><button id="gpsave" class="primary">추가</button></div>`,
      bind() {
        bindRoleField('gf-role');
        $('gpsave').onclick = () => tryOps(() => {
          const ops = [];
          const key = need('gf-key', '자리 이름');
          const role = readRole('gf-role', ops);
          ops.push({ path: ['shared', key], value: { role, model: $('gf-model').value.trim() || undefined, count: Math.max(1, parseInt($('gf-count').value, 10) || 1) } });
          return saveGraph('org', ops);
        });
      },
    };
  },
  newdiv() {
    const profiles = Object.keys(org().profiles || {});
    return {
      html: `${panelHead('새 본부', '')}${field('본부 ID (예: bsp)', 'gf-id', '')}${field('이름', 'gf-name', '')}
        ${selectField('프로파일', 'gf-profile', profiles[0] || '__new__', [...profiles, ['__new__', '＋ 새 프로파일…']])}
        <label id="gf-profile-newbox" class="newrole" hidden>새 프로파일 이름<input id="gf-profile-new" type="text"></label>
        ${field('git 저장소 (bare 저장소 경로나 서버 주소)', 'gf-repo', '')}
        ${selectField('프로세스 템플릿', 'gf-tpl', Object.keys(templates())[0] || '', ['', ...Object.keys(templates())].map((k) => [k, k || '(없음)']))}
        <div class="gpactions"><button id="gpsave" class="primary">추가</button></div>`,
      bind() {
        const sync = () => { $('gf-profile-newbox').hidden = $('gf-profile').value !== '__new__'; };
        $('gf-profile').onchange = sync;
        sync();
        $('gpsave').onclick = () => tryOps(() => {
          const id = need('gf-id', '본부 ID');
          const ops = [];
          let profile = $('gf-profile').value;
          if (profile === '__new__') {
            profile = need('gf-profile-new', '프로파일 이름');
            ops.push({ path: ['profiles', profile], value: { standards: [], gates_dir: `gates/${profile}` } });
          }
          const div = { name: $('gf-name').value.trim() || id, profile, depts: {} };
          if ($('gf-repo').value.trim()) div.repo = $('gf-repo').value.trim();
          if ($('gf-tpl').value) div.template = $('gf-tpl').value;
          ops.push({ path: ['divisions', id], value: div });
          return saveGraph('org', ops, { kind: 'div', div: id });
        });
      },
    };
  },
  div(sel) {
    const d = org().divisions[sel.div];
    const profiles = Object.keys(org().profiles || {});
    return {
      html: `${panelHead(`본부 ${sel.div}`, d.name)}${field('이름', 'gf-name', d.name || '')}
        ${selectField('프로파일', 'gf-profile', d.profile, profiles)}
        ${field('git 저장소', 'gf-repo', d.repo || '')}
        ${selectField('프로세스 템플릿', 'gf-tpl', d.template || '', ['', ...Object.keys(templates())].map((k) => [k, k || '(자동)']))}
        <div class="gpactions"><button id="gpsave" class="primary">저장</button><button id="gpproc">프로세스 보기</button></div>
        <h4>부서 추가</h4>${field('부서 ID (예: impl)', 'gf-dept', '')}${roleFieldHtml('gf-role', null)}
        ${field('인원', 'gf-count', 1, 'number', ' min="1"')}${field('계층 (쉼표로, 병렬 구현용)', 'gf-layers', '')}
        <div class="gpactions"><button id="gpadd">부서 추가</button></div>
        <div class="gpactions"><button id="gpdel" class="danger">본부 삭제</button></div>`,
      bind() {
        bindRoleField('gf-role');
        $('gpsave').onclick = () => saveGraph('org', [
          { path: ['divisions', sel.div, 'name'], value: $('gf-name').value.trim() || sel.div },
          { path: ['divisions', sel.div, 'profile'], value: $('gf-profile').value },
          $('gf-repo').value.trim() ? { path: ['divisions', sel.div, 'repo'], value: $('gf-repo').value.trim() } : { path: ['divisions', sel.div, 'repo'], delete: true },
          $('gf-tpl').value ? { path: ['divisions', sel.div, 'template'], value: $('gf-tpl').value } : { path: ['divisions', sel.div, 'template'], delete: true },
        ]);
        $('gpproc').onclick = () => { graph.division = sel.div; graph.view = 'process'; selectGraphNode(null); };
        $('gpadd').onclick = () => tryOps(() => {
          const dept = need('gf-dept', '부서 ID');
          if (d.depts?.[dept]) throw new Error('이미 있는 부서입니다');
          const ops = [];
          const role = readRole('gf-role', ops);
          const layers = textList($('gf-layers').value);
          for (const l of layers) if (!IDENT.test(l)) throw new Error(`계층 이름이 올바르지 않습니다: ${l}`);
          const value = { members: { role, count: Math.max(1, parseInt($('gf-count').value, 10) || 1) } };
          if (layers.length) value.layers = layers;
          ops.push({ path: ['divisions', sel.div, 'depts', dept], value });
          return saveGraph('org', ops, { kind: 'dept', div: sel.div, dept });
        });
        $('gpdel').onclick = () => {
          if (!confirm(`본부 '${sel.div}'와 그 부서를 모두 삭제할까요? 진행 중인 세션은 그대로 남습니다.`)) return;
          saveGraph('org', [{ path: ['divisions', sel.div], delete: true }], null);
        };
      },
    };
  },
  dept(sel) {
    const d = org().divisions[sel.div].depts[sel.dept];
    const slots = ['lead', 'members'].filter((k) => d[k]);
    const free = ['lead', 'members'].filter((k) => !d[k]);
    return {
      html: `${panelHead(`부서 ${sel.dept}`, `본부 ${sel.div}`)}
        <ul class="glist">${slots.map((k) => `<li>${k === 'lead' ? '책임자' : '구성원'}: ${esc(d[k].role)} ×${d[k].count || 1}${d[k].model ? ` · ${esc(d[k].model)}` : ''}</li>`).join('')}</ul>
        ${field('계층 (쉼표로)', 'gf-layers', (d.layers || []).join(', '))}${field('부서 규칙 파일', 'gf-rules', d.rules || '')}
        <div class="gpactions"><button id="gpsave" class="primary">저장</button></div>
        ${free.length ? `<h4>역할 추가</h4>${selectField('자리', 'gf-slot', free[0], free.map((k) => [k, k === 'lead' ? '책임자 (lead)' : '구성원 (members)']))}
        ${roleFieldHtml('gf-role', null)}${field('모델', 'gf-model', '')}${field('인원', 'gf-count', 1, 'number', ' min="1"')}
        <div class="gpactions"><button id="gpadd">역할 추가</button></div>` : '<p class="gdim">책임자와 구성원 자리가 모두 찼습니다. 역할 노드를 눌러 바꾸세요.</p>'}
        <div class="gpactions"><button id="gpdel" class="danger">부서 삭제</button></div>`,
      bind() {
        if (free.length) bindRoleField('gf-role');
        const base = ['divisions', sel.div, 'depts', sel.dept];
        $('gpsave').onclick = () => tryOps(() => {
          const layers = textList($('gf-layers').value);
          for (const l of layers) if (!IDENT.test(l)) throw new Error(`계층 이름이 올바르지 않습니다: ${l}`);
          return saveGraph('org', [
            layers.length ? { path: [...base, 'layers'], value: layers } : { path: [...base, 'layers'], delete: true },
            $('gf-rules').value.trim() ? { path: [...base, 'rules'], value: $('gf-rules').value.trim() } : { path: [...base, 'rules'], delete: true },
          ]);
        });
        if (free.length) {
          $('gpadd').onclick = () => tryOps(() => {
            const ops = [];
            const role = readRole('gf-role', ops);
            const m = { role, count: Math.max(1, parseInt($('gf-count').value, 10) || 1) };
            if ($('gf-model').value.trim()) m.model = $('gf-model').value.trim();
            ops.push({ path: [...base, $('gf-slot').value], value: m });
            return saveGraph('org', ops);
          });
        }
        $('gpdel').onclick = () => {
          if (!confirm(`부서 '${sel.dept}'를 삭제할까요?`)) return;
          saveGraph('org', [{ path: base, delete: true }], { kind: 'div', div: sel.div });
        };
      },
    };
  },
  node(sel) {
    const t = templates()[sel.template];
    const n = t.nodes[sel.key];
    const names = Object.keys(t.nodes);
    const base = ['templates', sel.template, 'nodes', sel.key];
    if (n.type === 'approval' || n.type === 'terminal') {
      const opts = n.options || [];
      return {
        html: `${panelHead(sel.key, n.type === 'approval' ? '결재 노드' : '종료 노드')}
          ${n.type === 'approval' ? `<h4>선택지</h4>${field('재설계 (처음 단계로)', 'gf-o-redesign', opts.includes('redesign'), 'checkbox')}
          ${field('중단', 'gf-o-drop', opts.includes('drop'), 'checkbox')}${field('통과 처리 (원래 다음 단계로)', 'gf-o-override', opts.includes('override'), 'checkbox')}
          <div class="gpactions"><button id="gpsave" class="primary">저장</button></div>` : ''}
          <div class="gpactions"><button id="gpdel" class="danger">단계 삭제</button></div>`,
        bind() {
          if (n.type === 'approval') {
            $('gpsave').onclick = () => saveGraph('process', [{ path: [...base, 'options'],
              value: ['redesign', 'drop', 'override'].filter((o) => $(`gf-o-${o}`).checked) }]);
          }
          $('gpdel').onclick = () => deleteNode(sel.template, sel.key);
        },
      };
    }
    const nodeOpts = names.filter((k) => k !== sel.key);
    return {
      html: `${panelHead(sel.key, `템플릿 ${sel.template}`)}
        ${selectField('담당 역할', 'gf-role', n.role, roleOptions(false))}
        ${field('게이트', 'gf-gate', n.gate || '')}${field('사전 게이트 (pre_gate)', 'gf-pregate', n.pre_gate || '')}
        ${selectField('통과하면', 'gf-next', n.next || '', ['', ...nodeOpts].map((k) => [k, k || '(없음)']))}
        ${selectField('실패하면', 'gf-fail', n.on_fail || '', ['', ...nodeOpts].map((k) => [k, k || '(없음)']))}
        ${field('같은 단계 재시도 횟수', 'gf-retry', n.retry || 0, 'number', ' min="0"')}
        ${field('계층별 병렬 (parallel)', 'gf-par', n.parallel, 'checkbox')}
        ${field('시작 전에 결재 받기', 'gf-appr', n.requires_approval, 'checkbox')}
        ${field('반려 루프 노드 (다른 단계의 실패가 모이는 곳)', 'gf-isloop', !!n.loop, 'checkbox')}
        <div id="gf-loopbox"${n.loop ? '' : ' hidden'}>
          ${field('발생 단계별 상한 (단계: 횟수, 한 줄에 하나)', 'gf-loop', Object.entries(n.loop?.max || {}).map(([k, v]) => `${k}: ${v}`).join('\n'), 'textarea')}
          ${selectField('상한 초과 시', 'gf-exceed', n.loop?.on_exceed || '', ['', ...nodeOpts].map((k) => [k, k || '(없음)']))}
        </div>
        <div class="gpactions"><button id="gpsave" class="primary">저장</button><button id="gpdel" class="danger">단계 삭제</button></div>`,
      bind() {
        $('gf-isloop').onchange = () => { $('gf-loopbox').hidden = !$('gf-isloop').checked; };
        $('gpsave').onclick = () => tryOps(() => {
          const ops = [];
          const set = (k, v) => ops.push(v === '' || v === false || v === 0 || v == null ? { path: [...base, k], delete: true } : { path: [...base, k], value: v });
          set('role', $('gf-role').value);
          set('gate', $('gf-gate').value.trim());
          set('pre_gate', $('gf-pregate').value.trim());
          set('next', $('gf-next').value);
          set('on_fail', $('gf-fail').value);
          set('retry', parseInt($('gf-retry').value, 10) || 0);
          set('parallel', $('gf-par').checked);
          set('requires_approval', $('gf-appr').checked);
          if ($('gf-isloop').checked) {
            const max = {};
            for (const line of textList($('gf-loop').value.replace(/,/g, '\n'))) {
              const [k, v] = line.split(':').map((x) => x.trim());
              if (k) max[k] = parseInt(v, 10) || 1;
            }
            ops.push({ path: [...base, 'loop'], value: { counter_by: 'source_node', max, on_exceed: $('gf-exceed').value } });
          } else {
            ops.push({ path: [...base, 'loop'], delete: true });
          }
          return saveGraph('process', ops);
        });
        $('gpdel').onclick = () => deleteNode(sel.template, sel.key);
      },
    };
  },
  newnode(sel) {
    const t = templates()[sel.template];
    const names = Object.keys(t.nodes);
    const fails = names.filter((k) => t.nodes[k].type !== 'terminal');
    return {
      html: `${panelHead('새 단계', `템플릿 ${sel.template}`)}${field('단계 이름 (예: std_check)', 'gf-id', '')}
        ${selectField('종류', 'gf-type', 'work', [['work', '작업'], ['approval', '결재'], ['terminal', '종료']])}
        <div id="gf-workbox">${selectField('담당 역할', 'gf-role', Object.keys(org().roles || {})[0], roleOptions(false))}
        ${field('게이트', 'gf-gate', '')}
        ${selectField('실패하면', 'gf-fail', fails.find((k) => t.nodes[k].type === 'approval') || (t.nodes.escalate ? 'escalate' : '__esc__'),
    [...fails.map((k) => [k, k]), ...(t.nodes.escalate ? [] : [['__esc__', '＋ 결재 노드 escalate 새로 만들기']])])}</div>
        ${selectField('어디에 넣을까요', 'gf-after', names.filter((k) => t.nodes[k].type !== 'terminal').slice(-1)[0] || '__start__',
    [['__start__', '맨 앞 (시작 단계)'], ...names.filter((k) => t.nodes[k].type !== 'terminal').map((k) => [k, `${k} 뒤`]), ['', '(연결하지 않음)']])}
        <p class="gdim">고른 단계의 "통과하면"이 새 단계로 바뀌고, 새 단계는 원래 다음 단계로 이어집니다.</p>
        <div class="gpactions"><button id="gpsave" class="primary">추가</button></div>`,
      bind() {
        const sync = () => { $('gf-workbox').hidden = $('gf-type').value !== 'work'; };
        $('gf-type').onchange = sync;
        sync();
        $('gpsave').onclick = () => tryOps(() => {
          const id = need('gf-id', '단계 이름');
          if (t.nodes[id]) throw new Error('이미 있는 단계입니다');
          const type = $('gf-type').value;
          const after = $('gf-after').value;
          const terminal = names.find((k) => t.nodes[k].type === 'terminal');
          const nextOf = after === '__start__' ? t.start : after ? t.nodes[after].next : terminal;
          const base = ['templates', sel.template, 'nodes'];
          const ops = [];
          let node;
          if (type === 'work') {
            let fail = $('gf-fail').value;
            if (fail === '__esc__') {
              fail = 'escalate';
              ops.push({ path: [...base, 'escalate'], value: { type: 'approval', options: ['redesign', 'drop', 'override'] } });
            }
            node = { role: $('gf-role').value, next: nextOf || terminal, on_fail: fail || undefined };
            if ($('gf-gate').value.trim()) node.gate = $('gf-gate').value.trim();
          } else if (type === 'approval') {
            node = { type: 'approval', options: ['redesign', 'drop', 'override'] };
          } else {
            node = { type: 'terminal' };
          }
          ops.push({ path: [...base, id], value: node });
          if (after === '__start__') ops.push({ path: ['templates', sel.template, 'start'], value: id });
          else if (after) ops.push({ path: [...base, after, 'next'], value: id });
          return saveGraph('process', ops, { kind: 'node', template: sel.template, key: id });
        });
      },
    };
  },
  template(sel) {
    const t = templates()[sel.template];
    const used = Object.entries(org().divisions || {}).filter(([, d]) => (d.template || Object.keys(templates())[0]) === sel.template).map(([k]) => k);
    return {
      html: `${panelHead(`템플릿 ${sel.template}`, used.length ? `사용: ${used.join(', ')}` : '사용하는 본부 없음')}
        ${selectField('시작 단계', 'gf-start', t.start, Object.keys(t.nodes))}
        ${field('단계 시간 상한 (시간)', 'gf-node-h', t.limits?.node_timeout_h ?? '', 'number', ' min="0" step="0.5"')}
        ${field('지시서 확인 시간 상한 (시간)', 'gf-ack-h', t.limits?.ack_timeout_h ?? '', 'number', ' min="0" step="0.5"')}
        <div class="gpactions"><button id="gpsave" class="primary">저장</button><button id="gpdel" class="danger">템플릿 삭제</button></div>`,
      bind() {
        const base = ['templates', sel.template];
        $('gpsave').onclick = () => {
          const ops = [{ path: [...base, 'start'], value: $('gf-start').value }];
          for (const [id, key] of [['gf-node-h', 'node_timeout_h'], ['gf-ack-h', 'ack_timeout_h']]) {
            const v = parseFloat($(id).value);
            ops.push(Number.isFinite(v) && v > 0 ? { path: [...base, 'limits', key], value: v } : { path: [...base, 'limits', key], delete: true });
          }
          saveGraph('process', ops);
        };
        $('gpdel').onclick = () => {
          if (used.length) return toast(`본부 ${used.join(', ')}가 이 템플릿을 씁니다. 먼저 본부의 템플릿을 바꾸세요`, 4000);
          if (!confirm(`템플릿 '${sel.template}'를 삭제할까요?`)) return;
          saveGraph('process', [{ path: base, delete: true }], null);
        };
      },
    };
  },
  newtemplate() {
    return {
      html: `${panelHead('새 프로세스 템플릿', '')}${field('템플릿 이름 (예: hotfix)', 'gf-id', '')}
        <p class="gdim">시작·종료만 있는 빈 템플릿을 만듭니다. 만든 뒤 ＋ 단계로 채우세요.</p>
        <div class="gpactions"><button id="gpsave" class="primary">만들기</button></div>`,
      bind() {
        $('gpsave').onclick = () => tryOps(() => {
          const id = need('gf-id', '템플릿 이름');
          if (templates()[id]) throw new Error('이미 있는 템플릿입니다');
          return saveGraph('process', [{ path: ['templates', id], value: { start: 'done', nodes: { done: { type: 'terminal' } }, limits: { node_timeout_h: 24 } } }],
            { kind: 'template', template: id });
        });
      },
    };
  },
};

function tryOps(fn) {
  try {
    return fn();
  } catch (e) {
    $('gpissues').innerHTML = `<li>${esc(e.message)}</li>`;
    return null;
  }
}

function deleteNode(template, key) {
  const t = templates()[template];
  const n = t.nodes[key];
  if (!confirm(`단계 '${key}'를 삭제할까요? 이 단계로 이어지던 연결은 다음 단계로 바로 잇습니다.`)) return;
  const base = ['templates', template, 'nodes'];
  const ops = [];
  for (const [k, m] of Object.entries(t.nodes)) {
    if (k === key) continue;
    if (m.next === key) ops.push(n.next ? { path: [...base, k, 'next'], value: n.next } : { path: [...base, k, 'next'], delete: true });
    if (m.on_fail === key) ops.push(n.on_fail ? { path: [...base, k, 'on_fail'], value: n.on_fail } : { path: [...base, k, 'on_fail'], delete: true });
    if (m.loop?.on_exceed === key) ops.push({ path: [...base, k, 'loop', 'on_exceed'], value: n.next || '' });
    if (m.loop?.max && key in m.loop.max) ops.push({ path: [...base, k, 'loop', 'max', key], delete: true });
  }
  if (t.start === key && n.next) ops.push({ path: ['templates', template, 'start'], value: n.next });
  ops.push({ path: [...base, key], delete: true });
  saveGraph('process', ops, null);
}

function renderGraphPanel() {
  const p = $('gpanel');
  const sel = graph.selected;
  p.hidden = !sel || !graph.model?.org;
  if (p.hidden) return;
  const make = PANELS[sel.kind];
  let panel;
  try {
    panel = make(sel);
  } catch {
    graph.selected = null;
    p.hidden = true;
    return;
  }
  p.innerHTML = `${panel.html}<ul id="gpissues"></ul>`;
  panel.bind();
  $('gpclose').onclick = () => selectGraphNode(null);
}

async function saveGraph(kind, ops, nextSel) {
  const ul = $('gpissues');
  if (ul) ul.innerHTML = '';
  try {
    await api('PATCH', `/company/${kind}`, { ops: ops.filter(Boolean) });
  } catch (e) {
    let issues = [];
    try { issues = JSON.parse(e.message).issues || []; } catch {}
    if (ul) {
      ul.innerHTML = issues.length
        ? issues.map((i) => `<li><b>${esc(i.rule)}</b> ${esc(i.where)}<br>${esc(i.message)}</li>`).join('')
        : `<li>${esc(e.message)}</li>`;
    }
    return false;
  }
  toast('저장했습니다');
  if (nextSel !== undefined) graph.selected = nextSel;
  await loadGraph();
  renderGraphPanel();
  return true;
}

function selectGraphNode(n) {
  graph.selected = n;
  renderGraph();
  renderGraphPanel();
}

async function loadGraph() {
  try {
    [graph.model, graph.insts, graph.summary] = await Promise.all([
      api('GET', '/company/model'), api('GET', '/company/instances'), api('GET', '/company'),
    ]);
  } catch (e) {
    toast(e.message);
    return;
  }
  renderGraph();
}

let graphTimer = null;

function openGraph() {
  $('graph').hidden = false;
  loadGraph().then(renderGraphPanel);
  clearInterval(graphTimer);
  graphTimer = setInterval(() => {
    if ($('graph').hidden || $('gpanel').contains(document.activeElement)) return;
    refresh().then(loadGraph);
  }, 5000);
}

function closeGraph() {
  $('graph').hidden = true;
  clearInterval(graphTimer);
}

$('graphbtn').onclick = () => ($('graph').hidden ? openGraph() : closeGraph());
$('gclose').onclick = closeGraph;
for (const b of document.querySelectorAll('#graph .gtab')) {
  b.onclick = () => {
    graph.view = b.dataset.view;
    selectGraphNode(null);
  };
}
$('gdivsel').onchange = () => { graph.division = $('gdivsel').value; selectGraphNode(null); };
$('ginstsel').onchange = () => { graph.instance = $('ginstsel').value; renderGraph(); };

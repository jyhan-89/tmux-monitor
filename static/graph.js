const graph = {
  view: 'org',
  model: null,
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

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function sessionInfo(name) {
  return sessions.find((s) => s.name === name) || null;
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
  const label = n.suffix ? `${n.role} · ${n.suffix}` : n.role;
  const sel = graph.selected?.name === n.name && graph.selected?.kind === 'role' ? ' sel' : '';
  return `<g class="gnode st-${esc(n.state)}${sel}" data-i="${n.i}" transform="translate(${x},${y})">
    <title>${esc(n.name)} · ${esc(STATE_TEXT[n.state] || '세션 없음')}${n.model ? ` · ${esc(n.model)}` : ''}</title>
    <rect width="${w}" height="${NH}" rx="6"></rect><circle cx="10" cy="${NH / 2}" r="4"></circle>
    <text x="20" y="${NH / 2 + 4}">${esc(label.length > 15 ? `${label.slice(0, 14)}…` : label)}</text></g>`;
}

function renderOrg() {
  const org = graph.model.org;
  const nodes = [];
  const parts = [];
  const shared = Object.entries(org.shared || {}).flatMap(([key, m]) => roleNodes('shared', { key: 'shared', layers: [] }, 'shared', m)
    .map((n) => ({ ...n, div: Object.keys(org.divisions || {})[0] || 'shared', dept: 'shared', sharedKey: key })));
  const divs = Object.entries(org.divisions || {});
  const divW = 2 * NW + GAP + 2 * PAD + 2 * PAD;
  let y = 8;
  const sharedCols = Math.max(2, Math.floor((Math.max(divs.length, 1) * (divW + GAP) - GAP - 2 * PAD) / (NW + GAP)));
  if (shared.length) {
    const rows = Math.ceil(shared.length / sharedCols);
    const h = 26 + rows * (NH + GAP) + PAD;
    parts.push(`<g transform="translate(8,${y})"><rect class="gbox shared" width="${Math.max(divs.length, 1) * (divW + GAP) - GAP}" height="${h}" rx="8"></rect>
      <text class="gtitle" x="${PAD}" y="18">전사 공통</text>`);
    shared.forEach((n, i) => {
      const real = sessions.find((s) => s.meta?.role === n.role && s.name.split('-')[1] === 'shared');
      n.name = real?.name || `${divs[0]?.[0] || 'x'}-shared-${n.role}`;
      n.state = real?.state || 'none';
      n.i = nodes.push(n) - 1;
      parts.push(nodeSvg(n, PAD + (i % sharedCols) * (NW + GAP), 26 + Math.floor(i / sharedCols) * (NH + GAP)));
    });
    parts.push('</g>');
    y += h + 12;
  }
  let maxH = 0;
  divs.forEach(([divKey, div], di) => {
    const x = 8 + di * (divW + GAP);
    const inner = [];
    let dy = 30;
    for (const [deptKey, dept] of Object.entries(div.depts || {})) {
      const d = { ...dept, key: deptKey };
      const items = ['lead', 'members'].filter((slot) => dept[slot]).flatMap((slot) => roleNodes(divKey, d, slot, dept[slot]));
      const rows = Math.ceil(items.length / 2);
      const h = 24 + rows * (NH + GAP) + 4;
      inner.push(`<g transform="translate(${PAD},${dy})"><rect class="gbox dept" width="${divW - 2 * PAD}" height="${h}" rx="6"></rect>
        <text class="gsub" x="${PAD}" y="16">${esc(deptKey)}${dept.layers?.length ? ` · ${esc(dept.layers.join(', '))}` : ''}</text>`);
      items.forEach((n, i) => {
        n.i = nodes.push(n) - 1;
        inner.push(nodeSvg(n, PAD + (i % 2) * (NW + GAP), 22 + Math.floor(i / 2) * (NH + GAP)));
      });
      inner.push('</g>');
      dy += h + GAP;
    }
    const h = dy + 4;
    maxH = Math.max(maxH, h);
    parts.push(`<g transform="translate(${x},${y})"><rect class="gbox div" width="${divW}" height="${h}" rx="8" data-div="${esc(divKey)}"></rect>
      <text class="gtitle" x="${PAD}" y="20" data-div="${esc(divKey)}">${esc(divKey)} · ${esc(div.name || '')} <tspan class="gdim">(${esc(div.profile || '')})</tspan></text>${inner.join('')}</g>`);
  });
  const width = 16 + Math.max(divs.length, 1) * (divW + GAP);
  return { svg: `<svg width="${width}" height="${y + maxH + 16}" xmlns="http://www.w3.org/2000/svg">${parts.join('')}</svg>`, nodes };
}

function templateOf(divKey) {
  const proc = graph.model.process;
  const div = graph.model.org?.divisions?.[divKey];
  const keys = Object.keys(proc?.templates || {});
  const key = div?.template || (keys.length === 1 ? keys[0] : keys[0]);
  return key ? { key, t: proc.templates[key] } : null;
}

function renderProcess() {
  const tpl = templateOf(graph.division);
  if (!tpl) return { svg: '<p class="gempty">프로세스 템플릿이 없습니다</p>', nodes: [] };
  const { key, t } = tpl;
  const ns = t.nodes || {};
  const inst = graph.insts.find((i) => `${i.division}/${i.feature}` === graph.instance);
  const main = [];
  for (let k = t.start; k && ns[k] && !main.includes(k); k = ns[k].next) {
    main.push(k);
    if (ns[k].type === 'terminal') break;
  }
  const rest = Object.keys(ns).filter((k) => !main.includes(k));
  const left = rest.filter((k) => ns[k].type !== 'approval');
  const right = rest.filter((k) => ns[k].type === 'approval');
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
    if (label) {
      const mx = (a.x + b.x + W) / 2;
      const my = (a.y + b.y + NH) / 2;
      edges.push(`<text class="glabel ${cls}" x="${mx}" y="${my}">${esc(label)}</text>`);
    }
  };
  for (const [k, n] of Object.entries(ns)) {
    if (n.next) arrow(k, n.next, left.includes(k) ? 'loop' : 'next');
    if (n.on_fail) arrow(k, n.on_fail, ns[n.on_fail]?.type === 'approval' ? 'esc' : 'fail');
    if (n.loop?.on_exceed) arrow(k, n.loop.on_exceed, 'esc', '상한 초과');
    if (n.type === 'approval') {
      if ((n.options || []).includes('redesign')) arrow(k, t.start, 'loop', '재설계');
    }
  }
  const nodes = [];
  const boxes = Object.entries(pos).map(([k, p]) => {
    const n = ns[k];
    const item = { kind: 'node', template: key, key: k, node: n };
    item.i = nodes.push(item) - 1;
    const cur = inst?.node === k ? ' cur' : '';
    const sel = graph.selected?.kind === 'node' && graph.selected.key === k ? ' sel' : '';
    const type = n.type === 'approval' ? 'approval' : n.type === 'terminal' ? 'terminal' : 'work';
    const sub = n.type === 'approval' ? '결재' : n.type === 'terminal' ? '종료' : `${n.role || ''}${n.parallel ? ' ×계층' : ''}${n.requires_approval ? ' · 결재' : ''}`;
    let counter = '';
    if (n.loop?.max && inst) {
      counter = Object.entries(n.loop.max).map(([src, mx]) => `${src} ${inst.counters?.[src] || 0}/${mx}`).join(' · ');
    } else if (n.loop?.max) {
      counter = `상한 ${Object.entries(n.loop.max).map(([src, mx]) => `${src} ${mx}`).join(', ')}`;
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

function renderGraph() {
  const box = $('gcanvas');
  if (!graph.model?.org) {
    box.innerHTML = '<p class="gempty">조직 정의가 없습니다. 설정 폴더의 company/에 org.yaml·process.yaml·documents.yaml을 두세요.</p>';
    return;
  }
  const divs = Object.keys(graph.model.org.divisions || {});
  if (!divs.includes(graph.division)) graph.division = divs[0] || null;
  $('gdivsel').innerHTML = divs.map((d) => `<option value="${esc(d)}"${d === graph.division ? ' selected' : ''}>${esc(d)}</option>`).join('');
  const insts = graph.insts.filter((i) => i.division === graph.division);
  if (!insts.some((i) => `${i.division}/${i.feature}` === graph.instance)) graph.instance = insts[0] ? `${insts[0].division}/${insts[0].feature}` : '';
  $('ginstsel').innerHTML = '<option value="">인스턴스 없음</option>'
    + insts.map((i) => `<option value="${esc(`${i.division}/${i.feature}`)}"${`${i.division}/${i.feature}` === graph.instance ? ' selected' : ''}>${esc(i.feature)} · ${esc(i.node)}</option>`).join('');
  $('gdivsel').hidden = graph.view !== 'process';
  $('ginstsel').hidden = graph.view !== 'process';
  for (const b of document.querySelectorAll('#graph .gtab')) b.classList.toggle('on', b.dataset.view === graph.view);
  const { svg, nodes } = graph.view === 'org' ? renderOrg() : renderProcess();
  box.innerHTML = svg;
  $('glegend').innerHTML = graphLegend();
  for (const el of box.querySelectorAll('[data-i]')) {
    el.addEventListener('click', () => selectGraphNode(nodes[+el.dataset.i]));
  }
  for (const el of box.querySelectorAll('[data-div]')) {
    el.addEventListener('dblclick', () => {
      graph.division = el.dataset.div;
      graph.view = 'process';
      graph.selected = null;
      renderGraph();
      renderGraphPanel();
    });
  }
}

const listText = (v) => (Array.isArray(v) ? v.join('\n') : '');
const textList = (v) => v.split('\n').map((x) => x.trim()).filter(Boolean);

function field(label, id, value, type = 'text') {
  if (type === 'textarea') return `<label>${esc(label)}<textarea id="${id}" rows="4">${esc(value)}</textarea></label>`;
  if (type === 'checkbox') return `<label class="chk"><input id="${id}" type="checkbox"${value ? ' checked' : ''}> ${esc(label)}</label>`;
  return `<label>${esc(label)}<input id="${id}" type="${type}" value="${esc(value)}"></label>`;
}

function renderGraphPanel() {
  const p = $('gpanel');
  const sel = graph.selected;
  p.hidden = !sel;
  if (!sel) return;
  const org = graph.model.org;
  if (sel.kind === 'role') {
    const role = org.roles?.[sel.role] || {};
    const member = sel.sharedKey ? org.shared[sel.sharedKey] : org.divisions[sel.div].depts[sel.dept][sel.slot];
    const s = sessionInfo(sel.name);
    p.innerHTML = `<div class="gph"><b>${esc(sel.role)}</b><span>${esc(sel.name)}</span><button id="gpclose">×</button></div>
      <p class="gdim">${s ? `세션 ${esc(STATE_TEXT[s.state] || s.state || '')}${s.meta?.node ? ` · 노드 ${esc(s.meta.node)}` : ''}` : '세션 없음'}</p>
      ${s ? '<button id="gpopen" class="primary">세션 열기</button>' : ''}
      ${field('모델', 'gf-model', member.model || '')}${field('인원 (count)', 'gf-count', member.count || 1, 'number')}
      ${field('프롬프트', 'gf-prompt', role.prompt || '')}
      ${field('allowed_tools (한 줄에 하나)', 'gf-tools', listText(role.allowed_tools), 'textarea')}
      ${field('can_edit (한 줄에 하나)', 'gf-can', listText(role.can_edit), 'textarea')}
      <div class="gpactions"><button id="gpsave" class="primary">저장</button></div><ul id="gpissues"></ul>`;
    if (s) $('gpopen').onclick = () => { closeGraph(); openSession(s.name); };
    $('gpsave').onclick = () => {
      const base = sel.sharedKey ? ['shared', sel.sharedKey] : ['divisions', sel.div, 'depts', sel.dept, sel.slot];
      const count = parseInt($('gf-count').value, 10);
      saveGraph('org', [
        { path: [...base, 'model'], value: $('gf-model').value.trim() || null, delete: !$('gf-model').value.trim() },
        { path: [...base, 'count'], value: Number.isFinite(count) ? count : 1 },
        { path: ['roles', sel.role, 'prompt'], value: $('gf-prompt').value.trim(), delete: !$('gf-prompt').value.trim() },
        { path: ['roles', sel.role, 'allowed_tools'], value: textList($('gf-tools').value) },
        { path: ['roles', sel.role, 'can_edit'], value: textList($('gf-can').value), delete: !textList($('gf-can').value).length },
      ]);
    };
  } else {
    const n = sel.node;
    const isWork = !n.type || n.type === 'work';
    p.innerHTML = `<div class="gph"><b>${esc(sel.key)}</b><span>${esc(sel.template)}</span><button id="gpclose">×</button></div>
      ${isWork ? `${field('role', 'gf-role', n.role || '')}${field('gate', 'gf-gate', n.gate || '')}${field('pre_gate', 'gf-pregate', n.pre_gate || '')}
      ${field('next', 'gf-next', n.next || '')}${field('on_fail', 'gf-fail', n.on_fail || '')}${field('retry', 'gf-retry', n.retry || 0, 'number')}
      ${field('결재 필요 (requires_approval)', 'gf-appr', n.requires_approval, 'checkbox')}
      ${n.loop ? field('loop.max (노드: 횟수, 한 줄에 하나)', 'gf-loop', Object.entries(n.loop.max || {}).map(([k, v]) => `${k}: ${v}`).join('\n'), 'textarea') : ''}
      <div class="gpactions"><button id="gpsave" class="primary">저장</button></div>`
    : `<p class="gdim">${n.type === 'approval' ? `결재 선택지: ${esc((n.options || []).join(', '))}` : '종료 노드'}</p>`}<ul id="gpissues"></ul>`;
    if (isWork) {
      $('gpsave').onclick = () => {
        const base = ['templates', sel.template, 'nodes', sel.key];
        const ops = [];
        const set = (k, v) => ops.push(v === '' || v === false || v === 0 ? { path: [...base, k], delete: true } : { path: [...base, k], value: v });
        set('role', $('gf-role').value.trim());
        set('gate', $('gf-gate').value.trim());
        set('pre_gate', $('gf-pregate').value.trim());
        set('next', $('gf-next').value.trim());
        set('on_fail', $('gf-fail').value.trim());
        set('retry', parseInt($('gf-retry').value, 10) || 0);
        set('requires_approval', $('gf-appr').checked);
        if ($('gf-loop')) {
          const max = {};
          for (const line of textList($('gf-loop').value)) {
            const [k, v] = line.split(':').map((x) => x.trim());
            if (k) max[k] = parseInt(v, 10);
          }
          ops.push({ path: [...base, 'loop', 'max'], value: max });
        }
        saveGraph('process', ops);
      };
    }
  }
  $('gpclose').onclick = () => selectGraphNode(null);
}

async function saveGraph(kind, ops) {
  const ul = $('gpissues');
  ul.innerHTML = '';
  try {
    await api('PATCH', `/company/${kind}`, { ops });
  } catch (e) {
    let issues = [];
    try { issues = JSON.parse(e.message).issues || []; } catch {}
    ul.innerHTML = issues.length
      ? issues.map((i) => `<li><b>${esc(i.rule)}</b> ${esc(i.where)}<br>${esc(i.message)}</li>`).join('')
      : `<li>${esc(e.message)}</li>`;
    return;
  }
  toast('저장했습니다');
  await loadGraph();
  const sel = graph.selected;
  if (sel?.kind === 'node') sel.node = graph.model.process.templates[sel.template].nodes[sel.key];
  renderGraphPanel();
}

function selectGraphNode(n) {
  graph.selected = n;
  renderGraph();
  renderGraphPanel();
}

async function loadGraph() {
  try {
    [graph.model, graph.insts] = await Promise.all([api('GET', '/company/model'), api('GET', '/company/instances')]);
  } catch (e) {
    toast(e.message);
    return;
  }
  renderGraph();
}

let graphTimer = null;

function openGraph() {
  $('graph').hidden = false;
  loadGraph();
  clearInterval(graphTimer);
  graphTimer = setInterval(() => { if (!$('graph').hidden) { refresh().then(loadGraph); } }, 5000);
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
    graph.selected = null;
    renderGraph();
    renderGraphPanel();
  };
}
$('gdivsel').onchange = () => { graph.division = $('gdivsel').value; graph.selected = null; renderGraph(); renderGraphPanel(); };
$('ginstsel').onchange = () => { graph.instance = $('ginstsel').value; renderGraph(); };

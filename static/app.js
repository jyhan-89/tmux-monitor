'use strict';

// 페이지가 서비스되는 경로(/dev/ 등) 기준으로 API/WS 주소 구성
const base = location.pathname.replace(/\/+$/, '');
const $ = (id) => document.getElementById(id);
const enc = encodeURIComponent;
const narrow = matchMedia('(max-width: 768px)');
const toLogin = () => location.replace(`${base}/login`);

// localStorage는 막혀 있을 수 있으니 항상 try
const LS = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};

const STATE_LABEL = { working: '작업 중', waiting: '확인 필요', idle: '대기', running: '실행 중', shell: '셸' };

let sessions = [];
let groups = [];  // 그룹 이름 목록 (서버 저장)
let sortMode = LS.get('sort', 'name-asc');
const collapsedGroups = new Set(LS.get('collapsedGroups', []));
const conns = new Map();  // 세션 이름 -> 열린 터미널 연결
let activeName = null;
let split = !!LS.get('split', false);
let fontSize = +LS.get('fontSize', narrow.matches ? 12 : 14);
let imeOn = true;
let ctrlArmed = false;
let config = { snippets: [] };

const active = () => conns.get(activeName) || null;

// ================= 공통 =================

let toastTimer;
function toast(msg, ms = 2500) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${base}/api${path}`, opts);
  if (res.status === 401) { toLogin(); throw new Error('로그인이 필요합니다'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === 'string' ? d : (d ? JSON.stringify(d) : res.statusText));
  }
  return data;
}

function ago(ts) {
  const s = Math.floor(Date.now() / 1000) - ts;
  if (s < 60) return `${Math.max(s, 0)}초 전`;
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return `${Math.floor(s / 86400)}일 전`;
}

const shortPath = (p) => p.split('/').filter(Boolean).slice(-2).join('/') || '/';

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // HTTP 주소에서는 clipboard API가 막혀 있어 예전 방식 사용
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    (document.querySelector('dialog[open]') || document.body).appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }
}

// 버튼을 눌러도 포커스(=모바일 키보드)가 유지되도록
function keepFocus(el) {
  el.addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
}

// ================= 세션 목록 =================

async function refresh() {
  try {
    [sessions, groups] = await Promise.all([api('GET', '/sessions'), api('GET', '/groups')]);
  } catch (e) {
    toast('목록 오류: ' + e.message);
    return;
  }
  renderList();
  renderTabs();
  renderWinbar();
}

function sortSessions(list) {
  const byName = (a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true });
  const cmp = {
    'name-asc': byName,
    'name-desc': (a, b) => byName(b, a),
    activity: (a, b) => b.activity - a.activity || byName(a, b),
    created: (a, b) => a.created - b.created || byName(a, b),
  }[sortMode] || byName;
  return [...list].sort(cmp);
}

function sortGroupNames(names) {
  const sorted = [...names].sort((a, b) => a.localeCompare(b, 'ko', { numeric: true }));
  return sortMode === 'name-desc' ? sorted.reverse() : sorted;
}

function renderList() {
  if (drag) return;  // 끌고 있는 동안 목록이 바뀌면 안 되므로 끝난 뒤 다시 그림
  const ul = $('sessions');
  ul.innerHTML = '';
  const sorted = sortSessions(sessions);
  if (!groups.length) {
    for (const s of sorted) ul.appendChild(sessionItem(s, false));
    return;
  }
  // 그룹별로 묶어서 표시, 그룹에 없는 세션은 맨 아래 '그룹 없음'
  const sections = sortGroupNames(groups).map((g) => [g, sorted.filter((s) => s.group === g)]);
  const loose = sorted.filter((s) => !s.group || !groups.includes(s.group));
  if (loose.length) sections.push([null, loose]);
  for (const [g, members] of sections) {
    ul.appendChild(groupHeader(g, members));
    if (!collapsedGroups.has(g ?? '')) for (const s of members) ul.appendChild(sessionItem(s, true));
  }
}

function groupHeader(g, members) {
  const key = g ?? '';
  const li = document.createElement('li');
  li.className = 'group';
  li.dataset.group = key;  // 드롭 대상
  const folded = collapsedGroups.has(key);
  li.innerHTML = `<span class="gname"></span><span class="gdots"></span><span class="gcount"></span>
    ${g === null ? '' : '<button class="act grename" title="그룹 이름 바꾸기">✎</button><button class="act gdel" title="그룹 삭제">✕</button>'}`;
  li.querySelector('.gname').textContent = `${folded ? '▸' : '▾'} ${g ?? '그룹 없음'}`;
  li.querySelector('.gcount').textContent = members.length;
  // 접었을 때도 작업 중/확인 필요 세션이 보이도록 점 표시
  const dots = li.querySelector('.gdots');
  for (const s of members) {
    if (s.state === 'working' || s.state === 'waiting') {
      const d = document.createElement('span');
      d.className = `dot st-${s.state}`;
      d.title = `${s.name}: ${STATE_LABEL[s.state]}`;
      dots.appendChild(d);
    }
  }
  li.onclick = () => {
    if (collapsedGroups.has(key)) collapsedGroups.delete(key); else collapsedGroups.add(key);
    LS.set('collapsedGroups', [...collapsedGroups]);
    renderList();
  };
  if (g !== null) {
    li.querySelector('.grename').onclick = (e) => { e.stopPropagation(); renameGroup(g); };
    li.querySelector('.gdel').onclick = (e) => { e.stopPropagation(); deleteGroup(g, members); };
  }
  return li;
}

function sessionItem(s, inGroup) {
  const li = document.createElement('li');
  li.classList.toggle('open', conns.has(s.name));
  li.classList.toggle('active', s.name === activeName);
  li.classList.toggle('ingroup', inGroup);
  if (groups.length) {
    li.dataset.group = s.group && groups.includes(s.group) ? s.group : '';
    enableDrag(li, s.name);
  }
  li.innerHTML = `
    <div class="row"><span class="dot"></span><span class="name"></span><span class="badge"></span>
      <button class="act move" title="그룹으로 이동">📁</button><button class="act rename" title="이름 바꾸기">✎</button><button class="act kill" title="세션 종료">✕</button></div>
    <div class="preview"></div><div class="meta"></div>`;
  const dot = li.querySelector('.dot');
  dot.classList.toggle('on', s.attached > 0);
  dot.title = `접속한 클라이언트 ${s.attached}`;
  li.querySelector('.name').textContent = s.name;
  const badge = li.querySelector('.badge');
  if (s.state) {
    badge.className = `badge st-${s.state}`;
    badge.textContent = STATE_LABEL[s.state];
  } else {
    badge.remove();
  }
  const pv = li.querySelector('.preview');
  for (const line of s.preview || []) {
    const d = document.createElement('div');
    d.textContent = line;
    pv.appendChild(d);
  }
  if (!pv.childElementCount) pv.remove();
  const meta = li.querySelector('.meta');
  meta.textContent = `${shortPath(s.path)} · 창 ${s.window_count} · ${ago(s.activity)}`;
  meta.title = s.path;

  li.onclick = () => openSession(s.name);
  li.querySelector('.rename').onclick = (e) => { e.stopPropagation(); renameSession(s.name); };
  li.querySelector('.kill').onclick = (e) => { e.stopPropagation(); killSession(s.name); };
  li.querySelector('.move').onclick = (e) => { e.stopPropagation(); openMove(s); };
  return li;
}

// ================= 정렬 / 그룹 =================

$('sort').value = sortMode;
$('sort').onchange = () => {
  sortMode = $('sort').value;
  LS.set('sort', sortMode);
  renderList();
};

async function createGroup(name) {
  await api('POST', '/groups', { name });
  collapsedGroups.delete(name);
}

$('newgroup').onclick = async () => {
  const name = prompt('새 그룹 이름');
  if (!name?.trim()) return;
  try { await createGroup(name.trim()); } catch (e) { return toast(e.message); }
  refresh();
};

async function renameGroup(g) {
  const name = prompt('그룹 이름 바꾸기', g);
  if (!name?.trim() || name.trim() === g) return;
  try {
    await api('PATCH', `/groups/${enc(g)}`, { new_name: name.trim() });
  } catch (e) {
    return toast(e.message);
  }
  if (collapsedGroups.delete(g)) collapsedGroups.add(name.trim());
  LS.set('collapsedGroups', [...collapsedGroups]);
  refresh();
}

let deletingGroup = null;

async function deleteGroup(g, members) {
  if (!members.length) {
    if (!confirm(`'${g}' 그룹을 삭제할까요?`)) return;
    return removeGroup(g, false);
  }
  deletingGroup = { g, members };
  $('groupdeltitle').textContent = `'${g}' 그룹 삭제`;
  $('groupdelmsg').textContent =
    `이 그룹에 세션 ${members.length}개가 있습니다 (${members.map((s) => s.name).join(', ')}). 세션을 어떻게 할까요?`;
  $('groupdeldlg').showModal();
}

async function removeGroup(g, kill) {
  try {
    const r = await api('DELETE', `/groups/${enc(g)}?kill=${kill}`);
    for (const name of r.killed || []) closeSession(name);
    if (r.failed?.length) toast(`종료 실패: ${r.failed.join(', ')}`, 4000);
    else if (kill) toast(`세션 ${r.killed.length}개를 종료했습니다`);
  } catch (e) {
    toast(e.message);
  }
  collapsedGroups.delete(g);
  LS.set('collapsedGroups', [...collapsedGroups]);
  refresh();
}

$('groupdelkeep').onclick = () => {
  $('groupdeldlg').close();
  if (deletingGroup) removeGroup(deletingGroup.g, false);
};
$('groupdelkill').onclick = () => {
  const { g, members } = deletingGroup || {};
  if (!g) return;
  if (!confirm(`세션 ${members.length}개를 정말 종료할까요? 실행 중인 작업이 모두 종료됩니다.`)) return;
  $('groupdeldlg').close();
  removeGroup(g, true);
};

let movingSession = null;

function openMove(s) {
  movingSession = s.name;
  $('movetitle').textContent = `'${s.name}' 그룹 이동`;
  const box = $('movelist');
  box.innerHTML = '';
  for (const g of [...sortGroupNames(groups), null]) {
    const b = document.createElement('button');
    b.textContent = g === null ? '그룹 없음' : `📁 ${g}`;
    if ((s.group ?? null) === g) b.className = 'cur';
    b.onclick = () => moveTo(g);
    box.appendChild(b);
  }
  $('movenew').value = '';
  $('movedlg').showModal();
}

async function moveSession(name, g) {
  try {
    await api('PUT', `/sessions/${enc(name)}/group`, { group: g });
  } catch (e) {
    toast(e.message);
    return false;
  }
  if (g !== null) {
    collapsedGroups.delete(g);
    LS.set('collapsedGroups', [...collapsedGroups]);
  }
  refresh();
  return true;
}

async function moveTo(g) {
  if (await moveSession(movingSession, g)) $('movedlg').close();
}

// ---- 드래그로 그룹 이동 (PC: 마우스 드래그, 폰: 길게 눌러서 끌기) ----
let drag = null;  // { name, li, target }

// 화면 좌표/요소 아래의 드롭 대상 그룹 ('' = 그룹 없음, undefined = 대상 아님)
function dropGroupAt(el) {
  const li = el?.closest?.('#sessions li');
  return li?.dataset.group;
}

function highlightDrop(key) {
  for (const h of document.querySelectorAll('#sessions li.group.droptarget')) h.classList.remove('droptarget');
  if (key === undefined) return;
  const header = [...document.querySelectorAll('#sessions li.group')].find((h) => h.dataset.group === key);
  header?.classList.add('droptarget');
}

function endDrag(drop) {
  const d = drag;
  drag = null;
  highlightDrop(undefined);
  $('dragghost')?.remove();
  d?.li.classList.remove('dragging');
  const current = sessions.find((s) => s.name === d?.name)?.group || '';
  if (drop && d && d.target !== undefined && d.target !== current) {
    moveSession(d.name, d.target === '' ? null : d.target).then((ok) => {
      if (ok) toast(`${d.name} → ${d.target || '그룹 없음'}`);
    });
  } else {
    renderList();
  }
}

function enableDrag(li, name) {
  li.classList.add('dnd');
  // PC (마우스): 브라우저 기본 드래그. 터치 기기는 iOS 기본 드래그와 겹치지 않게 끔
  li.draggable = matchMedia('(pointer: fine)').matches;
  li.addEventListener('dragstart', (e) => {
    drag = { name, li, target: undefined };
    e.dataTransfer.setData('text/plain', name);
    e.dataTransfer.effectAllowed = 'move';
    li.classList.add('dragging');
  });
  li.addEventListener('dragend', () => { if (drag) endDrag(false); });

  // 폰: 길게 누르면 끌기 시작
  let timer = null;
  let x0 = 0;
  let y0 = 0;
  li.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    x0 = t.clientX;
    y0 = t.clientY;
    clearTimeout(timer);
    timer = setTimeout(() => startTouchDrag(name, li, x0, y0), 450);
  }, { passive: true });
  li.addEventListener('touchmove', (e) => {
    const t = e.touches[0];
    if (Math.hypot(t.clientX - x0, t.clientY - y0) > 10) clearTimeout(timer);  // 스크롤이면 취소
  }, { passive: true });
  li.addEventListener('touchend', () => clearTimeout(timer));
  li.addEventListener('touchcancel', () => clearTimeout(timer));
}

function startTouchDrag(name, li, x, y) {
  drag = { name, li, target: undefined };
  drawerX = null;  // 세션 목록 '왼쪽 스와이프로 닫기'와 겹치지 않게
  li.classList.add('dragging');
  navigator.vibrate?.(30);
  const ghost = document.createElement('div');
  ghost.id = 'dragghost';
  ghost.textContent = `📁 ${name}`;
  document.body.appendChild(ghost);
  const list = $('sessions');

  const move = (e) => {
    e.preventDefault();  // 끄는 동안 목록 스크롤 막기
    const t = e.touches[0];
    ghost.style.left = `${t.clientX}px`;
    ghost.style.top = `${t.clientY}px`;
    drag.target = dropGroupAt(document.elementFromPoint(t.clientX, t.clientY));
    highlightDrop(drag.target);
    // 목록 위/아래 끝으로 끌면 자동 스크롤
    const r = list.getBoundingClientRect();
    if (t.clientY < r.top + 40) list.scrollTop -= 12;
    else if (t.clientY > r.bottom - 40) list.scrollTop += 12;
  };
  const end = (e) => {
    e.preventDefault();  // 손을 뗄 때 세션이 열리지(click) 않게
    document.removeEventListener('touchmove', move);
    document.removeEventListener('touchend', end);
    document.removeEventListener('touchcancel', end);
    endDrag(e.type === 'touchend');
  };
  move({ preventDefault() {}, touches: [{ clientX: x, clientY: y }] });
  document.addEventListener('touchmove', move, { passive: false });
  document.addEventListener('touchend', end, { passive: false });
  document.addEventListener('touchcancel', end, { passive: false });
}

// PC 드롭 대상 처리
$('sessions').addEventListener('dragover', (e) => {
  if (!drag) return;
  const key = dropGroupAt(e.target);
  if (key === undefined) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  drag.target = key;
  highlightDrop(key);
});
$('sessions').addEventListener('drop', (e) => {
  if (!drag) return;
  e.preventDefault();
  drag.target = dropGroupAt(e.target);
  endDrag(true);
});

$('moveform').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('movenew').value.trim();
  if (!name) return;
  try { await createGroup(name); } catch (err) { return toast(err.message); }
  moveTo(name);
});

async function renameSession(name) {
  const newName = prompt('새 세션 이름', name);
  if (!newName || newName === name) return;
  try {
    await api('PATCH', `/sessions/${enc(name)}`, { new_name: newName });
  } catch (e) {
    return toast(e.message, 4000);
  }
  // 열려 있는 탭은 연결을 유지한 채 이름만 바꿈
  const conn = conns.get(name);
  if (conn) {
    conns.delete(name);
    conn.name = newName;
    conn.el.dataset.name = newName;
    conn.label.textContent = newName;
    conns.set(newName, conn);
    if (activeName === name) activeName = newName;
    saveTabs();
  }
  refresh();
}

async function killSession(name) {
  if (!confirm(`'${name}' 세션을 종료할까요? 실행 중인 작업이 모두 종료됩니다.`)) return;
  closeSession(name);
  try { await api('DELETE', `/sessions/${enc(name)}`); } catch (e) { toast(e.message); }
  refresh();
}

// ================= 터미널 연결 (탭) =================

function saveTabs() {
  LS.set('openTabs', [...conns.keys()]);
  LS.set('activeTab', activeName);
}

function openSession(name) {
  setDrawer(false);
  if (!conns.has(name)) conns.set(name, createConn(name));
  activate(name);
  saveTabs();
}

function createConn(name) {
  const el = document.createElement('div');
  el.className = 'pane';
  el.dataset.name = name;
  const label = document.createElement('div');
  label.className = 'pane-label';
  label.textContent = name;
  const msg = document.createElement('div');
  msg.className = 'pane-msg';
  msg.hidden = true;
  const host = document.createElement('div');
  host.style.height = '100%';
  el.append(label, msg, host);
  $('term').appendChild(el);

  const term = new Terminal({
    cursorBlink: true, fontSize, scrollback: 5000,
    fontFamily: '"JetBrains Mono", "D2Coding", Menlo, Consolas, monospace',
    theme: { background: '#1e1f22' },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);

  const conn = {
    name, el, label, msg, host, term, fit,
    ws: null, opened: false, closed: false, gone: false, scrolled: false,
    retry: 0, timer: null, lastRx: 0,
  };
  conn.raw = (obj) => {
    if (conn.ws && conn.ws.readyState === WebSocket.OPEN) conn.ws.send(JSON.stringify(obj));
  };
  // 스와이프로 스크롤(copy-mode) 중이면 입력 전에 빠져나와 앱에 키가 가도록
  conn.send = (obj) => {
    if (obj.type === 'input' && conn.scrolled) {
      conn.scrolled = false;
      conn.raw({ type: 'scroll-exit' });
    }
    conn.raw(obj);
  };

  term.onData((data) => conn.send({ type: 'input', data: applyCtrl(data) }));
  term.onResize(({ cols, rows }) => conn.raw({ type: 'resize', cols, rows }));
  term.attachCustomKeyEventHandler((e) => {
    // Ctrl+Shift+C: 선택한 글자 복사
    if (e.type === 'keydown' && e.ctrlKey && e.shiftKey && e.code === 'KeyC') {
      const sel = term.getSelection();
      if (sel) copyText(sel).then((ok) => toast(ok ? '복사했습니다' : '복사 실패'));
      return false;
    }
    return true;
  });
  el.addEventListener('mousedown', () => { if (activeName !== conn.name) activate(conn.name, false); });
  new ResizeObserver(() => fitConn(conn)).observe(el);

  connectWs(conn);
  return conn;
}

// 보이는 상태에서 열어야 xterm이 글자 크기를 제대로 잼
function ensureOpen(conn) {
  if (!conn.opened) {
    conn.term.open(conn.host);
    conn.opened = true;
  }
}

function fitConn(conn) {
  if (!conn.opened || !conn.el.clientWidth || !conn.el.clientHeight) return;
  try { conn.fit.fit(); } catch {}
}

function showMsg(conn, text) {
  conn.msg.textContent = text;
  conn.msg.hidden = !text;
}

function connectWs(conn) {
  clearTimeout(conn.timer);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${base}/ws/${enc(conn.name)}`);
  ws.binaryType = 'arraybuffer';
  conn.ws = ws;

  ws.onopen = () => {
    conn.retry = 0;
    conn.gone = false;
    conn.lastRx = Date.now();
    conn.term.reset();  // attach하면 tmux가 화면 전체를 다시 그려줌
    showMsg(conn, '');
    fitConn(conn);
    conn.raw({ type: 'resize', cols: conn.term.cols, rows: conn.term.rows });
    renderTabs();
  };
  ws.onmessage = (ev) => {
    conn.lastRx = Date.now();
    if (ev.data.byteLength) conn.term.write(new Uint8Array(ev.data));
  };
  ws.onclose = (ev) => {
    if (conn.ws !== ws || conn.closed) return;
    conn.ws = null;
    renderTabs();
    if (ev.code === 4401) return toLogin();
    if (ev.code === 4404) {
      conn.gone = true;
      showMsg(conn, '세션이 없습니다 (종료되었거나 이름이 바뀜)');
      return;
    }
    scheduleReconnect(conn);
  };
}

function scheduleReconnect(conn) {
  const delay = Math.min(1000 * 2 ** conn.retry, 10000);
  conn.retry++;
  showMsg(conn, `연결 끊김 · ${Math.round(delay / 1000)}초 후 다시 연결`);
  clearTimeout(conn.timer);
  conn.timer = setTimeout(() => connectWs(conn), delay);
}

function reconnectNow(conn) {
  const old = conn.ws;
  conn.ws = null;
  old?.close();
  conn.retry = 0;
  connectWs(conn);
}

// 화면이 다시 보이거나 네트워크가 돌아오면: 끊긴 연결은 바로 재연결,
// 열려 있는 것처럼 보이는 연결도 ping으로 살아있는지 확인 (폰 절전 후 흔함)
function checkConnections() {
  for (const conn of conns.values()) {
    if (conn.closed || conn.gone) continue;
    if (!conn.ws) {
      reconnectNow(conn);
    } else if (conn.ws.readyState === WebSocket.OPEN) {
      const sentAt = Date.now();
      const ws = conn.ws;
      conn.raw({ type: 'ping' });
      setTimeout(() => { if (conn.ws === ws && conn.lastRx < sentAt) reconnectNow(conn); }, 3000);
    }
  }
  refresh();
}

function closeSession(name) {
  const conn = conns.get(name);
  if (!conn) return;
  conn.closed = true;
  clearTimeout(conn.timer);
  conn.ws?.close();
  conn.term.dispose();
  conn.el.remove();
  conns.delete(name);
  if (activeName === name) activeName = [...conns.keys()].pop() || null;
  layout();
  saveTabs();
  renderList();
}

function activate(name, focus = true) {
  if (!conns.has(name)) return;
  const changed = activeName !== name;
  activeName = name;
  layout();
  if (focus) focusInput();
  if (changed) {
    renderList();
    saveTabs();
  }
}

function focusInput() {
  const c = active();
  if (!c || narrow.matches) return;  // 폰에서는 키보드가 갑자기 올라오지 않게
  if (imeOn) $('ime').focus(); else c.term.focus();
}

function layout() {
  const list = [...conns.values()];
  const useSplit = split && !narrow.matches && list.length > 1;
  $('term').className = useSplit ? `split n${Math.min(list.length, 6)}` : '';
  $('empty').hidden = list.length > 0;
  for (const c of list) c.el.classList.toggle('active', c.name === activeName);
  for (const c of list) {
    if (useSplit || c.name === activeName) {
      ensureOpen(c);
      fitConn(c);
    }
  }
  $('split').classList.toggle('on', split);
  renderTabs();
  renderWinbar();
}

function renderTabs() {
  const box = $('tabs');
  box.innerHTML = '';
  for (const c of conns.values()) {
    const s = sessions.find((x) => x.name === c.name);
    const tab = document.createElement('div');
    tab.className = 'tab';
    tab.classList.toggle('active', c.name === activeName);
    tab.classList.toggle('offline', !(c.ws && c.ws.readyState === WebSocket.OPEN));
    tab.innerHTML = '<span class="dot"></span><span class="tname"></span><button class="tclose" title="탭 닫기 (세션은 유지)">×</button>';
    if (s?.state) tab.querySelector('.dot').classList.add(`st-${s.state}`);
    tab.querySelector('.tname').textContent = c.name;
    tab.title = s?.state ? `${c.name} · ${STATE_LABEL[s.state]}` : c.name;
    tab.onclick = () => activate(c.name);
    tab.querySelector('.tclose').onclick = (e) => { e.stopPropagation(); closeSession(c.name); };
    box.appendChild(tab);
  }
  box.querySelector('.tab.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

// ================= tmux 창/패널 =================

function renderWinbar() {
  const bar = $('winbar');
  const c = active();
  const s = c && sessions.find((x) => x.name === c.name);
  const win = s?.windows.find((w) => w.active);
  const multi = s && (s.windows.length > 1 || (win && win.panes.length > 1));
  // 폰에서는 창/패널이 여러 개일 때만 표시 (세로 공간 절약)
  if (!s || (narrow.matches && !multi)) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  bar.innerHTML = '';
  const add = (text, cls, onclick, title) => {
    const el = document.createElement(onclick ? 'button' : 'span');
    el.textContent = text;
    if (cls) el.className = cls;
    if (title) el.title = title;
    if (onclick) el.onclick = onclick;
    bar.appendChild(el);
  };
  add('창', 'lbl');
  for (const w of s.windows) add(`${w.index}:${w.name}`, w.active ? 'cur' : '', () => selectTarget(s.name, w.index));
  add('＋', '', () => newWindow(s.name), '새 창 만들기');
  if (win && win.panes.length > 1) {
    add('|', 'sep');
    add('패널', 'lbl');
    for (const p of win.panes) {
      add(`${p.index}:${p.command}`, p.active ? 'cur' : '', () => selectTarget(s.name, win.index, p.index));
    }
  }
}

async function selectTarget(name, window, pane) {
  try {
    await api('POST', `/sessions/${enc(name)}/select`, { window, pane: pane ?? null });
  } catch (e) {
    toast(e.message);
  }
  refresh();
}

async function newWindow(name) {
  try { await api('POST', `/sessions/${enc(name)}/windows`); } catch (e) { toast(e.message); }
  refresh();
}

// ================= 입력창 (한글) =================

const ime = $('ime');

function setIme(on, focus = true) {
  imeOn = !!on;
  $('imebar').hidden = !imeOn;
  $('imetoggle').classList.toggle('on', imeOn);
  LS.set('imeOn', imeOn);
  if (!focus) return;
  if (imeOn) ime.focus(); else active()?.term.focus();
}

function autoGrow() {
  ime.style.height = 'auto';
  ime.style.height = ime.scrollHeight + 2 + 'px';
}

function sendText(text, execute) {
  const c = active();
  if (!c) return toast('먼저 세션을 선택하세요');
  // paste()는 앱이 bracketed paste 모드면 자동으로 감싸고 줄바꿈도 터미널 형식으로 변환
  if (text) c.term.paste(text);
  // 붙여넣기 직후 바로 Enter를 보내면 일부 앱(Claude Code 등)이 붙여넣기의 일부로 처리하므로 약간 지연
  if (execute) setTimeout(() => c.send({ type: 'input', data: '\r' }), text ? 50 : 0);
}

function sendIme(execute) {
  if (!active()) return toast('먼저 세션을 선택하세요');
  sendText(ime.value, execute);
  ime.value = '';
  autoGrow();
}

ime.addEventListener('input', () => {
  // Ctrl 버튼이 켜진 상태에서 한 글자 입력 → Ctrl 조합으로 바로 전송
  const c = active();
  if (ctrlArmed && c && ime.value.length === 1) {
    c.send({ type: 'input', data: applyCtrl(ime.value) });
    ime.value = '';
  }
  autoGrow();
});

ime.addEventListener('keydown', (e) => {
  if (e.isComposing || e.keyCode === 229) return;  // 한글 조합 중 Enter는 조합 확정용
  const c = active();
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendIme(!(e.ctrlKey || e.metaKey));
  } else if (e.key === 'Escape') {
    e.preventDefault();
    c?.term.focus();
  } else if (!ime.value && c && (e.key === 'Backspace' || e.key.startsWith('Arrow') || e.key === 'Tab')) {
    // 입력창이 비어 있을 때는 편집 키를 터미널로 전달
    e.preventDefault();
    const keys = { Backspace: 'bs', Tab: 'tab', ArrowUp: 'up', ArrowDown: 'down', ArrowRight: 'right', ArrowLeft: 'left' };
    c.send({ type: 'input', data: keySeq(keys[e.key]) });
  }
});

// 이미지 등 파일을 입력창에 붙여넣으면 업로드
ime.addEventListener('paste', (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) {
    e.preventDefault();
    uploadFiles(files);
  }
});

$('imesend').onclick = () => sendIme(true);
$('imetoggle').onclick = () => setIme(!imeOn);

// ================= 특수키 / Ctrl =================

function setCtrl(on) {
  ctrlArmed = on;
  $('ctrlkey').classList.toggle('armed', on);
}

function applyCtrl(data) {
  if (!ctrlArmed || data.length !== 1) return data;
  setCtrl(false);
  const code = data.toUpperCase().charCodeAt(0);
  if (code >= 64 && code <= 95) return String.fromCharCode(code - 64);  // A → ^A
  return data === ' ' ? '\x00' : data;
}

function keySeq(key) {
  // vim/less 등이 켜는 application cursor 모드에서는 방향키 시퀀스가 다름
  const csi = active()?.term.modes.applicationCursorKeysMode ? '\x1bO' : '\x1b[';
  return {
    esc: '\x1b', tab: '\t', stab: '\x1b[Z', bs: '\x7f', 'c-c': '\x03', 'c-d': '\x04',
    up: csi + 'A', down: csi + 'B', right: csi + 'C', left: csi + 'D',
    home: csi + 'H', end: csi + 'F', pgup: '\x1b[5~', pgdn: '\x1b[6~',
  }[key];
}

for (const b of document.querySelectorAll('#keys button[data-key]')) {
  b.onclick = () => active()?.send({ type: 'input', data: keySeq(b.dataset.key) });
}
$('ctrlkey').onclick = () => setCtrl(!ctrlArmed);
$('pastekey').onclick = async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) sendText(text, false);
  } catch {
    toast('이 주소에서는 붙여넣기 버튼을 쓸 수 없습니다. 입력창을 길게 눌러 붙여넣으세요', 4000);
    setIme(true);
  }
};
keepFocus($('keys'));
keepFocus($('imebar'));

// ================= 자주 쓰는 명령 =================

async function loadConfig() {
  try { config = await api('GET', '/config'); } catch {}
  renderSnippets();
}

function renderSnippets() {
  const box = $('snippets');
  box.innerHTML = '';
  for (const cmd of config.snippets) {
    const b = document.createElement('button');
    b.textContent = cmd;
    b.title = `${cmd} 입력 후 실행`;
    b.onclick = () => sendText(cmd, true);
    box.appendChild(b);
  }
  const edit = document.createElement('button');
  edit.className = 'edit';
  edit.textContent = '✎ 편집';
  edit.onclick = () => {
    $('sniptext').value = config.snippets.join('\n');
    $('snipdlg').returnValue = '';  // Esc로 닫으면 저장 안 되게
    $('snipdlg').showModal();
  };
  box.appendChild(edit);
}
keepFocus($('snippets'));

function setSnippets(on) {
  $('snippets').hidden = !on;
  $('snippettoggle').classList.toggle('on', on);
  LS.set('snippetsOn', on);
}
$('snippettoggle').onclick = () => setSnippets($('snippets').hidden);

$('snipdlg').addEventListener('close', async () => {
  if ($('snipdlg').returnValue !== 'ok') return;
  try {
    config = await api('PUT', '/config', { snippets: $('sniptext').value.split('\n') });
    renderSnippets();
  } catch (e) {
    toast(e.message);
  }
});

// ================= 파일 올리기 =================

async function uploadFiles(files) {
  const c = active();
  if (!c) return toast('먼저 세션을 선택하세요');
  const paths = [];
  for (const f of files) {
    toast(`업로드 중: ${f.name}`, 120000);
    const fd = new FormData();
    fd.append('file', f, f.name);
    try {
      paths.push((await api('POST', `/sessions/${enc(c.name)}/upload`, fd)).path);
    } catch (e) {
      return toast(`업로드 실패: ${e.message}`, 5000);
    }
  }
  toast(`업로드 완료 → ${paths.join(', ')}`, 4000);
  // 입력창에 경로를 넣어 두어 Claude 등에게 바로 전달할 수 있게
  setIme(true, false);
  if (ime.value && !/\s$/.test(ime.value)) ime.value += ' ';
  ime.value += paths.join(' ') + ' ';
  autoGrow();
}

$('attach').onclick = () => $('file').click();
$('file').onchange = () => {
  uploadFiles([...$('file').files]);
  $('file').value = '';
};

const termEl = $('term');
termEl.addEventListener('dragover', (e) => {
  if (!e.dataTransfer?.types.includes('Files')) return;
  e.preventDefault();
  termEl.classList.add('dragover');
});
termEl.addEventListener('dragleave', () => termEl.classList.remove('dragover'));
termEl.addEventListener('drop', (e) => {
  termEl.classList.remove('dragover');
  if (!e.dataTransfer?.files.length) return;
  e.preventDefault();
  uploadFiles([...e.dataTransfer.files]);
});

// ================= 복사 모드 =================

$('copymode').onclick = async () => {
  const c = active();
  if (!c) return toast('먼저 세션을 선택하세요');
  try {
    $('copytext').textContent = (await api('GET', `/sessions/${enc(c.name)}/capture?lines=3000`)).text;
  } catch (e) {
    return toast(e.message);
  }
  $('copydlg').showModal();
  $('copytext').scrollTop = $('copytext').scrollHeight;
};
$('copyall').onclick = async () => {
  const ok = await copyText($('copytext').textContent);
  toast(ok ? '전체 내용을 복사했습니다' : '복사 실패 · 직접 선택해서 복사하세요');
};
$('copyclose').onclick = () => $('copydlg').close();

// 대화상자의 '취소' 버튼
for (const b of document.querySelectorAll('dialog [data-close]')) {
  b.onclick = () => b.closest('dialog').close('cancel');
}

// ================= 새 세션 =================

$('new').onclick = async () => {
  $('newform').reset();
  $('newerr').textContent = '';
  const last = LS.get('newcmd', 'claude');
  const sel = $('newcmdsel');
  if ([...sel.options].some((o) => o.value === last && o.value !== 'custom')) {
    sel.value = last;
  } else {
    sel.value = 'custom';
    $('newcmd').value = last;
  }
  $('newcmd').hidden = sel.value !== 'custom';
  // 기본 작업 폴더: 지금 보고 있는 세션의 현재 폴더(PWD)
  const cur = sessions.find((s) => s.name === activeName);
  $('newdir').value = cur?.path || '';
  $('newname').placeholder = autoName($('newdir').value) || '폴더 이름으로 자동';
  $('newdlg').showModal();
  try {
    const dirs = await api('GET', '/dirs');
    $('dirlist').innerHTML = '';
    for (const d of dirs) {
      const o = document.createElement('option');
      o.value = d;
      $('dirlist').appendChild(o);
    }
  } catch {}
};

const autoName = (dir) => dir.replace(/\/+$/, '').split('/').pop().replace(/[.:]/g, '_');
$('newdir').addEventListener('input', () => { $('newname').placeholder = autoName($('newdir').value) || '폴더 이름으로 자동'; });
$('newcmdsel').onchange = () => {
  $('newcmd').hidden = $('newcmdsel').value !== 'custom';
  if (!$('newcmd').hidden) $('newcmd').focus();
};

$('newform').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return;
  e.preventDefault();
  const dir = $('newdir').value.trim();
  const name = $('newname').value.trim() || autoName(dir);
  if (!name) return ($('newerr').textContent = '세션 이름이나 작업 폴더를 입력하세요');
  const sel = $('newcmdsel').value;
  const command = sel === 'custom' ? $('newcmd').value.trim() : sel;
  try {
    await api('POST', '/sessions', { name, cwd: dir || null, command: command || null });
  } catch (err) {
    return ($('newerr').textContent = err.message);
  }
  LS.set('newcmd', command);
  $('newdlg').close();
  await refresh();
  openSession(name);
});

// ================= 알림 (웹 푸시) =================

let swReg = null;

async function initServiceWorker() {
  if ('serviceWorker' in navigator && isSecureContext) {
    try {
      swReg = await navigator.serviceWorker.register(`${base}/sw.js`, { scope: `${base}/` });
    } catch (e) {
      console.warn('service worker 등록 실패', e);
    }
    // 알림을 눌렀을 때 이미 열린 창이면 해당 세션으로 이동
    navigator.serviceWorker.addEventListener('message', (e) => {
      if (e.data?.open) openSession(e.data.open);
    });
  }
  updateNotifyButton();
}

async function currentSubscription() {
  if (!swReg || !('PushManager' in window)) return null;
  return swReg.pushManager.getSubscription().catch(() => null);
}

async function updateNotifyButton() {
  const sub = await currentSubscription();
  $('notify').textContent = sub ? '🔔' : '🔕';
  $('notify').classList.toggle('on', !!sub);
}

function b64ToBytes(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
}

$('notify').onclick = async () => {
  if (!isSecureContext) return toast('알림은 HTTPS 주소에서만 켤 수 있습니다', 5000);
  if (!swReg || !('PushManager' in window)) {
    return toast('이 브라우저는 알림을 지원하지 않습니다 (iPhone은 홈 화면에 추가한 앱에서만 가능)', 5000);
  }
  try {
    const sub = await currentSubscription();
    if (sub) {
      await api('POST', '/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {});
      await sub.unsubscribe();
      toast('알림을 껐습니다');
    } else {
      if ((await Notification.requestPermission()) !== 'granted') return toast('알림 권한이 거부되었습니다');
      const { key } = await api('GET', '/push/key');
      const s = await swReg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
      const j = s.toJSON();
      await api('POST', '/push/subscribe', { endpoint: j.endpoint, keys: j.keys });
      await api('POST', '/push/test');
      toast('알림을 켰습니다. 테스트 알림을 보냈습니다', 4000);
    }
  } catch (e) {
    toast('알림 설정 실패: ' + e.message, 5000);
  }
  updateNotifyButton();
};

// ================= 글자 크기 =================

function setFontSize(size) {
  fontSize = Math.max(8, Math.min(28, Math.round(size)));
  LS.set('fontSize', fontSize);
  for (const c of conns.values()) {
    c.term.options.fontSize = fontSize;
    fitConn(c);
  }
}
$('fontdown').onclick = () => setFontSize(fontSize - 1);
$('fontup').onclick = () => setFontSize(fontSize + 1);

// ================= 터치 제스처 (터미널 영역) =================
//  한 손가락 위/아래 스와이프 → tmux 히스토리 스크롤
//  두 손가락 핀치 → 글자 크기
//  화면 왼쪽 끝에서 오른쪽으로 스와이프 → 세션 목록

let touch = null;
const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
const cellHeight = (c) => c.el.clientHeight / c.term.rows || 16;

termEl.addEventListener('touchstart', (e) => {
  const name = e.target.closest('.pane')?.dataset.name;
  if (name && name !== activeName) activate(name, false);
  const t = e.touches;
  if (t.length === 2) {
    touch = { mode: 'pinch', startDist: dist(t), startSize: fontSize };
  } else if (t.length === 1) {
    touch = { mode: 'pending', x0: t[0].clientX, y0: t[0].clientY, y: t[0].clientY, acc: 0 };
  }
}, { passive: true, capture: true });

termEl.addEventListener('touchmove', (e) => {
  if (!touch) return;
  const t = e.touches;
  if (touch.mode !== 'pending') e.stopPropagation();  // xterm 자체 터치 스크롤과 겹치지 않게
  if (touch.mode === 'pinch' && t.length === 2) {
    e.preventDefault();
    const size = (touch.startSize * dist(t)) / touch.startDist;
    if (Math.round(size) !== fontSize) setFontSize(size);
    return;
  }
  if (t.length !== 1) return;
  const dx = t[0].clientX - touch.x0;
  const dy = t[0].clientY - touch.y0;
  if (touch.mode === 'pending' && Math.hypot(dx, dy) > 10) {
    touch.mode = touch.x0 < 24 && Math.abs(dx) > Math.abs(dy) ? 'edge' : 'scroll';
  }
  const c = active();
  if (touch.mode === 'edge') {
    e.preventDefault();
    if (dx > 60) {
      setDrawer(true);
      touch = null;
    }
  } else if (touch.mode === 'scroll' && c) {
    e.preventDefault();
    touch.acc += t[0].clientY - touch.y;  // 아래로 끌면(+) 과거 쪽으로
    touch.y = t[0].clientY;
    const lines = Math.trunc(touch.acc / cellHeight(c));
    if (lines) {
      touch.acc -= lines * cellHeight(c);
      c.raw({ type: 'scroll', lines });
      if (lines > 0) c.scrolled = true;
    }
  }
}, { passive: false, capture: true });

// PC 마우스 휠: xterm.js 기본 동작(대체 화면에서 ↑↓ 키 전송) 대신 스와이프와 같은 스크롤 처리
let wheelAcc = 0;
termEl.addEventListener('wheel', (e) => {
  const name = e.target.closest('.pane')?.dataset.name;
  const c = conns.get(name);
  if (!c) return;
  e.preventDefault();
  e.stopPropagation();
  const px = e.deltaMode === 1 ? e.deltaY * cellHeight(c) : e.deltaMode === 2 ? e.deltaY * c.el.clientHeight : e.deltaY;
  wheelAcc -= px;  // 휠을 위로(-) 굴리면 과거 쪽(+)
  const lines = Math.trunc(wheelAcc / cellHeight(c));
  if (lines) {
    wheelAcc -= lines * cellHeight(c);
    c.raw({ type: 'scroll', lines });
    if (lines > 0) c.scrolled = true;
  }
}, { passive: false, capture: true });

termEl.addEventListener('touchend', (e) => {
  // 스와이프/핀치였으면 탭(키보드 열기)으로 처리되지 않게
  if (touch && touch.mode !== 'pending') e.preventDefault();
  if (e.touches.length === 0) touch = null;
}, { capture: true });

// ================= 레이아웃 (세션 목록 / 분할) =================

const setDrawer = (open) => $('app').classList.toggle('drawer', open);

$('menu').onclick = () => {
  const app = $('app');
  if (narrow.matches) return setDrawer(!app.classList.contains('drawer'));
  LS.set('listCollapsed', app.classList.toggle('collapsed'));
  setTimeout(() => conns.forEach(fitConn), 0);
};
$('scrim').onclick = () => setDrawer(false);

// 세션 목록에서 왼쪽으로 스와이프 → 닫기
let drawerX = null;
const aside = document.querySelector('aside');
aside.addEventListener('touchstart', (e) => { drawerX = e.touches[0].clientX; }, { passive: true });
aside.addEventListener('touchmove', (e) => {
  if (drawerX !== null && e.touches[0].clientX - drawerX < -60) {
    setDrawer(false);
    drawerX = null;
  }
}, { passive: true });

$('split').onclick = () => {
  split = !split;
  LS.set('split', split);
  layout();
  if (split && conns.size < 2) toast('탭을 두 개 이상 열면 나란히 보입니다');
};
narrow.addEventListener('change', layout);

// 키보드가 올라오면 보이는 영역에 맞춰 높이 조정 (iOS Safari 대응)
if (window.visualViewport) {
  const vv = window.visualViewport;
  const fitViewport = () => {
    document.documentElement.style.setProperty('--app-h', `${vv.height}px`);
    window.scrollTo(0, 0);
  };
  vv.addEventListener('resize', fitViewport);
  vv.addEventListener('scroll', () => window.scrollTo(0, 0));
  fitViewport();
}

// ================= 기타 버튼 / 시작 =================

$('refresh').onclick = refresh;
$('logout').onclick = async () => {
  for (const name of [...conns.keys()]) closeSession(name);
  await fetch(`${base}/api/logout`, { method: 'POST' });
  toLogin();
};

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') checkConnections();
});
window.addEventListener('online', checkConnections);
window.addEventListener('pageshow', (e) => { if (e.persisted) checkConnections(); });

(async function init() {
  setIme(LS.get('imeOn', true), false);
  setSnippets(!!LS.get('snippetsOn', false));
  $('app').classList.toggle('collapsed', !!LS.get('listCollapsed', false));
  if (narrow.matches) ime.placeholder = '입력 후 Enter (줄바꿈: Shift+Enter)';

  await refresh();
  const exists = (n) => sessions.some((s) => s.name === n);
  // 이전에 열어 둔 탭 복원
  for (const name of LS.get('openTabs', [])) if (exists(name)) openSession(name);
  const last = LS.get('activeTab', null);
  if (last && conns.has(last)) activate(last, false);
  // 알림을 눌러서 들어온 경우 (?s=세션)
  const target = new URLSearchParams(location.search).get('s');
  if (target) {
    history.replaceState(null, '', `${base}/`);
    if (exists(target)) openSession(target);
  }
  if (narrow.matches && conns.size === 0) setDrawer(true);
  layout();

  loadConfig();
  initServiceWorker();
  setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 3000);
})();

// 白貓工具箱前端
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fileUrl = rel => '/files/' + rel.split('/').map(encodeURIComponent).join('/');

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3500);
}

// ---------------- 分頁 ----------------
function showTab(name) {
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  $$('.tab').forEach(s => s.classList.toggle('on', s.id === 'tab-' + name));
  if (name === 'flow') loadStatus();
  if (name === 'config') loadConfigs();
  if (name === 'jobs') refreshJobs();
}
$$('#tabs button').forEach(b => (b.onclick = () => showTab(b.dataset.tab)));

// ---------------- 角色圖庫 ----------------
const PAGE = 120;
let chars = [], shown = [], limit = PAGE, filter = 'all', selected = null;

// ID 各位數：[性別][職業 2 碼][版本][xxx][神解]，名稱在 config_id_labels.json
const FACETS = [
  { key: 'gender', title: '性別', pick: id => id[0] },
  { key: 'job', title: '職業', pick: id => id.slice(1, 3) },
  { key: 'version', title: '版本', pick: id => id[3] },
  { key: 'awaken', title: '神解', pick: id => id[7] },
];
let labels = {}, facetSel = {};
const facetName = (key, v) => (labels[key] || {})[v] || '';
const jobIcon = (job, cls = 'ico') => {
  const p = (labels.job_icons || {})[job];
  return p ? `<img class="${cls}" src="/gui/${p.split('/').map(encodeURIComponent).join('/')}" alt="" onerror="this.remove()">` : '';
};

async function loadChars() {
  [chars, labels] = await Promise.all([api('/api/characters'), api('/api/id_labels').catch(() => ({}))]);
  renderGrid();
}

function passBase(c, q) {
  if (q && !c.id.includes(q)) return false;
  if (filter === 'new') return c.new;
  if (filter === 'prefab') return c.prefab;
  if (filter === 'local') return c.dirs.length > 0;
  if (filter === 'rig') return c.rig;
  return true;
}
const passFacets = (c, skip) => FACETS.every(f => f.key === skip || !facetSel[f.key] || f.pick(c.id) === facetSel[f.key]);

function renderFacets(base) {
  $('#facets').innerHTML = FACETS.map(f => {
    // 數量 = 符合其他條件的角色裡，這一位是該值的數量
    const n = {};
    for (const c of base) if (passFacets(c, f.key)) { const v = f.pick(c.id); n[v] = (n[v] || 0) + 1; }
    const vals = [...new Set(chars.map(c => f.pick(c.id)))].sort();
    const btn = (v, text, cnt) => `<button data-k="${f.key}" data-v="${v}" class="${(facetSel[f.key] || '') === v ? 'on' : ''}"
      ${cnt === 0 ? 'disabled' : ''}>${text}${cnt === undefined ? '' : `<small>${cnt}</small>`}</button>`;
    return `<div class="chips"><b>${f.title}</b>${btn('', '全部')}${vals.map(v => {
      const name = facetName(f.key, v);
      const icon = f.key === 'job' ? jobIcon(v) : '';
      return btn(v, icon + (name ? `${esc(name)}<i>${v}</i>` : v), n[v] || 0);
    }).join('')}</div>`;
  }).join('');
}

function applyFilter() {
  const q = $('#q').value.trim();
  const base = chars.filter(c => passBase(c, q));
  renderFacets(base);
  shown = base.filter(c => passFacets(c));
  // 新角色排前面
  shown.sort((a, b) => (b.new - a.new) || (a.id < b.id ? 1 : -1));
}

function cardHtml(c) {
  const tags = [c.new && '<span class="tag new">新</span>', c.rig && '<span class="tag rig">GLB</span>',
    !c.rig && c.dirs.length && '<span class="tag">已下載</span>', !c.prefab && '<span class="tag">無模型</span>']
    .filter(Boolean).join('');
  const img = c.bust ? `<img loading="lazy" src="${fileUrl(`index_work/bust_gallery/${c.id}.png`)}" alt="">` : '<span>沒有圖</span>';
  return `<button class="card${c.id === selected ? ' sel' : ''}" data-id="${c.id}">
    <div class="img">${img}</div><div class="meta"><span>${jobIcon(c.id.slice(1, 3), 'ico sm')}${c.id}</span><span class="tags">${tags}</span></div></button>`;
}

function renderGrid() {
  applyFilter();
  $('#grid').innerHTML = shown.slice(0, limit).map(cardHtml).join('');
  $('#count').textContent = `${shown.length} / ${chars.length} 隻`;
  $('#more').textContent = shown.length > limit ? '往下捲載入更多…' : '';
}

$('#q').addEventListener('input', () => { limit = PAGE; renderGrid(); });
$('#q').addEventListener('keydown', e => {
  if (e.key === 'Enter' && /^\d{8}$/.test($('#q').value.trim())) selectChar($('#q').value.trim());
});
$$('#filters button').forEach(b => (b.onclick = () => {
  filter = b.dataset.f;
  $$('#filters button').forEach(x => x.classList.toggle('on', x === b));
  limit = PAGE;
  renderGrid();
}));
$('#facets').onclick = e => {
  const b = e.target.closest('button[data-k]');
  if (!b) return;
  facetSel[b.dataset.k] = b.dataset.v;
  limit = PAGE;
  renderGrid();
};
$('#grid').onclick = e => {
  const card = e.target.closest('.card');
  if (card) selectChar(card.dataset.id);
};
new IntersectionObserver(es => {
  if (es[0].isIntersecting && shown.length > limit) {
    limit += PAGE;
    $('#grid').insertAdjacentHTML('beforeend', shown.slice(limit - PAGE, limit).map(cardHtml).join(''));
    $('#more').textContent = shown.length > limit ? '往下捲載入更多…' : '';
  }
}).observe($('#more'));

// ---------------- 角色詳細 ----------------
let viewer = null, viewerMod = null, anims = null, audio = null;

async function selectChar(id) {
  selected = id;
  $$('.card').forEach(c => c.classList.toggle('sel', c.dataset.id === id));
  const d = await api('/api/char/' + id);
  if (selected !== id) return;
  const c = chars.find(x => x.id === id) || {};
  const glbs = d.dirs.flatMap(x => x.glb).sort((a, b) => b.includes('_rig') - a.includes('_rig'));
  const imgs = d.dirs.flatMap(x => x.images);
  const voices = d.dirs.flatMap(x => x.voices);

  $('#detail').innerHTML = `
    <div class="d-head">
      ${d.bust ? `<img src="${fileUrl(d.bust)}" alt="">` : ''}
      <div>
        <h2>${id}</h2>
        <div class="muted small">${FACETS.map(f => `${f.title} ${f.pick(id)}${facetName(f.key, f.pick(id)) ? '（' + esc(facetName(f.key, f.pick(id))) + '）' : ''}`).join('・')}</div>
        <div class="tags">${c.new ? '<span class="tag new">新角色</span>' : ''}
          ${d.prefab ? '<span class="tag">索引裡有模型</span>' : '<span class="tag">索引裡沒有模型</span>'}</div>
      </div>
    </div>
    <div class="row">
      <button id="actAll">一鍵下載（圖片 + 語音 + GLB）</button>
      <button id="actRig" class="ghost" ${d.prefab ? '' : 'disabled'}>只匯出 GLB</button>
    </div>
    <details class="opts">
      <summary class="muted">GLB 動作選項</summary>
      <label>動作 <input id="optAnims" type="text" placeholder="空白 = 預設 00000000-00000019"></label>
      <input id="animSearch" type="text" placeholder="搜尋共用動作編號，點一下加入（例如 rezero、0215）">
      <div id="animHits" class="anim-hits"></div>
      <label><input id="optNoSkill" type="checkbox"> 不自動找技能動作</label>
      <label><input id="optIncM" type="checkbox"> 一併輸出 body_m 小模型</label>
      <label><input id="optHidden" type="checkbox"> 一併輸出預設隱藏的網格（替換手型、變身）</label>
      <label><input id="optUpd" type="checkbox"> 先更新 Character / Action 索引</label>
    </details>
    <div class="d-sec">
      <h4>3D 預覽</h4>
      ${glbs.length ? `
        ${glbs.length > 1 ? `<select id="glbSel">${glbs.map(g => `<option value="${esc(g)}">${esc(g)}</option>`).join('')}</select>` : ''}
        <div id="viewer" class="viewer"><div class="msg">載入中…</div></div>
        <div class="vctl">
          <div id="animList" class="anim-list"></div>
          <div class="row">
            <button id="vPause" class="ghost">暫停</button>
            <button id="vStop" class="ghost">T 字姿勢</button>
            <select id="vSpeed"><option>0.25</option><option>0.5</option><option selected>1</option><option>2</option></select>
            <label><input id="vLoop" type="checkbox" checked> 循環</label>
            <label><input id="vBones" type="checkbox"> 顯示骨頭</label>
            <label><input id="vFollow" type="checkbox" checked> 鏡頭跟隨</label>
          </div>
          <div class="row"><input id="vTime" type="range" min="0" max="1" step="0.001" value="0" style="flex:1"><span id="vTimeLbl" class="muted">0.00s</span></div>
        </div>` : `<p class="muted">還沒有 GLB。${d.prefab ? '按上面的「只匯出 GLB」。' : ''}</p>`}
    </div>
    ${imgs.length ? `<div class="d-sec"><h4>圖片</h4><div class="thumbs">${imgs.map(i =>
      `<a href="${fileUrl(i)}" target="_blank"><img loading="lazy" src="${fileUrl(i)}" title="${esc(i)}"></a>`).join('')}</div></div>` : ''}
    ${voices.length ? `<div class="d-sec"><h4>語音（${voices.length}）</h4><div class="voices">${voices.map(v =>
      `<button data-v="${esc(v)}">${esc(v.split('/').pop().replace('.wav', ''))}</button>`).join('')}</div></div>` : ''}
    <div class="d-sec"><h4>資料夾</h4>${d.dirs.length ? d.dirs.map(x =>
      `<div class="row"><span class="path">! wcat/${esc(x.path)}</span><button class="ghost" data-open="${esc(x.path)}">開啟</button></div>`).join('')
      : '<p class="muted">還沒下載過</p>'}</div>`;

  $('#actAll').onclick = () => run('char_all', [id], { with_rig: d.prefab, ...rigOpts() });
  $('#actRig').onclick = () => run('rig', [id], rigOpts());
  $('#animSearch').oninput = searchAnims;
  $$('#detail [data-open]').forEach(b => (b.onclick = () => api('/api/open', { path: b.dataset.open }).catch(e => toast(e.message))));
  $$('#detail [data-v]').forEach(b => (b.onclick = () => playVoice(b)));
  if (glbs.length) {
    await setupViewer();
    loadGlb(glbs[0]);
    if ($('#glbSel')) $('#glbSel').onchange = e => loadGlb(e.target.value);
  }
}

function rigOpts() {
  return {
    anims: $('#optAnims')?.value || '', no_skill: $('#optNoSkill')?.checked,
    include_m: $('#optIncM')?.checked, include_hidden: $('#optHidden')?.checked, update_index: $('#optUpd')?.checked,
  };
}

async function searchAnims() {
  const q = $('#animSearch').value.trim().toLowerCase();
  if (!q) return ($('#animHits').innerHTML = '');
  if (!anims) anims = await api('/api/anims');
  const hits = anims.filter(a => a.toLowerCase().includes(q)).slice(0, 60);
  $('#animHits').innerHTML = hits.map(h => `<button data-a="${esc(h)}">${esc(h)}</button>`).join('')
    || '<span class="muted">找不到</span>';
  $$('#animHits [data-a]').forEach(b => (b.onclick = () => {
    const el = $('#optAnims');
    const cur = el.value.split(/[\s,]+/).filter(Boolean);
    if (!cur.length) cur.push('00000000-00000019');
    if (!cur.includes(b.dataset.a)) cur.push(b.dataset.a);
    el.value = cur.join(' ');
  }));
}

function playVoice(btn) {
  if (audio) audio.pause();
  $$('#detail [data-v]').forEach(b => b.classList.remove('playing'));
  audio = new Audio(fileUrl(btn.dataset.v));
  btn.classList.add('playing');
  audio.onended = () => btn.classList.remove('playing');
  audio.play();
}

async function setupViewer() {
  viewerMod ??= await import('./viewer.js');
  const el = $('#viewer');
  if (viewer) {
    viewer.renderer.setAnimationLoop(null);
    viewer.renderer.dispose();
  }
  viewer = new viewerMod.Viewer(el);
  const lbl = $('#vTimeLbl'), slider = $('#vTime');
  let dragging = false;
  slider.onpointerdown = () => (dragging = true);
  slider.onpointerup = () => (dragging = false);
  slider.oninput = () => viewer.seek(+slider.value);
  viewer.onTick = (t, dur) => {
    slider.max = dur;
    if (!dragging) slider.value = t;
    lbl.textContent = `${t.toFixed(2)} / ${dur.toFixed(2)}s`;
  };
  $('#vPause').onclick = () => {
    viewer.paused = !viewer.paused;
    $('#vPause').textContent = viewer.paused ? '播放' : '暫停';
  };
  $('#vStop').onclick = () => { viewer.stop(); $$('#animList button').forEach(b => b.classList.remove('on')); };
  $('#vSpeed').onchange = e => (viewer.speed = +e.target.value);
  $('#vLoop').onchange = e => viewer.setLoop(e.target.checked);
  $('#vBones').onchange = e => viewer.setBones(e.target.checked);
  $('#vFollow').onchange = e => { viewer.follow = e.target.checked; if (!viewer.follow) viewer.frame(); };
}

async function loadGlb(rel) {
  const msg = $('#viewer .msg');
  msg.textContent = '載入中…';
  msg.hidden = false;
  try {
    const list = await viewer.load(fileUrl(rel) + '?t=' + Date.now());
    msg.hidden = true;
    $('#animList').innerHTML = list.map(a =>
      `<button data-n="${esc(a.name)}" title="${a.duration.toFixed(2)} 秒">${esc(a.name.replace(/^anm_/, ''))}</button>`).join('')
      || '<span class="muted">這個檔案沒有動作</span>';
    $$('#animList button').forEach(b => (b.onclick = () => {
      $$('#animList button').forEach(x => x.classList.toggle('on', x === b));
      viewer.paused = false;
      $('#vPause').textContent = '暫停';
      viewer.play(b.dataset.n);
    }));
    const idle = $('#animList button');
    if (idle) idle.click();
  } catch (e) {
    msg.textContent = '載入失敗：' + e.message;
  }
}

// ---------------- 執行工作 ----------------
async function run(task, ids, options) {
  try {
    const job = await api('/api/run', { task, ids, options });
    toast(`已排入：${job.title}`);
    currentJob = job.id;
    logFrom = 0;
    $('#jobLog').textContent = '';
    refreshJobs();
  } catch (e) {
    toast('無法執行：' + e.message);
  }
}

$$('[data-run]').forEach(b => (b.onclick = () => {
  const ids = b.dataset.ids ? $('#' + b.dataset.ids).value.split(/[\s,]+/).filter(Boolean) : [];
  run(b.dataset.run, ids, b.dataset.norig ? { with_rig: false } : {});
}));

// ---------------- 工作清單 / 輸出 ----------------
let currentJob = null, logFrom = 0, jobs = [], lastActive = 0, pollTimer = null;
const ST = { queued: '排隊中', running: '執行中', done: '完成', failed: '失敗', cancelled: '已取消' };

async function refreshJobs() {
  jobs = await api('/api/jobs');
  const active = jobs.filter(j => j.status === 'running' || j.status === 'queued').length;
  $('#jobBadge').hidden = !active;
  $('#jobBadge').textContent = active;
  if (active < lastActive) { // 有工作剛結束：更新角色清單與目前角色
    await loadChars();
    if (selected) selectChar(selected);
  }
  lastActive = active;
  if (currentJob === null && jobs.length) currentJob = jobs[0].id;
  $('#jobList').innerHTML = jobs.map(j => `<li data-j="${j.id}" class="${j.id === currentJob ? 'sel' : ''}">
    <b>#${j.id}</b> ${esc(j.title)}<small class="st-${j.status}">${ST[j.status]}
    ${j.started ? '・' + new Date(j.started * 1000).toLocaleTimeString() : ''}</small></li>`).join('')
    || '<li class="muted">還沒有工作</li>';
  $$('#jobList [data-j]').forEach(li => (li.onclick = () => {
    currentJob = +li.dataset.j;
    logFrom = 0;
    $('#jobLog').textContent = '';
    refreshJobs();
  }));
  if (currentJob !== null) await pullLog();
  clearTimeout(pollTimer);
  pollTimer = setTimeout(refreshJobs, active ? 1000 : 4000);
}

async function pullLog() {
  const j = await api(`/api/job/${currentJob}?since=${logFrom}`);
  $('#jobTitle').textContent = `#${j.id} ${j.title}`;
  $('#jobStatus').textContent = ST[j.status];
  $('#jobStatus').className = 'st-' + j.status;
  $('#jobCancel').hidden = !(j.status === 'running' || j.status === 'queued');
  if (j.log.length) {
    const el = $('#jobLog');
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent += j.log.join('\n') + '\n';
    logFrom = j.from + j.log.length;
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
}
$('#jobCancel').onclick = () => api(`/api/job/${currentJob}/cancel`, {}).then(refreshJobs);

// ---------------- 流程狀態 ----------------
async function loadStatus() {
  const s = await api('/api/status');
  const item = (k, v) => `<span>${k}：<b>${v ?? '—'}</b></span>`;
  $('#statusBox').innerHTML = [
    item('Python', s.python),
    item('AssetStudio CLI', s.assetstudio ? '有' : '找不到'),
    item('Card 索引', s.card_index),
    item('Character 索引', s.character_index),
    item('Action 索引', s.action_index),
    item('新角色', s.new_ids),
    item('bust 圖', s.busts),
  ].join('');
}

// ---------------- 設定檔 ----------------
let configs = {};
async function loadConfigs() {
  configs = await api('/api/configs');
  const sel = $('#cfgName'), cur = sel.value;
  sel.innerHTML = Object.keys(configs).map(n => `<option>${n}</option>`).join('');
  if (cur && configs[cur] !== undefined) sel.value = cur;
  $('#cfgText').value = configs[sel.value] || '';
  $('#cfgMsg').textContent = '';
}
$('#cfgName').onchange = () => { $('#cfgText').value = configs[$('#cfgName').value]; $('#cfgMsg').textContent = ''; };
$('#cfgSave').onclick = async () => {
  const name = $('#cfgName').value, text = $('#cfgText').value;
  try {
    JSON.parse(text);
    await api('/api/config', { name, text });
    configs[name] = text;
    $('#cfgMsg').textContent = '已儲存';
    if (name === 'config_id_labels.json') { labels = JSON.parse(text); renderGrid(); }
  } catch (e) {
    $('#cfgMsg').textContent = '沒存：' + e.message;
  }
};

const fromHash = () => {
  const hash = location.hash.slice(1);
  if (/^\d{8}$/.test(hash)) { showTab('chars'); selectChar(hash); }
};
window.addEventListener('hashchange', fromHash);
loadChars().then(fromHash);
refreshJobs();

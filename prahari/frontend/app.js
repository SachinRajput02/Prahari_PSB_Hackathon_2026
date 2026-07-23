// PRAHARI dashboard — talks to the FastAPI backend over same-origin /api.

//frontend/app.js
const $ = id => document.getElementById(id);
const API = '';                      // same origin (served by FastAPI)

const state = {
  session_id: null,
  action: 'transfer',
  actions: [],
  signals: {},                       // the 11-feature vector sent to the model
  lastTouch: Date.now(),
  decay: 0,
  ctq: 99,
};

// UI -> feature vector
function readSignals() {
  const dev = $('s_dev').checked;
  const ipv = document.querySelector('#s_ip button.on').dataset.v;
  return {
    new_device: dev ? 1 : 0,
    device_age_days: dev ? 3 : 240,
    impossible_travel: $('s_geo').checked ? 1 : 0,
    sim_swap: $('s_sim').checked ? 1 : 0,
    odd_hour: $('s_hour').checked ? 1 : 0,
    recovery_attempts: +$('s_rec').value,
    behavioral_mismatch: +$('s_bio').value / 100,
    amount_zscore: +$('s_amt').value / 10,
    ip_vpn: ipv === 'vpn' ? 1 : 0,
    ip_bad: ipv === 'bad' ? 1 : 0,
    failed_auth_24h: 0,
  };
}

function setSignals(s) {
  $('s_dev').checked = !!s.new_device;
  $('s_geo').checked = !!s.impossible_travel;
  $('s_sim').checked = !!s.sim_swap;
  $('s_hour').checked = !!s.odd_hour;
  $('s_rec').value = s.recovery_attempts || 0;
  $('s_bio').value = Math.round((s.behavioral_mismatch || 0) * 100);
  $('s_amt').value = Math.round((s.amount_zscore || 0) * 10);
  const ip = s.ip_bad ? 'bad' : s.ip_vpn ? 'vpn' : 'clean';
  document.querySelectorAll('#s_ip button').forEach(b => b.classList.toggle('on', b.dataset.v === ip));
  syncLabels();
}

function syncLabels() {
  $('rec_v').textContent = $('s_rec').value;
  $('bio_v').textContent = $('s_bio').value + '%';
  $('amt_v').textContent = (+$('s_amt').value / 10).toFixed(1) + 'σ';
}

const bandColor = b => b === 'trusted' ? 'var(--green)' : b === 'elevated' ? 'var(--warn)' : 'var(--red)';
const bandText = b => b === 'trusted' ? 'Trusted' : b === 'elevated' ? 'Elevated risk' : 'High risk';

async function api(path, body) {
  const r = await fetch(API + path, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

// ---------- core scoring ----------
let scoring = false;
async function score(log = true) {
  if (!state.session_id) return;
  state.signals = readSignals();
  const idle = (Date.now() - state.lastTouch) / 1000;
  scoring = true;
  let r;
  try {
    r = await api('/api/score', {
      session_id: state.session_id, signals: state.signals,
      action: state.action, idle_seconds: idle,
    });
  } catch (e) { scoring = false; return; }
  scoring = false;
  render(r);
  if (log) { refreshMetrics(); refreshEvents(); }
}

function render(r) {
  state.ctq = r.ctq;
  const col = bandColor(r.band);
  // gauge
  $('ctq').textContent = r.ctq;
  $('ctq').style.color = col;
  $('band').textContent = bandText(r.band);
  $('band').style.color = col;
  $('needle').style.transform = 'rotate(' + (-90 + r.ctq / 100 * 180) + 'deg)';
  $('mlrow').textContent = r.policy_ceiling != null
    ? `model ${r.ml_trust} · policy ceiling ${r.policy_ceiling}`
    : `model P(genuine) → ${r.ml_trust}`;
  // decay bar
  $('decaybar').style.width = (100 - r.decay * 100).toFixed(0) + '%';
  $('decaytxt').textContent = r.decay < 0.05 ? 'fresh' : r.decay < 0.4 ? 'decaying' : 'stale — re-auth';

  // reasons
  const rc = $('reasons');
  if (!r.reasons.length) {
    rc.innerHTML = '<div class="empty">No active risk signals.</div>';
  } else {
    const max = r.reasons[0].impact;
    rc.innerHTML = r.reasons.map(x => {
      const pct = Math.round(x.impact / max * 100);
      const c = x.impact > 1.5 ? 'var(--red)' : x.impact > 0.6 ? 'var(--warn)' : 'var(--amber)';
      return `<div class="reason"><div class="rl"><b>${x.label}</b><span>−${x.impact.toFixed(2)}</span></div>
              <div class="rbar"><i style="width:${pct}%;background:${c}"></i></div></div>`;
    }).join('');
  }

  // verdict
  const d = r.decision;
  $('verdict').className = 'verdict v-' + d.kind;
  $('vic').textContent = d.kind === 'silent' ? '✓' : d.kind === 'soft' ? '◐' : '⚠';
  $('vt').textContent = d.kind === 'silent' ? 'Silent — access granted'
    : d.kind === 'soft' ? 'Step-up — soft challenge' : 'Step-up — strong verification';
  $('vd').textContent = d.message;
  $('policy').innerHTML = (r.policy_hits || []).map(p => `<span>${p.rule}</span>`).join('');
}

// ---------- actions ----------
function renderActions() {
  const row = $('actrow'); row.innerHTML = '';
  Object.entries(state.actions).forEach(([id, a]) => {
    const b = document.createElement('button');
    b.className = id === state.action ? 'on' : '';
    b.innerHTML = a.label + '<span class="req">≥' + a.req + '</span>';
    b.onclick = () => { state.action = id; renderActions(); touch(); score(); };
    row.appendChild(b);
  });
}

// ---------- presets ----------
const PRESETS = {
  genuine: { behavioral_mismatch: 0.05 },
  ato: { new_device: 1, impossible_travel: 1, odd_hour: 1, behavioral_mismatch: 0.7, ip_bad: 1, amount_zscore: 2.2 },
  recovery: { new_device: 1, sim_swap: 1, recovery_attempts: 3, behavioral_mismatch: 0.5, ip_vpn: 1 },
  insider: { odd_hour: 1, behavioral_mismatch: 0.30, amount_zscore: 0.8 },
};
const PRESET_ACTION = { genuine: 'transfer', ato: 'transfer', recovery: 'recovery', insider: 'admin' };

async function applyPreset(p) {
  setSignals(PRESETS[p]);
  state.action = PRESET_ACTION[p];
  renderActions();
  touch();
  await score();
  // auto-scan the graph; compromised sessions get pulled into the ring
  await runScan(state.ctq < 50);
}

// ---------- graph ----------
async function runScan(linkRing) {
  const r = await api('/api/graph/scan', { user_id: 'U1000', link_ring: !!linkRing });
  drawGraph(r);
}

function drawGraph(r) {
  const svg = $('graphsvg');
  const cx = 160, cy = 82;
  const others = r.nodes.filter(n => n.kind !== 'self');
  const self = r.nodes.find(n => n.kind === 'self') || r.nodes[0];
  const pos = {};
  if (self) pos[self.id] = [cx, cy];
  others.forEach((n, i) => {
    const a = (i / Math.max(1, others.length)) * Math.PI * 2 - Math.PI / 2;
    pos[n.id] = [cx + Math.cos(a) * 95, cy + Math.sin(a) * 60];
  });
  let h = '';
  r.edges.forEach(e => {
    const A = pos[e.source], B = pos[e.target];
    if (!A || !B) return;
    const suspect = r.ring && (e.source !== self.id && e.target !== self.id || e.via === 'device' || e.via === 'beneficiary');
    h += `<line x1="${A[0]}" y1="${A[1]}" x2="${B[0]}" y2="${B[1]}" stroke="${r.ring ? '#DC4B3E' : '#C2CCDA'}" stroke-width="${r.ring ? 1.8 : 1.2}" opacity="${r.ring ? .8 : .6}"/>`;
  });
  r.nodes.forEach(n => {
    const [x, y] = pos[n.id];
    const fill = n.kind === 'self' ? '#E8821E' : n.suspect ? '#DC4B3E' : '#7A8CA6';
    const rad = n.kind === 'self' ? 15 : 11;
    h += `<circle cx="${x}" cy="${y}" r="${rad}" fill="${fill}"/>`;
    h += `<text x="${x}" y="${y + rad + 11}" fill="#5E708A" font-size="9" text-anchor="middle">${n.label.length > 14 ? n.label.slice(0, 13) + '…' : n.label}</text>`;
  });
  svg.innerHTML = h;
  const g = $('gverdict');
  g.className = 'gverdict ' + (r.ring ? 'gv-ring' : 'gv-clean');
  g.textContent = r.verdict;
}

// ---------- metrics + events ----------
async function refreshMetrics() {
  const m = await (await fetch(API + '/api/metrics')).json();
  $('m_ctq').textContent = state.ctq;
  $('m_silent').textContent = m.silent_pct + '%';
  $('m_step').textContent = m.stepups;
  $('m_block').textContent = m.blocked;
  $('m_events').textContent = m.events;
}

async function refreshEvents() {
  const ev = await (await fetch(API + '/api/events?limit=18')).json();
  $('logbody').innerHTML = ev.map(e => {
    const t = new Date(e.ts * 1000).toLocaleTimeString();
    const reasons = JSON.parse(e.reasons || '[]');
    const top = reasons.length ? reasons[0].label : '—';
    const col = e.ctq >= 70 ? 'var(--green)' : e.ctq >= 40 ? 'var(--warn)' : 'var(--red)';
    const al = (state.actions[e.action] || {}).label || e.action;
    return `<tr><td>${t}</td><td class="c" style="color:${col}">${Math.round(e.ctq)}</td><td>${al}</td>
            <td><span class="tag ${e.decision}">${e.decision}</span></td><td style="color:var(--muted)">${top}</td></tr>`;
  }).join('');
}

// ---------- trust decay (continuous validation) ----------
function touch() { state.lastTouch = Date.now(); }
['click', 'input', 'change'].forEach(ev => document.addEventListener(ev, touch));
setInterval(() => {
  const idle = (Date.now() - state.lastTouch) / 1000;
  const d = Math.min(1, Math.max(0, (idle - 8) / 40));
  if (Math.abs(d - state.decay) > 0.02) {
    state.decay = d;
    // re-score silently to reflect decayed trust (continuous monitoring)
    if (!scoring) score(false);
  }
}, 2000);

// ---------- wiring ----------
function bindControls() {
  ['s_dev', 's_geo', 's_sim', 's_hour'].forEach(id => $(id).addEventListener('change', () => { touch(); score(); }));
  ['s_rec', 's_bio', 's_amt'].forEach(id => {
    $(id).addEventListener('input', syncLabels);
    $(id).addEventListener('change', () => { touch(); score(); });
  });
  document.querySelectorAll('#s_ip button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#s_ip button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); touch(); score();
  }));
  document.querySelectorAll('.preset').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.preset)));
  $('scan').addEventListener('click', () => runScan(state.ctq < 50));
}

async function boot() {
  bindControls();
  syncLabels();
  const s = await api('/api/session', {});
  state.session_id = s.session_id;
  state.actions = s.actions;
  $('sid').textContent = s.session_id;
  $('userpill').innerHTML = `${s.name} · <b>${s.kyc_status}</b>`;
  renderActions();
  await score();
  await runScan(false);
}
boot();

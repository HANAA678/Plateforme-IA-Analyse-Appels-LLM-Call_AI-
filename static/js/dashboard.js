/* ============================================================
   CallAI v2 — dashboard.js
   Charge GET /api/dashboard?period=...
   Injecte : KPIs, scores équipes, conformité, types, derniers appels
   ============================================================ */

document.addEventListener('DOMContentLoaded', loadDashboard);

async function loadDashboard() {
  const period = document.getElementById('periodSelect').value;

  try {
    const res  = await fetch(`/api/dashboard?period=${period}`);
    if (!res.ok) throw new Error('Erreur API dashboard');
    const d = await res.json();

    renderKPIs(d);
    renderTeams(d.scores_by_team);
    renderCompliance(d.compliance_breakdown, d.total_calls);
    renderCallTypes(d.calls_by_type);
    renderRecentCalls(d.recent_calls);
  } catch (e) {
    showToast('Impossible de charger le dashboard.', 'error');
  }
}

// ── KPIs ──────────────────────────────────────────────────────
function renderKPIs(d) {
  document.getElementById('kpiCalls').textContent      = fmt(d.total_calls);
  document.getElementById('kpiCallsSub').textContent   = '';

  const score = d.avg_score ? d.avg_score.toFixed(1) : '—';
  document.getElementById('kpiScore').textContent      = score + '/100';
  document.getElementById('kpiScoreSub').textContent   = '';

  const rate = d.compliance_rate ? d.compliance_rate.toFixed(1) : '—';
  document.getElementById('kpiCompliance').textContent    = rate + '%';
  document.getElementById('kpiComplianceSub').textContent = '';

  document.getElementById('kpiAlerts').textContent    = d.critical_alerts ?? '—';
  document.getElementById('kpiAlertsSub').innerHTML   =
    d.critical_alerts > 0
      ? `<a href="/alerts" style="color:#791F1F;font-size:10px">${d.critical_alerts} non traitée(s)</a>`
      : '<span style="color:#27500A">Aucune</span>';
}

// ── Score par équipe ──────────────────────────────────────────
const TEAM_COLORS = ['#1D9E75','#378ADD','#D85A30','#7F77DD','#EF9F27'];

function renderTeams(teams) {
  const el = document.getElementById('teamsRows');
  if (!teams || teams.length === 0) {
    el.innerHTML = '<div class="row-c" style="color:#888;font-size:11px">Aucune donnée.</div>';
    return;
  }

  const max = Math.max(...teams.map(t => t.avg_score || 0), 1);

  el.innerHTML = teams.map((t, i) => {
    const color = TEAM_COLORS[i % TEAM_COLORS.length];
    const pct   = ((t.avg_score || 0) / 100 * 100).toFixed(0);
    const score = t.avg_score ? t.avg_score.toFixed(0) : '—';
    return `
      <div class="row-c">
        <span style="min-width:80px;font-size:12px">${escHtml(t.team_name)}</span>
        <div class="pbar">
          <div class="pb" style="width:${pct}%;background:${color}"></div>
        </div>
        <span style="min-width:24px;text-align:right;font-weight:600;color:${color}">${score}</span>
      </div>`;
  }).join('');
}

// ── Répartition conformité ────────────────────────────────────
function renderCompliance(breakdown, total) {
  const el = document.getElementById('complianceRows');
  if (!breakdown || total === 0) {
    el.innerHTML = '<div class="row-c" style="color:#888;font-size:11px">Aucune donnée.</div>';
    return;
  }

  const conforme    = breakdown['conforme']      || 0;
  const partiel     = breakdown['partiel']       || 0;
  const nonConforme = breakdown['non-conforme']  || 0;
  const positif     = breakdown['positif']       || 0; // sentiment_client

  const pct = v => total > 0 ? ((v / total) * 100).toFixed(0) + '%' : '—';

  el.innerHTML = `
    <div class="row-c">
      <span style="flex:1;font-size:12px">Score ≥ 80 (Conforme)</span>
      <span class="badge-c bg">${pct(conforme)}</span>
    </div>
    <div class="row-c">
      <span style="flex:1;font-size:12px">Score 60–79 (Partiel)</span>
      <span class="badge-c ba">${pct(partiel)}</span>
    </div>
    <div class="row-c">
      <span style="flex:1;font-size:12px">Score &lt; 60 (Critique)</span>
      <span class="badge-c br">${pct(nonConforme)}</span>
    </div>
    <div class="row-c">
      <span style="flex:1;font-size:12px">Sentiment client positif</span>
      <span class="badge-c bg">${pct(positif)}</span>
    </div>`;
}

// ── Appels par type ───────────────────────────────────────────
const TYPE_COLORS = {
  reclamation:  '#E24B4A',
  information:  '#378ADD',
  commercial:   '#1D9E75',
  technique:    '#7F77DD',
};
const TYPE_LABELS = {
  reclamation: 'Réclamation',
  information: 'Information',
  commercial:  'Commercial',
  technique:   'Technique',
};

function renderCallTypes(types) {
  const el = document.getElementById('callTypeRows');
  if (!types || Object.keys(types).length === 0) {
    el.innerHTML = '<div class="row-c" style="color:#888;font-size:11px">Aucune donnée.</div>';
    return;
  }

  const max = Math.max(...Object.values(types), 1);

  el.innerHTML = Object.entries(types)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => {
      const color = TYPE_COLORS[type] || '#888';
      const label = TYPE_LABELS[type] || type;
      const pct   = ((count / max) * 100).toFixed(0);
      return `
        <div class="row-c">
          <span style="flex:1;font-size:12px">${label}</span>
          <div class="pbar">
            <div class="pb" style="width:${pct}%;background:${color}"></div>
          </div>
          <span style="font-size:11px;min-width:30px;text-align:right">${count}</span>
        </div>`;
    }).join('');
}

// ── Derniers appels ───────────────────────────────────────────
const COMPLIANCE_BADGE = {
  'conforme':     'bg',
  'partiel':      'ba',
  'non-conforme': 'br',
};
const CALL_TYPE_BADGE = {
  reclamation: 'br',
  commercial:  'bb',
  technique:   'bp',
  information: 'bgr',
};
const AVA_COLORS = [
  { bg: '#E6F1FB', color: '#0C447C' },
  { bg: '#FAEEDA', color: '#633806' },
  { bg: '#FCEBEB', color: '#791F1F' },
  { bg: '#E1F5EE', color: '#085041' },
  { bg: '#EEEDFE', color: '#3C3489' },
];

function renderRecentCalls(calls) {
  const el = document.getElementById('recentCallsRows');
  if (!calls || calls.length === 0) {
    el.innerHTML = '<div class="row-c" style="color:#888;font-size:11px">Aucun appel récent.</div>';
    return;
  }

  el.innerHTML = calls.map((c, i) => {
    const ava     = AVA_COLORS[i % AVA_COLORS.length];
    const compBdg = COMPLIANCE_BADGE[c.compliance] || 'bgr';
    const typeBdg = CALL_TYPE_BADGE[c.call_type]   || 'bgr';
    const compLbl = c.compliance === 'non-conforme' ? 'Non-conf.' : capitalize(c.compliance || '—');
    const typeLbl = TYPE_LABELS[c.call_type] || c.call_type;
    const score   = c.score_total ?? '—';
    const scoreBdg = scoreClass(c.score_total);
    const dateStr = c.called_at ? formatDate(c.called_at) : '—';
    const dur     = c.duration_seconds ? formatDuration(c.duration_seconds) : '';

    // Alerte si score < 60
    const alertBadge = c.score_total < 60
      ? `<a href="/alerts" class="badge-c br" style="margin-left:4px;text-decoration:none">⚠ Alerte</a>`
      : '';

    return `
      <div class="row-c">
        <div class="ava" style="background:${ava.bg};color:${ava.color}">
          ${escHtml(c.agent_initials || '??')}
        </div>
        <span style="flex:1;font-size:12px">${escHtml(c.agent_name || '—')}</span>
        <span style="font-size:10px;color:#888;white-space:nowrap">${dateStr}${dur ? ' · ' + dur : ''}</span>
        <span class="badge-c ${scoreBdg}">${score}</span>
        <span class="badge-c ${compBdg}" style="margin-left:4px">${compLbl}</span>
        <span class="badge-c ${typeBdg}" style="margin-left:4px">${typeLbl}</span>
        ${alertBadge}
        <a href="/rapport?call_id=${c.call_id}"
           style="margin-left:8px;font-size:11px;color:#0C447C;text-decoration:none;white-space:nowrap">
          Rapport →
        </a>
      </div>`;
  }).join('');
}

// ── Utilitaires ───────────────────────────────────────────────
function scoreClass(score) {
  if (score == null) return 'bgr';
  if (score >= 80)   return 'bg';
  if (score >= 60)   return 'ba';
  return 'br';
}

function formatDate(iso) {
  const d   = new Date(iso);
  const now = new Date();
  const isToday =
    d.getDate() === now.getDate() &&
    d.getMonth() === now.getMonth() &&
    d.getFullYear() === now.getFullYear();

  const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  return isToday ? `Auj. ${time}` : `${d.toLocaleDateString('fr-FR', { day:'2-digit', month:'2-digit' })} ${time}`;
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m${String(s).padStart(2, '0')}s`;
}

function fmt(n) {
  return n != null ? n.toLocaleString('fr-FR') : '—';
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;');
}
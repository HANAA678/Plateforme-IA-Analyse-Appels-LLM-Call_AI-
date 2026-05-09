/* ============================================================
   CallAI v2 — calls.js
   Gère : filtres, pagination, tableau des appels
   API  : GET /api/calls
   ============================================================ */

let currentPage   = 1;
let totalPages    = 1;
let debounceTimer = null;

document.addEventListener('DOMContentLoaded', loadCalls);

function debounceLoad() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => { currentPage = 1; loadCalls(); }, 400);
}

function changePage(delta) {
  const next = currentPage + delta;
  if (next < 1 || next > totalPages) return;
  currentPage = next;
  loadCalls();
}

async function loadCalls() {
  const params = buildParams();
  setLoading(true);
  try {
    const res  = await fetch(`/api/calls?${params}`);
    if (!res.ok) throw new Error('Erreur API calls');
    const data = await res.json();
    totalPages = data.total_pages || 1;
    renderTable(data.calls);
    renderPagination(data.total, data.page, data.total_pages);
    document.getElementById('totalBadge').textContent =
      data.total.toLocaleString('fr-FR') + ' appel(s)';
  } catch (e) {
    showError('Impossible de charger les appels.');
  } finally {
    setLoading(false);
  }
}

function buildParams() {
  const p = new URLSearchParams();
  const search   = document.getElementById('fSearch').value.trim();
  const period   = document.getElementById('fPeriod').value;
  const score    = document.getElementById('fScore').value;
  const type     = document.getElementById('fType').value;
  const priority = document.getElementById('fPriority').value;
  p.set('page', currentPage);
  if (period)   p.set('period',    period);
  if (score)    p.set('score',     score);
  if (type)     p.set('call_type', type);
  if (priority) p.set('priority',  priority);
  if (search)   p.set('search',    search);
  return p.toString();
}

// ── Constantes d'affichage ────────────────────────────────────
const TYPE_LABELS = {
  reclamation: 'Réclamation', information: 'Information',
  commercial:  'Commercial',  technique:   'Technique',
};
const TYPE_BADGE = {
  reclamation: 'br', commercial: 'bb', technique: 'bp', information: 'bgr',
};
const SENTIMENT_COLOR = { positif: '#27500A', neutre: '#633806', negatif: '#791F1F' };
const SENTIMENT_LABEL = { positif: 'Positif',  neutre: 'Neutre',  negatif: 'Négatif' };
const PRIORITY_BADGE  = { urgente: 'br', haute: 'ba', normale: 'bgr' };
const AVA_COLORS = [
  { bg: '#E6F1FB', color: '#0C447C' },
  { bg: '#FAEEDA', color: '#633806' },
  { bg: '#FCEBEB', color: '#791F1F' },
  { bg: '#E1F5EE', color: '#085041' },
  { bg: '#EEEDFE', color: '#3C3489' },
];

// ── Rendu tableau ─────────────────────────────────────────────
function renderTable(calls) {
  const tbody = document.getElementById('callsBody');
  if (!calls || calls.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9"
      style="text-align:center;padding:22px;color:#888;font-size:11px">
      Aucun appel trouvé pour ces filtres.</td></tr>`;
    return;
  }

  tbody.innerHTML = calls.map((c, i) => {
    const ava       = AVA_COLORS[i % AVA_COLORS.length];
    const scoreBdg  = scoreClass(c.score_total);
    const typeBdg   = TYPE_BADGE[c.call_type]    || 'bgr';
    const prioBdg   = PRIORITY_BADGE[c.priority] || 'bgr';
    const typeLabel = TYPE_LABELS[c.call_type]   || c.call_type || '—';
    const sentColor = SENTIMENT_COLOR[c.sentiment_client] || '#888';
    const sentLabel = SENTIMENT_LABEL[c.sentiment_client] || (c.sentiment_client || '—');
    const dateStr   = c.called_at        ? formatDate(c.called_at)            : '—';
    const dur       = c.duration_seconds ? formatDuration(c.duration_seconds) : '—';
    const score     = c.score_total ?? '—';
    const prio      = c.priority ? capitalize(c.priority) : '—';

    const avaHtml = `<span style="background:${ava.bg};color:${ava.color};
      border-radius:50%;width:20px;height:20px;display:inline-flex;
      align-items:center;justify-content:center;font-size:9px;
      font-weight:600;margin-right:4px">${escHtml(c.agent_initials || '??')}</span>`;

    return `
      <tr>
        <td>${avaHtml}${escHtml(shortName(c.agent_name))}</td>
        <td style="color:#888">${dateStr}</td>
        <td>${dur}</td>
        <td><span class="badge-c ${scoreBdg}">${score}</span></td>
        <td><span class="badge-c ${typeBdg}" style="font-size:10px">${typeLabel}</span></td>
        <td style="color:${sentColor}">${sentLabel}</td>
        <td><span class="badge-c ${prioBdg}" style="font-size:10px">${prio}</span></td>
        <td>
          <a href="/rapport?call_id=${c.call_id}"
             style="color:#0C447C;text-decoration:none;font-size:11px">Rapport</a>
          &nbsp;·&nbsp;
          <a href="/audio?call_id=${c.call_id}"
             style="color:#1D9E75;text-decoration:none;font-size:11px">Audio</a>
          &nbsp;·&nbsp;
          <a href="/coaching?agent_id=${c.agent_id || ''}"
             style="color:#7F77DD;text-decoration:none;font-size:11px">Coaching</a>
        </td>
      </tr>`;
  }).join('');
}

// ── Pagination ────────────────────────────────────────────────
function renderPagination(total, page, pages) {
  const info    = document.getElementById('pageInfo');
  const btnPrev = document.getElementById('btnPrev');
  const btnNext = document.getElementById('btnNext');
  const from = total === 0 ? 0 : (page - 1) * 25 + 1;
  const to   = Math.min(page * 25, total);
  info.textContent = total > 0
    ? `${from}–${to} sur ${total.toLocaleString('fr-FR')}`
    : 'Aucun résultat';
  btnPrev.disabled = page <= 1;
  btnNext.disabled = page >= pages;
}

// ── Helpers UI ────────────────────────────────────────────────
function setLoading(on) {
  const tbody = document.getElementById('callsBody');
  if (on && tbody.children.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9"
      style="text-align:center;padding:18px;color:#888;font-size:11px">
      <span class="spinner"></span></td></tr>`;
  }
}
function showError(msg) {
  document.getElementById('callsBody').innerHTML = `<tr><td colspan="9"
    style="text-align:center;padding:18px;color:#791F1F;font-size:11px">
    ${escHtml(msg)}</td></tr>`;
  showToast(msg, 'error');
}

// ── Utilitaires ───────────────────────────────────────────────
function scoreClass(s) {
  if (s == null) return 'bgr';
  if (s >= 80)   return 'bg';
  if (s >= 60)   return 'ba';
  return 'br';
}
function formatDate(iso) {
  const d = new Date(iso), now = new Date();
  const isToday = d.getDate()===now.getDate() && d.getMonth()===now.getMonth()
                  && d.getFullYear()===now.getFullYear();
  const time = d.toLocaleTimeString('fr-FR', { hour:'2-digit', minute:'2-digit' });
  return isToday ? `Auj. ${time}`
    : `${d.toLocaleDateString('fr-FR',{day:'2-digit',month:'2-digit'})} ${time}`;
}
function formatDuration(s) {
  const m = Math.floor(s/60), r = s%60;
  return `${m}m${String(r).padStart(2,'0')}s`;
}
function shortName(n) {
  if (!n) return '—';
  const p = n.trim().split(' ');
  return p.length === 1 ? p[0] : p[0]+' '+p[1][0]+'.';
}
function capitalize(s) { return s.charAt(0).toUpperCase()+s.slice(1); }
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
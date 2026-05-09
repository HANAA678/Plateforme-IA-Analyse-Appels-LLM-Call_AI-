/* ============================================================
   CallAI v2 — agents.js
   Gère : liste agents, filtre équipe, KPIs, modal ajout agent
   API  : GET /api/agents, GET /api/teams, POST /api/agents
   ============================================================ */

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadTeams();
  loadAgents();
});

// ── Charger les équipes (pour filtre + modal) ─────────────────
async function loadTeams() {
  try {
    const res  = await fetch('/api/teams');
    const data = await res.json();

    const fTeam  = document.getElementById('fTeam');
    const newTeam = document.getElementById('newTeam');

    data.forEach(t => {
      [fTeam, newTeam].forEach(sel => {
        const opt = document.createElement('option');
        opt.value       = t.id;
        opt.textContent = t.name;
        sel.appendChild(opt);
      });
    });
  } catch (_) {}
}

// ── Charger les agents ────────────────────────────────────────
async function loadAgents() {
  const teamId = document.getElementById('fTeam').value;
  const url    = teamId ? `/api/agents?team_id=${teamId}` : '/api/agents';

  try {
    const res  = await fetch(url);
    if (!res.ok) throw new Error('Erreur API agents');
    const data = await res.json();

    renderKPIs(data);
    renderAgents(data);
    document.getElementById('totalBadge').textContent =
      data.length + ' agent(s)';
  } catch (e) {
    document.getElementById('agentsList').innerHTML =
      '<div class="row-c" style="color:#791F1F;font-size:11px">Impossible de charger les agents.</div>';
    showToast('Erreur chargement agents', 'error');
  }
}

// ── KPIs ──────────────────────────────────────────────────────
function renderKPIs(agents) {
  document.getElementById('kpiTotal').textContent = agents.length;

  if (agents.length === 0) {
    document.getElementById('kpiBest').textContent  = '—';
    document.getElementById('kpiWorst').textContent = '—';
    return;
  }

  const withScore = agents.filter(a => a.avg_score != null);
  if (withScore.length === 0) return;

  const best  = withScore.reduce((m, a) => a.avg_score > m.avg_score ? a : m);
  const worst = withScore.reduce((m, a) => a.avg_score < m.avg_score ? a : m);

  document.getElementById('kpiBest').textContent  =
    `${shortName(best.full_name)} · ${best.avg_score.toFixed(0)}`;
  document.getElementById('kpiWorst').textContent =
    `${shortName(worst.full_name)} · ${worst.avg_score.toFixed(0)}`;
}

// ── Rendu liste agents ────────────────────────────────────────
const AVA_PALETTE = [
  { bg: '#E6F1FB', color: '#0C447C' },
  { bg: '#FAEEDA', color: '#633806' },
  { bg: '#FCEBEB', color: '#791F1F' },
  { bg: '#E1F5EE', color: '#085041' },
  { bg: '#EEEDFE', color: '#3C3489' },
];

function renderAgents(agents) {
  const el = document.getElementById('agentsList');

  if (agents.length === 0) {
    el.innerHTML = '<div class="row-c" style="color:#888;font-size:11px">Aucun agent trouvé.</div>';
    return;
  }

  el.innerHTML = agents.map((a, i) => {
    const ava       = AVA_PALETTE[i % AVA_PALETTE.length];
    const score     = a.avg_score != null ? a.avg_score.toFixed(0) : '—';
    const scorePct  = a.avg_score != null ? Math.min(a.avg_score, 100) : 0;
    const barColor  = barColorFromScore(a.avg_score);
    const scoreColor = a.avg_score == null ? '#888'
                     : a.avg_score >= 80 ? '#0F6E56'
                     : a.avg_score >= 60 ? '#633806'
                     : '#791F1F';
    const calls     = a.total_calls != null ? `${a.total_calls} appels` : '';
    const team      = a.team_name   ? `· ${escHtml(a.team_name)}` : '';
    const meta      = [calls, team].filter(Boolean).join(' ');

    return `
      <div class="row-c">
        <div class="ava" style="background:${ava.bg};color:${ava.color}">
          ${escHtml(a.initials || '??')}
        </div>
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:600">${escHtml(a.full_name)}</div>
          <div style="font-size:10px;color:#888">${meta}</div>
        </div>
        <div class="pbar" style="max-width:120px">
          <div class="pb" style="width:${scorePct}%;background:${barColor}"></div>
        </div>
        <span style="font-size:12px;font-weight:600;min-width:24px;
                     text-align:right;color:${scoreColor}">
          ${score}
        </span>
        <a href="/coaching?agent_id=${a.id}"
           class="btn-c btn-sm"
           style="margin-left:8px;background:#EEEDFE;border-color:#CECBF6;
                  color:#3C3489;text-decoration:none;white-space:nowrap">
          Coaching
        </a>
      </div>`;
  }).join('');
}

// ── Modal ajout agent ─────────────────────────────────────────
function openAddModal() {
  document.getElementById('newName').value  = '';
  document.getElementById('newEmail').value = '';
  document.getElementById('newTeam').value  = '';
  const modal = document.getElementById('addModal');
  modal.style.display = 'flex';

  // Fermer en cliquant en dehors
  modal.onclick = e => { if (e.target === modal) closeAddModal(); };
}

function closeAddModal() {
  document.getElementById('addModal').style.display = 'none';
}

async function submitAddAgent() {
  const fullName = document.getElementById('newName').value.trim();
  const email    = document.getElementById('newEmail').value.trim();
  const teamId   = document.getElementById('newTeam').value;

  if (!fullName) {
    showToast('Le nom complet est obligatoire.', 'error');
    return;
  }

  const btn = document.querySelector('#addModal .btn-primary');
  btn.disabled    = true;
  btn.textContent = 'Création…';

  try {
    const res = await fetch('/api/agents', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        full_name: fullName,
        email:     email || undefined,
        team_id:   teamId || undefined,
      }),
    });

    if (!res.ok) {
      const d = await res.json();
      throw new Error(d.detail || 'Erreur serveur');
    }

    showToast(`Agent "${fullName}" créé avec succès.`, 'success');
    closeAddModal();
    loadAgents();        // Rafraîchir la liste
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Créer →';
  }
}

// ── Utilitaires ───────────────────────────────────────────────
function barColorFromScore(score) {
  if (score == null) return '#e5e3dc';
  if (score >= 80)   return '#1D9E75';
  if (score >= 60)   return '#EF9F27';
  return '#E24B4A';
}

function shortName(fullName) {
  if (!fullName) return '—';
  const parts = fullName.trim().split(' ');
  if (parts.length === 1) return parts[0];
  return parts[0] + ' ' + parts[1][0] + '.';
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
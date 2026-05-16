/* ============================================================
   CallAI v2 — coaching.js
   Fiche coaching générée par appel spécifique.
   API : GET  /api/calls/{call_id}/coaching
         POST /api/calls/{call_id}/coaching/generate
         GET  /api/calls/{call_id}/report  (pour nom agent)
   ============================================================ */

let currentCallId = null;

document.addEventListener('DOMContentLoaded', init);

// ── Init ──────────────────────────────────────────────────────
async function init() {
  const params  = new URLSearchParams(window.location.search);
  const callId  = params.get('call_id');

  if (!callId) {
    showGlobalError('Aucun call_id fourni dans l\'URL.');
    return;
  }

  currentCallId = callId;

  // Lien rapport
  const linkRapport = document.getElementById('linkRapport');
  linkRapport.href         = `/rapport?call_id=${callId}`;
  linkRapport.style.display = '';

  // Charger infos agent depuis le rapport
  await loadAgentInfo(callId);

  // Charger la fiche coaching
  await loadCoaching(callId);
}

// ── Infos agent (nom, initiales, score) ───────────────────────
async function loadAgentInfo(callId) {
  try {
    const res  = await fetch(`/api/calls/${callId}/report`);
    if (!res.ok) return;
    const data = await res.json();

    // Nom agent dans le topbar
    if (data.agent?.full_name) {
      document.getElementById('coachName').textContent =
        data.agent.full_name;
    }

    // Avatar
    if (data.agent?.initials) {
      const ava = AVA_PALETTE[
        (data.agent.full_name || '').charCodeAt(0) % AVA_PALETTE.length
      ];
      const el = document.getElementById('coachAva');
      el.textContent      = data.agent.initials;
      el.style.background = ava.bg;
      el.style.color      = ava.color;
    }

    // Pré-remplir le score KPI depuis le rapport
    if (data.evaluation?.score_total != null) {
      document.getElementById('kpiScore').textContent =
        data.evaluation.score_total + '/100';
      document.getElementById('kpiScore').style.color =
        scoreColor(data.evaluation.score_total);
    }

  } catch (_) {}
}

// ── Charger fiche coaching ────────────────────────────────────
async function loadCoaching(callId) {
  showBlock('loadingBlock');
  hideBlocks(['coachingContent','emptyBlock','generatingBlock','kpiBlock']);

  try {
    const res = await fetch(`/api/calls/${callId}/coaching`);

    if (res.status === 404) {
      hideBlock('loadingBlock');
      showBlock('emptyBlock');
      return;
    }
    if (!res.ok) throw new Error('Erreur API coaching');

    const data = await res.json();
    renderCoaching(data);

    hideBlock('loadingBlock');
    showBlock('kpiBlock');
    showBlock('coachingContent');
    document.getElementById('btnRegenerate').style.display = '';

  } catch (e) {
    hideBlock('loadingBlock');
    showToast('Erreur chargement coaching.', 'error');
    showBlock('emptyBlock');
  }
}

// ── Rendu fiche ───────────────────────────────────────────────
function renderCoaching(data) {
  // KPIs
  const score = data.avg_score_at_generation;
  document.getElementById('kpiScore').textContent =
    score != null ? score.toFixed(0) + '/100' : '—';
  document.getElementById('kpiScore').style.color = scoreColor(score);
  document.getElementById('kpiCalls').textContent =
    data.calls_analyzed != null ? data.calls_analyzed : '1';
  document.getElementById('kpiDate').textContent =
    data.generated_at ? formatDate(data.generated_at) : '—';

  // Contenu
  setText('weakPointsText',
    data.weak_points || 'Aucun point faible détecté.');
  setText('vocalIssuesText',
    data.vocal_issues || 'Données vocales non disponibles.');
  setText('trainingText',
    data.recommended_training || 'Aucune formation recommandée.');
  setText('performanceSummary',
    data.performance_summary || '—');

  // Lien appel source
  const exEl = document.getElementById('exampleCallText');
  if (data.call_id) {
    exEl.innerHTML = `
      <a href="/rapport?call_id=${data.call_id}"
         style="color:#0C447C;text-decoration:none">
        Voir le rapport de cet appel →
      </a>`;
  } else {
    exEl.textContent = '—';
  }
}

// ── Générer / Regénérer ───────────────────────────────────────
async function generateCoaching() {
  if (!currentCallId) return;

  // Masquer empty + boutons, afficher spinner
  hideBlocks(['emptyBlock','coachingContent','kpiBlock']);
  showBlock('generatingBlock');
  document.getElementById('btnRegenerate').disabled = true;

  try {
    const res = await fetch(
      `/api/calls/${currentCallId}/coaching/generate`,
      { method: 'POST' }
    );

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Erreur génération');
    }

    const data = await res.json();
    showToast('Fiche coaching générée avec succès !', 'success');

    hideBlock('generatingBlock');
    renderCoaching(data);
    showBlock('kpiBlock');
    showBlock('coachingContent');
    document.getElementById('btnRegenerate').style.display = '';

  } catch (e) {
    hideBlock('generatingBlock');
    showBlock('emptyBlock');
    showToast(e.message, 'error');
  } finally {
    document.getElementById('btnRegenerate').disabled = false;
  }
}

// ── Utilitaires ───────────────────────────────────────────────
const AVA_PALETTE = [
  { bg: '#E6F1FB', color: '#0C447C' },
  { bg: '#FAEEDA', color: '#633806' },
  { bg: '#FCEBEB', color: '#791F1F' },
  { bg: '#E1F5EE', color: '#085041' },
  { bg: '#EEEDFE', color: '#3C3489' },
];

function scoreColor(score) {
  if (score == null) return '#888';
  if (score >= 80)   return '#0F6E56';
  if (score >= 60)   return '#633806';
  return '#791F1F';
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function showBlock(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = '';
}

function hideBlock(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

function hideBlocks(ids) {
  ids.forEach(hideBlock);
}

function showGlobalError(msg) {
  hideBlock('loadingBlock');
  document.getElementById('coachName').textContent = 'Erreur';
  showToast(msg, 'error');
  const empty = document.getElementById('emptyBlock');
  empty.style.display = '';
  empty.querySelector('div[style]').innerHTML = `
    <div style="font-size:22px;margin-bottom:8px">⚠️</div>
    <div style="font-weight:600;font-size:13px;color:#791F1F">${msg}</div>
    <div style="margin-top:10px">
      <a href="/calls" class="btn-c btn-sm" style="text-decoration:none">
        ← Retour aux appels
      </a>
    </div>`;
}
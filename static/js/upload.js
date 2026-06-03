/* ============================================================
   CallAI v2 — upload.js
   Gère : drag & drop, chargement agents/critères, soumission,
           polling statut pipeline, affichage succès,
           toggle transcription alignée
   ============================================================ */

// ── État global ───────────────────────────────────────────────
let selectedFile    = null;
let pollingTimer    = null;
let alignedTextData = "";   // ← stocke la transcription reçue de l'API

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setDefaultDate();
  loadAgents();
  loadCriteria();
  initDropZone();
});

// ── Date/heure par défaut = maintenant ───────────────────────
function setDefaultDate() {
  const now = new Date();
  const iso = now.toISOString().slice(0, 16);
  document.getElementById('calledAt').value = iso;
}

// ── Charger la liste des agents ───────────────────────────────
async function loadAgents() {
  const sel = document.getElementById('agentSelect');
  try {
    const res  = await fetch('/api/agents');
    const data = await res.json();
    sel.innerHTML = '<option value="">— Sélectionner un agent —</option>';
    data.forEach(a => {
      const opt       = document.createElement('option');
      opt.value       = a.id;
      opt.textContent = a.full_name + (a.team_name ? ` (${a.team_name})` : '');
      sel.appendChild(opt);
    });
  } catch (e) {
    sel.innerHTML = '<option value="">Erreur de chargement</option>';
    showToast('Impossible de charger les agents', 'error');
  }
}

// ── Charger et afficher les critères ─────────────────────────
async function loadCriteria() {
  try {
    const res  = await fetch('/api/criteria');
    const data = await res.json();

    document.getElementById('criteriaLoading').style.display = 'none';

    const grid   = document.getElementById('criteriaGrid');
    const total  = document.getElementById('criteriaTotal');
    const col1   = document.createElement('div');
    const col2   = document.createElement('div');
    const active = data.filter(c => c.is_active);

    active.forEach((c, i) => {
      const card = document.createElement('div');
      card.className = 'criteria-card';
      card.innerHTML = `
        <span class="crit-pts">${c.max_pts} pts</span>
        <div class="crit-name">${escHtml(c.label)}</div>
        <div class="crit-desc">${escHtml(c.description || '')}</div>
      `;
      (i % 2 === 0 ? col1 : col2).appendChild(card);
    });

    const totalPts = active.reduce((s, c) => s + c.max_pts, 0);
    grid.appendChild(col1);
    grid.appendChild(col2);
    grid.style.display = '';

    total.innerHTML = `
      <strong>Total : ${totalPts} pts</strong><br>
      Score ≥ 80 → Conforme &nbsp;·&nbsp; 60–79 → Partiel &nbsp;·&nbsp; &lt; 60 → Non-conforme
    `;
    total.style.display = '';
  } catch (e) {
    document.getElementById('criteriaLoading').innerHTML =
      '<div style="font-size:11px;color:#888;padding:8px">Impossible de charger les critères.</div>';
  }
}

// ── Drag & Drop ───────────────────────────────────────────────
function initDropZone() {
  const zone  = document.getElementById('dropZone');
  const input = document.getElementById('fileInput');

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => { if (input.files[0]) handleFile(input.files[0]); });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
}

function handleFile(file) {
  const byExt = /\.(wav|mp3|m4a)$/i.test(file.name);
  if (!byExt) { showToast('Format non supporté. Utilisez WAV, MP3 ou M4A.', 'error'); return; }
  if (file.size > 100 * 1024 * 1024) { showToast('Fichier trop lourd (max 100 MB).', 'error'); return; }

  selectedFile = file;
  const title = document.getElementById('dropTitle');
  title.textContent = `✓ ${file.name} (${formatSize(file.size)})`;
  title.style.color = '#1D9E75';
}

// ── Soumission ────────────────────────────────────────────────
async function submitUpload() {
  if (!selectedFile) { showToast('Veuillez sélectionner un fichier audio.', 'error'); return; }
  const agentId = document.getElementById('agentSelect').value;
  if (!agentId) { showToast('Veuillez sélectionner un agent.', 'error'); return; }
  const calledAt = document.getElementById('calledAt').value;
  if (!calledAt) { showToast("Veuillez renseigner la date et l'heure.", 'error'); return; }

  const btn = document.getElementById('btnAnalyse');
  btn.disabled    = true;
  btn.textContent = 'Envoi en cours…';

  showProgress('Envoi du fichier…', 10);

  // Réinitialiser la transcription précédente
  alignedTextData = "";
  document.getElementById('transcriptionContent').textContent = "";
  document.getElementById('transcriptionBlock').style.display = 'none';
  const chk = document.getElementById('toggleTranscription');
  chk.checked = false;
  updateToggleStyle(false);

  const fd = new FormData();
  fd.append('file',             selectedFile);
  fd.append('agent_id',         agentId);
  fd.append('called_at',        calledAt + ':00');
  fd.append('call_type',        document.getElementById('callType').value);
  fd.append('priority',         document.getElementById('priority').value);
  fd.append('supervisor_notes', document.getElementById('supervisorNotes').value);
  fd.append('focus_points',     document.getElementById('focusPoints').value);

  try {
    const res  = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Erreur serveur');

    // ← Stocker la transcription alignée retournée par l'API
    if (data.aligned_text) {
      alignedTextData = data.aligned_text;
    }

    showProgress('Transcription en cours (Whisper)…', 25);
    startPolling(data.call_id);

  } catch (e) {
    resetBtn();
    hideProgress();
    showToast(e.message, 'error');
  }
}

// ── Polling statut ────────────────────────────────────────────
const STEPS = {
  pending:     { label: 'En attente de traitement…',              pct: 15  },
  transcribed: { label: 'Transcription terminée — Analyse LLM…', pct: 60  },
  evaluated:   { label: 'Évaluation terminée !',                  pct: 100 },
  failed:      { label: 'Erreur lors du traitement.',             pct: 100 },
};

function startPolling(callId) {
  let attempts = 0;
  const MAX    = 120;

  pollingTimer = setInterval(async () => {
    attempts++;
    if (attempts > MAX) {
      clearInterval(pollingTimer);
      showToast('Timeout — le traitement prend trop de temps.', 'error');
      resetBtn();
      return;
    }

    try {
      const res  = await fetch(`/api/calls/${callId}/status`);
      const data = await res.json();
      const step = STEPS[data.status] || STEPS.pending;

      showProgress(step.label, step.pct);

      // Si la transcription n'est pas encore reçue, la récupérer via le statut
      if (data.transcription_text && !alignedTextData) {
        alignedTextData = data.transcription_text;
      }

      if (data.status === 'evaluated') {
        clearInterval(pollingTimer);
        onSuccess(callId);
      } else if (data.status === 'failed') {
        clearInterval(pollingTimer);
        hideProgress();
        resetBtn();
        showToast('Le pipeline a échoué. Vérifiez les logs.', 'error');
      }
    } catch (e) {
      // réseau temporairement down, on réessaie
    }
  }, 3000);
}

// ── Succès ────────────────────────────────────────────────────
function onSuccess(callId) {
  hideProgress();

  const block = document.getElementById('successBlock');
  block.style.display = '';
  document.getElementById('linkRapport').href = `/rapport?call_id=${callId}`;

  // Pré-remplir le contenu de la transcription
  if (alignedTextData) {
    document.getElementById('transcriptionContent').textContent = alignedTextData;
  } else {
    document.getElementById('transcriptionContent').textContent =
      "Transcription non disponible.";
  }

  showToast('Analyse terminée avec succès !', 'success');
  resetBtn();
}

// ── Toggle transcription ──────────────────────────────────────
function toggleTranscriptionBlock() {
  const chk   = document.getElementById('toggleTranscription');
  const block = document.getElementById('transcriptionBlock');
  block.style.display = chk.checked ? '' : 'none';
  updateToggleStyle(chk.checked);
}

function updateToggleStyle(checked) {
  const track = document.getElementById('toggleTrack');
  const thumb = document.getElementById('toggleThumb');
  track.style.background = checked ? '#1D9E75' : '#ccc';
  thumb.style.left        = checked ? '21px'    : '3px';
}

// ── Helpers UI ────────────────────────────────────────────────
function showProgress(label, pct) {
  document.getElementById('progressBlock').style.display = '';
  document.getElementById('progressLabel').textContent   = label;
  document.getElementById('progressPct').textContent     = pct + '%';
  document.getElementById('progressFill').style.width    = pct + '%';
  const fill = document.getElementById('progressFill');
  fill.style.background = (pct === 100 && label.includes('Erreur')) ? '#E24B4A' : '#1D9E75';
}

function hideProgress() {
  document.getElementById('progressBlock').style.display = 'none';
}

function resetBtn() {
  const btn       = document.getElementById('btnAnalyse');
  btn.disabled    = false;
  btn.textContent = 'Lancer l\'analyse →';
}

function formatSize(bytes) {
  if (bytes < 1024)        return bytes + ' o';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' Ko';
  return (bytes / (1024 * 1024)).toFixed(1) + ' Mo';
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
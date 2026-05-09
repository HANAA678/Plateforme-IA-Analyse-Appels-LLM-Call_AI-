/* ============================================================
   CallAI v2 — audio.js
   - Si call_id présent dans l'URL → charge cet appel
   - Sinon → charge le dernier appel évalué automatiquement
   API : GET /api/calls/{id}/audio  +  GET /api/calls/{id}/report
   ============================================================ */

document.addEventListener('DOMContentLoaded', init);

async function init() {
  const params = new URLSearchParams(window.location.search);
  let callId   = params.get('call_id');

  if (!callId) {
    // Aucun call_id → on prend le dernier appel évalué
    callId = await fetchLatestCallId();
    if (!callId) {
      showGlobalError('Aucun appel analysé trouvé. Uploadez d\'abord un appel.');
      return;
    }
    // Mettre à jour l'URL sans recharger la page
    history.replaceState(null, '', `/audio?call_id=${callId}`);
  }

  loadAudio(callId);
}

// ── Récupère l'id du dernier appel évalué ────────────────────
async function fetchLatestCallId() {
  try {
    const res  = await fetch('/api/calls?period=month&page=1');
    if (!res.ok) return null;
    const data = await res.json();
    if (data.calls && data.calls.length > 0) return data.calls[0].call_id;
    // Essai sur la semaine si rien ce mois
    const res2  = await fetch('/api/calls?period=week&page=1');
    const data2 = await res2.json();
    return data2.calls?.[0]?.call_id || null;
  } catch (_) { return null; }
}

// ── Chargement principal ──────────────────────────────────────
async function loadAudio(callId) {
  try {
    // Les deux requêtes en parallèle
    const [audioRes, reportRes] = await Promise.all([
      fetch(`/api/calls/${callId}/audio`),
      fetch(`/api/calls/${callId}/report`),
    ]);

    if (audioRes.status === 404) throw new Error('Métriques audio introuvables pour cet appel.');
    if (!audioRes.ok)            throw new Error('Erreur lors du chargement des métriques audio.');

    const audio  = await audioRes.json();
    const report = reportRes.ok ? await reportRes.json() : null;

    // Titre & meta depuis le rapport
    if (report?.agent?.full_name) {
      document.getElementById('audioTitle').textContent =
        `Analyse audio — ${report.agent.full_name}`;
    }
    if (report?.call?.duration_seconds) {
      const dur = formatDuration(report.call.duration_seconds);
      document.getElementById('audioMeta').innerHTML =
        `WAV · Signal pur · ${dur} · <code>audio_metrics</code>`;
      updateDiarTimes(report.call.duration_seconds);
    }

    renderDiarisation(audio);
    renderEmotions('emotionsAgent',  audio, 'agent');
    renderEmotions('emotionsClient', audio, 'client');
    renderSilences(audio);
    renderRhythm(audio);

  } catch (e) {
    showGlobalError(e.message);
  }
}

// ── Diarisation ───────────────────────────────────────────────
function renderDiarisation(data) {
  const seg = document.getElementById('diarSeg');
  seg.innerHTML = '';

  let segments = Array.isArray(data.diarization) ? data.diarization : [];

  // Fallback : segments synthétiques depuis les pourcentages
  if (segments.length === 0) {
    const a = data.agent_talk_pct  || 0;
    const c = data.client_talk_pct || 0;
    const s = data.silence_pct     || 0;
    segments = buildFallbackSegments(a, c, s);
  }

  const total = segments.reduce((sum, s) => sum + (s.duration ?? s.weight ?? 1), 0) || 1;

  segments.forEach(s => {
    const d   = document.createElement('div');
    d.className = 'seg';
    const w   = ((s.duration ?? s.weight ?? 1) / total * 100).toFixed(2);
    d.style.cssText = `flex:${w};background:${speakerColor(s.speaker)};opacity:.75`;
    seg.appendChild(d);
  });

  // Légende
  const a = data.agent_talk_pct  ?? '—';
  const c = data.client_talk_pct ?? '—';
  const s = data.silence_pct     ?? '—';
  document.getElementById('diarLegend').innerHTML = `
    <span style="color:#0C447C">■ Agent <code>agent_talk_pct</code> ${a}%</span>
    <span style="color:#1D9E75">■ Client <code>client_talk_pct</code> ${c}%</span>
    <span style="color:#E24B4A">■ Silence <code>silence_pct</code> ${s}%</span>`;
}

function buildFallbackSegments(a, c, s) {
  // Génère des blocs alternés proportionnels aux %
  const pattern = [
    { speaker:'agent',   w: a * 0.4 },
    { speaker:'client',  w: c * 0.5 },
    { speaker:'silence', w: s       },
    { speaker:'agent',   w: a * 0.3 },
    { speaker:'client',  w: c * 0.3 },
    { speaker:'agent',   w: a * 0.3 },
    { speaker:'client',  w: c * 0.2 },
  ];
  return pattern.filter(p => p.w > 0).map(p => ({ speaker: p.speaker, duration: p.w }));
}

function updateDiarTimes(totalSec) {
  const mid = Math.floor(totalSec / 2);
  document.getElementById('diarTimes').innerHTML =
    `<span>0:00</span><span>${fmtSec(mid)}</span><span>${fmtSec(totalSec)}</span>`;
}

function speakerColor(speaker) {
  const s = (speaker || '').toLowerCase();
  if (s === 'agent')   return '#378ADD';
  if (s === 'client')  return '#1D9E75';
  if (s === 'silence') return '#E24B4A';
  return '#888';
}

// ── Émotions ──────────────────────────────────────────────────
const EMOTION_CFG = {
  agent: {
    professional:  { label:'Professionnel', color:'#1D9E75' },
    professionnel: { label:'Professionnel', color:'#1D9E75' },
    empathique:    { label:'Empathique',    color:'#378ADD' },
    empathetic:    { label:'Empathique',    color:'#378ADD' },
    stressed:      { label:'Stress',        color:'#E24B4A' },
    stress:        { label:'Stress',        color:'#E24B4A' },
    monotone:      { label:'Monotone',      color:'#888'    },
  },
  client: {
    frustrated:    { label:'Frustration',  color:'#D85A30' },
    frustration:   { label:'Frustration',  color:'#D85A30' },
    satisfied:     { label:'Satisfaction', color:'#1D9E75' },
    satisfaction:  { label:'Satisfaction', color:'#1D9E75' },
    angry:         { label:'Colère',       color:'#E24B4A' },
    colere:        { label:'Colère',       color:'#E24B4A' },
    neutral:       { label:'Neutre',       color:'#888'    },
    neutre:        { label:'Neutre',       color:'#888'    },
  },
};

function renderEmotions(elId, data, who) {
  const el  = document.getElementById(elId);
  const key = who === 'agent' ? 'emotions_agent' : 'emotions_client';

  // Chercher dans data directement
  let emotions = data[key] || null;

  // Fallback : chercher dans le premier segment de diarisation
  if (!emotions && Array.isArray(data.diarization) && data.diarization.length > 0) {
    emotions = data.diarization[0][key] || null;
  }

  if (!emotions || typeof emotions !== 'object' || Object.keys(emotions).length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:#888">Données non disponibles.</div>';
    return;
  }

  const cfg    = EMOTION_CFG[who] || {};
  const sorted = Object.entries(emotions).sort((a, b) => b[1] - a[1]);

  el.innerHTML = sorted.map(([key, val]) => {
    const k     = key.toLowerCase();
    const info  = cfg[k] || { label: capitalize(key), color: '#888' };
    // val peut être 0–1 ou 0–100
    const pct   = val > 1 ? val.toFixed(0) : (val * 100).toFixed(0);
    return `
      <div class="ebar">
        <span style="min-width:95px;font-size:11px">${info.label}</span>
        <div class="ebr">
          <div class="ebf" style="width:${pct}%;background:${info.color}"></div>
        </div>
        <span style="font-size:10px;min-width:32px;text-align:right">${pct}%</span>
      </div>`;
  }).join('');
}

// ── Silences ──────────────────────────────────────────────────
const NOISE_BADGE = {
  low:    { cls: 'bg',  label: 'Faible' },
  medium: { cls: 'ba',  label: 'Moyen'  },
  high:   { cls: 'br',  label: 'Élevé'  },
};

function renderSilences(data) {
  const el       = document.getElementById('silenceRows');
  const silences = Array.isArray(data.silences) ? data.silences : [];
  const maxSec   = data.silence_max_sec ?? null;
  const noise    = data.noise_level ? (NOISE_BADGE[data.noise_level] || { cls:'bgr', label: data.noise_level }) : null;

  // Position du silence le plus long
  const longest  = silences.reduce((m, s) => (s.duration ?? 0) > (m.duration ?? 0) ? s : m, {});
  const maxLabel = maxSec != null
    ? `${maxSec}s${longest.start != null ? ' à ' + fmtSec(longest.start) : ''}`
    : '—';

  el.innerHTML = `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Silences détectés</span>
      <span style="font-weight:600">${silences.length > 0 ? silences.length : (maxSec != null ? '≥1' : '—')}</span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Plus long <code>silence_max_sec</code></span>
      <span style="font-weight:600;color:#791F1F">${maxLabel}</span>
    </div>
    ${noise ? `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Bruit de fond <code>noise_level</code></span>
      <span class="badge-c ${noise.cls}">${noise.label}</span>
    </div>` : ''}`;

  // Liste détaillée des silences (max 5)
  if (silences.length > 0) {
    el.innerHTML += silences.slice(0, 5).map(s => {
      const dur = s.duration != null ? `${s.duration}s` : '—';
      const pos = s.start    != null ? `à ${fmtSec(s.start)}` : '';
      const cls = (s.duration ?? 0) >= 10 ? 'br' : (s.duration ?? 0) >= 5 ? 'ba' : 'bgr';
      return `
        <div class="row-c" style="padding:4px 0">
          <span style="font-size:10px;color:#888;flex:1">${pos}</span>
          <span class="badge-c ${cls}" style="font-size:10px">${dur}</span>
        </div>`;
    }).join('');
    if (silences.length > 5) {
      el.innerHTML += `<div style="font-size:10px;color:#888;padding:4px 0">+ ${silences.length - 5} autre(s)…</div>`;
    }
  }
}

// ── Rythme & interruptions ────────────────────────────────────
function renderRhythm(data) {
  const el     = document.getElementById('rhythmRows');
  const aWpm   = data.agent_wpm          ?? null;
  const cWpm   = data.client_wpm         ?? null;
  const inter  = data.interruptions_count ?? null;

  el.innerHTML = `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Débit agent <code>agent_wpm</code></span>
      <span style="font-weight:600;color:${wpmColor(aWpm)}">
        ${aWpm != null ? aWpm + ' mots/min' : '—'}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Débit client <code>client_wpm</code></span>
      <span style="font-weight:600;color:${wpmColor(cWpm)}">
        ${cWpm != null ? cWpm + ' mots/min' : '—'}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Interruptions <code>interruptions_count</code></span>
      <span style="font-weight:600;color:${(inter ?? 0) > 3 ? '#791F1F' : '#633806'}">
        ${inter != null ? inter + ' fois' : '—'}
      </span>
    </div>`;
}

// ── Utilitaires ───────────────────────────────────────────────
function wpmColor(wpm) {
  if (wpm == null) return '#1a1a18';
  if (wpm <= 160)  return '#1D9E75';
  if (wpm <= 200)  return '#EF9F27';
  return '#E24B4A';
}
function fmtSec(s) {
  const m = Math.floor(s / 60), r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}
function formatDuration(s) {
  const m = Math.floor(s / 60), r = s % 60;
  return `${m}m${String(r).padStart(2, '0')}s`;
}
function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function showGlobalError(msg) {
  document.getElementById('audioTitle').textContent = 'Analyse audio';
  document.getElementById('diarSeg').innerHTML =
    `<span style="font-size:11px;color:#791F1F;padding:4px">${escHtml(msg)}</span>`;
  ['emotionsAgent','emotionsClient','silenceRows','rhythmRows'].forEach(id => {
    document.getElementById(id).innerHTML =
      `<div style="font-size:11px;color:#888">—</div>`;
  });
  showToast(msg, 'error');
}
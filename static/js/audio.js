/* ============================================================
   CallAI v2 — audio.js
   Affiche uniquement les données disponibles en BDD.
   Gère gracieusement les champs NULL (emotions, wpm).
   ============================================================ */

document.addEventListener('DOMContentLoaded', init);

async function init() {
  const params = new URLSearchParams(window.location.search);
  let callId   = params.get('call_id');

  if (!callId) {
    callId = await fetchLatestCallId();
    if (!callId) {
      showGlobalError('Aucun appel analysé trouvé. Uploadez d\'abord un appel.');
      return;
    }
    history.replaceState(null, '', `/audio?call_id=${callId}`);
  }
  loadAudio(callId);
}

// ── Dernier appel si pas de call_id dans l'URL ────────────────
async function fetchLatestCallId() {
  try {
    const res  = await fetch('/api/calls?period=month&page=1');
    const data = await res.json();
    if (data.calls?.length > 0) return data.calls[0].call_id;
    const res2  = await fetch('/api/calls?period=week&page=1');
    const data2 = await res2.json();
    return data2.calls?.[0]?.call_id || null;
  } catch (_) { return null; }
}

// ── Chargement principal ──────────────────────────────────────
async function loadAudio(callId) {
  try {
    const [audioRes, reportRes] = await Promise.all([
      fetch(`/api/calls/${callId}/audio`),
      fetch(`/api/calls/${callId}/report`),
    ]);

    if (!audioRes.ok) throw new Error('Métriques audio introuvables.');
    const audio  = await audioRes.json();
    const report = reportRes.ok ? await reportRes.json() : null;

    // ── Debug console ────────────────────────────────────────
    console.group('📊 audio_metrics');
    console.table({
      agent_talk_pct:      audio.agent_talk_pct,
      client_talk_pct:     audio.client_talk_pct,
      silence_pct:         audio.silence_pct,
      silence_max_sec:     audio.silence_max_sec,
      interruptions_count: audio.interruptions_count,
      agent_wpm:           audio.agent_wpm,
      client_wpm:          audio.client_wpm,
      noise_level:         audio.noise_level,
    });
    console.log('diarization     :', audio.diarization);
    console.log('emotions_agent  :', audio.emotions_agent);
    console.log('emotions_client :', audio.emotions_client);
    console.groupEnd();

    // ── Titre & meta ─────────────────────────────────────────
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
    renderEmotions('emotionsAgent',  audio.emotions_agent,  'agent');
    renderEmotions('emotionsClient', audio.emotions_client, 'client');
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

  const agentPct   = data.agent_talk_pct  || 0;
  const clientPct  = data.client_talk_pct || 0;
  const silencePct = data.silence_pct     || 0;

  // Utiliser diarization si elle contient des segments valides
  let segments = Array.isArray(data.diarization)
    ? data.diarization.filter(s => s && (s.duration ?? s.end_sec ?? s.pct_width) != null)
    : [];

  if (segments.length > 0) {
    // Format pyannote : {speaker, start_sec, end_sec}
    // Format custom   : {speaker, duration} ou {speaker, pct_width}
    const total = segments.reduce((sum, s) => {
      const w = s.duration ?? (s.end_sec - (s.start_sec || 0)) ?? s.pct_width ?? 1;
      return sum + w;
    }, 0) || 1;

    segments.forEach(s => {
      const w = s.duration ?? (s.end_sec - (s.start_sec || 0)) ?? s.pct_width ?? 1;
      const d = document.createElement('div');
      d.className = 'seg';
      d.style.cssText = `flex:${(w/total*100).toFixed(2)};background:${speakerColor(s.speaker)};opacity:.8`;
      seg.appendChild(d);
    });
  } else {
    // Fallback : construire visuellement depuis les % disponibles
    renderDiarFallback(seg, agentPct, clientPct, silencePct);
  }

  // Légende
  document.getElementById('diarLegend').innerHTML = `
    <span style="color:#0C447C">■ Agent <code>agent_talk_pct</code> ${fmt(agentPct)}%</span>
    <span style="color:#1D9E75">■ Client <code>client_talk_pct</code> ${fmt(clientPct)}%</span>
    <span style="color:#E24B4A">■ Silence <code>silence_pct</code> ${fmt(silencePct)}%</span>`;
}

function renderDiarFallback(container, a, c, s) {
  // Construit une barre approximative depuis les 3 pourcentages
  // Alterne agent/client avec silences intercalés
  const total = a + c + s || 100;
  const blocks = [
    { speaker: 'agent',   w: a * 0.45 },
    { speaker: 'silence', w: s * 0.4  },
    { speaker: 'client',  w: c * 0.5  },
    { speaker: 'agent',   w: a * 0.35 },
    { speaker: 'client',  w: c * 0.3  },
    { speaker: 'silence', w: s * 0.3  },
    { speaker: 'agent',   w: a * 0.2  },
    { speaker: 'client',  w: c * 0.2  },
  ].filter(b => b.w > 0.5);

  const blockTotal = blocks.reduce((s, b) => s + b.w, 0) || 1;
  blocks.forEach(b => {
    const d = document.createElement('div');
    d.className = 'seg';
    d.style.cssText =
      `flex:${(b.w / blockTotal * 100).toFixed(2)};` +
      `background:${speakerColor(b.speaker)};opacity:.75`;
    container.appendChild(d);
  });
}

function updateDiarTimes(totalSec) {
  const mid = Math.floor(totalSec / 2);
  document.getElementById('diarTimes').innerHTML =
    `<span>0:00</span><span>${fmtSec(mid)}</span><span>${fmtSec(totalSec)}</span>`;
}

function speakerColor(speaker) {
  const s = (speaker || '').toLowerCase();
  if (['agent',  'speaker_0', 'speaker_00', 'spk_0'].includes(s)) return '#378ADD';
  if (['client', 'speaker_1', 'speaker_01', 'spk_1'].includes(s)) return '#1D9E75';
  if (['silence','no_speech', 'sil', 'nonspeech'].includes(s))     return '#E24B4A';
  // SPEAKER_N générique : pair=agent, impair=client
  const num = parseInt((s.match(/\d+$/) || [])[0], 10);
  if (!isNaN(num)) return num % 2 === 0 ? '#378ADD' : '#1D9E75';
  return '#888';
}

// ── Émotions ──────────────────────────────────────────────────
const EMOTION_CFG = {
  // Agent
  professional:  { label: 'Professionnel', color: '#1D9E75' },
  professionnel: { label: 'Professionnel', color: '#1D9E75' },
  empathetic:    { label: 'Empathique',    color: '#378ADD' },
  empathique:    { label: 'Empathique',    color: '#378ADD' },
  stressed:      { label: 'Stress',        color: '#E24B4A' },
  stress:        { label: 'Stress',        color: '#E24B4A' },
  monotone:      { label: 'Monotone',      color: '#888'    },
  // Client
  frustrated:    { label: 'Frustration',  color: '#D85A30' },
  frustration:   { label: 'Frustration',  color: '#D85A30' },
  satisfied:     { label: 'Satisfaction', color: '#1D9E75' },
  satisfaction:  { label: 'Satisfaction', color: '#1D9E75' },
  angry:         { label: 'Colère',       color: '#E24B4A' },
  colere:        { label: 'Colère',       color: '#E24B4A' },
  neutral:       { label: 'Neutre',       color: '#888'    },
  neutre:        { label: 'Neutre',       color: '#888'    },
};

function renderEmotions(elId, emotions, who) {
  const el = document.getElementById(elId);

  // Vérification stricte : doit être un objet non vide avec des nombres
  const isValid = emotions &&
    typeof emotions === 'object' &&
    !Array.isArray(emotions) &&
    Object.keys(emotions).length > 0 &&
    Object.values(emotions).some(v => typeof v === 'number');

  if (!isValid) {
    el.innerHTML = `
      <div style="font-size:11px;color:#888;padding:4px 0">
        Non calculé —
        <code>pipeline/emotions.py</code> requis
      </div>`;
    return;
  }

  const sorted = Object.entries(emotions).sort((a, b) => b[1] - a[1]);
  el.innerHTML = sorted.map(([key, val]) => {
    const k    = key.toLowerCase();
    const info = EMOTION_CFG[k] || { label: capitalize(key), color: '#888' };
    // val peut être 0–1 ou 0–100
    const pct  = val > 1 ? Math.round(val) : Math.round(val * 100);
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
  const maxSec   = data.silence_max_sec;
  const noise    = data.noise_level
    ? (NOISE_BADGE[data.noise_level] || { cls: 'bgr', label: data.noise_level })
    : null;

  // Chercher la position du silence le plus long dans le tableau silences[]
  const longest  = silences.reduce(
    (m, s) => ((s.duration_sec ?? s.duration ?? 0) > (m.duration_sec ?? m.duration ?? 0) ? s : m),
    {}
  );
  const pos      = longest.start_sec ?? longest.start ?? null;
  const maxLabel = maxSec != null && maxSec > 0
    ? `${maxSec}s${pos != null ? ' à ' + fmtSec(pos) : ''}`
    : maxSec === 0 ? 'Aucun silence long détecté' : '—';

  const countLabel = silences.length > 0
    ? silences.length
    : (maxSec != null && maxSec > 0 ? '≥ 1' : '0');

  el.innerHTML = `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Silences détectés</span>
      <span style="font-weight:600">${countLabel}</span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Plus long <code>silence_max_sec</code></span>
      <span style="font-weight:600;color:${maxSec > 5 ? '#791F1F' : '#1a1a18'}">${maxLabel}</span>
    </div>
    ${noise ? `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Bruit de fond <code>noise_level</code></span>
      <span class="badge-c ${noise.cls}">${noise.label}</span>
    </div>` : ''}`;

  // Liste détaillée si disponible
  if (silences.length > 0) {
    el.innerHTML += silences.slice(0, 5).map(s => {
      const dur = s.duration_sec ?? s.duration ?? null;
      const st  = s.start_sec   ?? s.start    ?? null;
      const cls = (dur ?? 0) >= 10 ? 'br' : (dur ?? 0) >= 5 ? 'ba' : 'bgr';
      return `
        <div class="row-c" style="padding:3px 0">
          <span style="font-size:10px;color:#888;flex:1">
            ${st != null ? 'à ' + fmtSec(st) : ''}
          </span>
          <span class="badge-c ${cls}" style="font-size:10px">
            ${dur != null ? dur + 's' : '—'}
          </span>
        </div>`;
    }).join('');
    if (silences.length > 5) {
      el.innerHTML +=
        `<div style="font-size:10px;color:#888;padding:3px 0">
           + ${silences.length - 5} autre(s)…
         </div>`;
    }
  }
}

// ── Rythme & interruptions ────────────────────────────────────
function renderRhythm(data) {
  const el     = document.getElementById('rhythmRows');
  const aWpm   = data.agent_wpm;
  const cWpm   = data.client_wpm;
  const inter  = data.interruptions_count ?? null;

  const wpmRow = (label, code, val) => {
    if (val == null) {
      return `
        <div class="row-c">
          <span style="font-size:11px;flex:1">${label} <code>${code}</code></span>
          <span style="font-size:10px;color:#888">Non calculé — <code>emotions.py</code></span>
        </div>`;
    }
    return `
      <div class="row-c">
        <span style="font-size:11px;flex:1">${label} <code>${code}</code></span>
        <span style="font-weight:600;color:${wpmColor(val)}">${val} mots/min</span>
      </div>`;
  };

  el.innerHTML = `
    ${wpmRow('Débit agent',  'agent_wpm',  aWpm)}
    ${wpmRow('Débit client', 'client_wpm', cWpm)}
    <div class="row-c">
      <span style="font-size:11px;flex:1">Interruptions <code>interruptions_count</code></span>
      <span style="font-weight:600;color:${(inter ?? 0) > 3 ? '#791F1F' : '#633806'}">
        ${inter != null ? inter + ' fois' : '—'}
      </span>
    </div>`;
}

// ── Utilitaires ───────────────────────────────────────────────
function wpmColor(v) {
  if (v == null)  return '#1a1a18';
  if (v <= 160)   return '#1D9E75';
  if (v <= 200)   return '#EF9F27';
  return '#E24B4A';
}
function fmt(v)   { return v != null ? v : '—'; }
function fmtSec(s) {
  const m = Math.floor(s / 60), r = Math.round(s % 60);
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
    `<span style="font-size:11px;color:#791F1F;padding:4px 0">${escHtml(msg)}</span>`;
  ['emotionsAgent','emotionsClient','silenceRows','rhythmRows'].forEach(id => {
    document.getElementById(id).innerHTML =
      `<div style="font-size:11px;color:#888">—</div>`;
  });
  showToast(msg, 'error');
}
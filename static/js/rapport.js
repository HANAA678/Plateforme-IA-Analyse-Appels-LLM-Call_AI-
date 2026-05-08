/* ============================================================
   CallAI v2 — rapport.js
   Charge GET /api/calls/{call_id}/report
   Injecte : topbar, critères LLM, audio, superviseur,
             résumé IA, timeline, mots-clés
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const callId = params.get('call_id');
  if (!callId) {
    showGlobalError('Aucun call_id fourni dans l\'URL.');
    return;
  }
  loadRapport(callId);
});

// ── Chargement principal ──────────────────────────────────────
async function loadRapport(callId) {
  try {
    const res = await fetch(`/api/calls/${callId}/report`);
    if (res.status === 404) throw new Error('Appel introuvable.');
    if (res.status === 400) {
      const d = await res.json();
      throw new Error(d.detail || 'Appel non évalué.');
    }
    if (!res.ok) throw new Error('Erreur serveur.');
    const data = await res.json();

    renderTopbar(data.call, data.agent, data.evaluation);
    renderCriteria(data.evaluation, data.criteria_config);
    renderAudio(data.audio);
    renderSupervisor(data.call, data.evaluation);
    renderSummary(data.evaluation);
    renderTimeline(data.evaluation.timeline);
    renderKeywords(data.evaluation.keywords);
  } catch (e) {
    showGlobalError(e.message);
  }
}

// ── Topbar ────────────────────────────────────────────────────
function renderTopbar(call, agent, ev) {
  document.getElementById('rapportTitle').textContent =
    `Rapport — ${agent.full_name}`;

  const score      = ev.score_total ?? '—';
  const compClass  = complianceClass(ev.compliance);
  const typeClass  = typeClass2(call.call_type);
  const typeLabel  = TYPE_LABELS[call.call_type] || call.call_type || '—';
  const compLabel  = ev.compliance === 'non-conforme' ? 'Non-conforme'
                   : ev.compliance === 'conforme'     ? 'Conforme'
                   : ev.compliance === 'partiel'      ? 'Partiel' : '—';

  document.getElementById('rapportBadges').innerHTML = `
    <span class="badge-c ${scoreClass(ev.score_total)}">${score}/100</span>
    <span class="badge-c ${compClass}">${compLabel}</span>
    <span class="badge-c ${typeClass}">${typeLabel}</span>`;

  // Méta : date · durée · équipe
  const date = call.called_at ? formatDate(call.called_at) : '—';
  const dur  = call.duration_seconds ? formatDuration(call.duration_seconds) : '—';
  document.getElementById('rapportMeta').innerHTML =
    `${date} · ${dur} · ${escHtml(agent.team_name || '—')}
     &nbsp;<code>calls + evaluations + audio_metrics + criteria_config</code>`;
}

// ── Critères LLM ─────────────────────────────────────────────
function renderCriteria(ev, config) {
  const el = document.getElementById('criteriaRows');
  if (!config || config.length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:#888">Aucun critère configuré.</div>';
    return;
  }

  const scores = ev.criteria || {};
  el.innerHTML = config.map(c => {
    const got   = scores[c.key] ?? null;
    const max   = c.max_pts;
    const pct   = got != null ? (got / max * 100).toFixed(0) : 0;
    const color = got == null ? '#888'
                : got >= max * 0.8 ? '#1D9E75'
                : got >= max * 0.5 ? '#378ADD'
                : '#E24B4A';
    const label = got != null ? `${got}/${max}` : '—';
    const labelColor = got != null && got < max * 0.5 ? '#791F1F' : '';

    return `
      <div class="row-c">
        <span style="font-size:11px;flex:1">${escHtml(c.label)}</span>
        <div class="pbar" style="max-width:80px">
          <div class="pb" style="width:${pct}%;background:${color}"></div>
        </div>
        <span style="font-size:10px;min-width:32px;text-align:right;
                     font-weight:600;color:${labelColor}">
          ${label}
        </span>
      </div>`;
  }).join('');
}

// ── Métriques audio ───────────────────────────────────────────
function renderAudio(audio) {
  const el = document.getElementById('audioRows');
  if (!audio || Object.keys(audio).length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:#888">Aucune métrique audio.</div>';
    return;
  }

  const agentPct   = audio.agent_talk_pct  ?? '—';
  const clientPct  = audio.client_talk_pct ?? '—';
  const silencePct = audio.silence_pct     ?? '—';
  const silenceMax = audio.silence_max_sec ?? '—';
  const interrupts = audio.interruptions_count ?? '—';

  const agentDur  = durationFromPct(agentPct,  audio);
  const clientDur = durationFromPct(clientPct, audio);
  const silDur    = durationFromPct(silencePct, audio);

  el.innerHTML = `
    <div class="row-c">
      <span style="font-size:11px;flex:1">Parole agent</span>
      <span style="font-size:11px;color:#0C447C;font-weight:600">
        ${fmt(agentPct)}%${agentDur ? ' · ' + agentDur : ''}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Parole client</span>
      <span style="font-size:11px;font-weight:600">
        ${fmt(clientPct)}%${clientDur ? ' · ' + clientDur : ''}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Silence / attente</span>
      <span style="font-size:11px;color:#791F1F;font-weight:600">
        ${fmt(silencePct)}%${silDur ? ' · ' + silDur : ''}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Silence max</span>
      <span style="font-size:11px;color:#791F1F;font-weight:600">
        ${silenceMax !== '—' ? silenceMax + 's' : '—'}
      </span>
    </div>
    <div class="row-c">
      <span style="font-size:11px;flex:1">Interruptions</span>
      <span style="font-size:11px;color:#633806;font-weight:600">
        ${interrupts} fois
      </span>
    </div>`;
}

// ── Réponse superviseur ───────────────────────────────────────
function renderSupervisor(call, ev) {
  const block = document.getElementById('supervisorBlock');
  if (!call.focus_points && !ev.supervisor_feedback) return;

  block.style.display = '';
  document.getElementById('focusPointsText').textContent =
    call.focus_points || '(aucun point défini)';
  document.getElementById('supervisorFeedbackText').textContent =
    ev.supervisor_feedback || '(aucune réponse)';
}

// ── Résumé IA ─────────────────────────────────────────────────
function renderSummary(ev) {
  const el = document.getElementById('summaryBlocks');
  const rows = [
    { key: 'summary',     label: 'Sujet'          },
    { key: 'strengths',   label: 'Points forts'   },
    { key: 'weaknesses',  label: 'Points faibles' },
    { key: 'next_action', label: 'Action CRM'     },
  ];

  el.innerHTML = rows
    .filter(r => ev[r.key])
    .map(r => `
      <div class="rblk">
        <div class="rbt">${r.label}</div>
        ${escHtml(ev[r.key])}
      </div>`)
    .join('') || '<div style="font-size:11px;color:#888">Aucun résumé disponible.</div>';
}

// ── Timeline ──────────────────────────────────────────────────
const TIMELINE_COLORS = {
  ok:      '#1D9E75',
  warning: '#EF9F27',
  issue:   '#E24B4A',
};
const TIMELINE_TEXT = {
  ok:      '',
  warning: '#633806',
  issue:   '#791F1F',
};

function renderTimeline(timeline) {
  const el = document.getElementById('timelineRows');
  if (!timeline || timeline.length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:#888">Aucune timeline disponible.</div>';
    return;
  }

  el.innerHTML = timeline.map(t => {
    const dotColor  = TIMELINE_COLORS[t.type] || '#888';
    const textColor = TIMELINE_TEXT[t.type]   || '';
    const timeLabel = t.time_label || (t.time_sec != null ? fmtSec(t.time_sec) : '—');
    return `
      <div class="tl">
        <div class="tldot" style="background:${dotColor}"></div>
        <span style="min-width:36px;font-size:10px;color:#888">${escHtml(timeLabel)}</span>
        <span style="color:${textColor}">${escHtml(t.event || '')}</span>
      </div>`;
  }).join('');
}

// ── Mots-clés ─────────────────────────────────────────────────
const KW_CLASSES = ['br','ba','bg','bb','bgr','bp'];

function renderKeywords(keywords) {
  const el = document.getElementById('keywordsBlock');
  if (!keywords || keywords.length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:#888">Aucun mot-clé.</div>';
    return;
  }

  el.innerHTML = keywords.map((kw, i) => {
    const cls = KW_CLASSES[i % KW_CLASSES.length];
    return `<span class="badge-c ${cls}">${escHtml(kw)}</span>`;
  }).join('');
}

// ── Utilitaires ───────────────────────────────────────────────
function scoreClass(score) {
  if (score == null) return 'bgr';
  if (score >= 80)   return 'bg';
  if (score >= 60)   return 'ba';
  return 'br';
}

function complianceClass(c) {
  return c === 'conforme' ? 'bg' : c === 'partiel' ? 'ba' : 'br';
}

function typeClass2(t) {
  return { reclamation:'br', commercial:'bb', technique:'bp', information:'bgr' }[t] || 'bgr';
}

const TYPE_LABELS = {
  reclamation: 'Réclamation',
  information: 'Information',
  commercial:  'Commercial',
  technique:   'Technique',
};

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric'
  }) + ' · ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m${String(s).padStart(2, '0')}s`;
}

// Convertit un % de parole en durée lisible (si duration_seconds disponible)
function durationFromPct(pct, audio) {
  if (pct == null || pct === '—') return '';
  // On reconstitue la durée totale depuis agent+client+silence pct
  return '';   // optionnel — à enrichir si duration_seconds est dans le payload audio
}

function fmtSec(s) {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

function fmt(v) {
  return v != null ? v : '—';
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function showGlobalError(msg) {
  document.getElementById('rapportMeta').innerHTML =
    `<span style="color:#791F1F">${escHtml(msg)}</span>`;
  showToast(msg, 'error');
}
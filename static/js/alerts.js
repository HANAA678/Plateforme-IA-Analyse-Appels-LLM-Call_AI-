/* ============================================================
   CallAI v2 — alerts.js
   Gère : liste alertes, filtres, marquer comme traitée (modal)
   API  : GET /api/alerts  ·  PATCH /api/alerts/{id}/resolve
   ============================================================ */

let pendingAlertId = null;   // id de l'alerte en cours de traitement

document.addEventListener('DOMContentLoaded', loadAlerts);

// ── Chargement ────────────────────────────────────────────────
async function loadAlerts() {
  const severity = document.getElementById('fSeverity').value;
  const resolved = document.getElementById('fResolved').value;

  const params = new URLSearchParams();
  if (severity) params.set('severity', severity);
  params.set('resolved', resolved);

  try {
    const res  = await fetch(`/api/alerts?${params}`);
    if (!res.ok) throw new Error('Erreur API alerts');
    const data = await res.json();

    renderKPIs(data.stats);
    renderAlerts(data.alerts);
  } catch (e) {
    document.getElementById('alertsList').innerHTML =
      `<div style="font-size:11px;color:#791F1F;padding:8px 0">
         Impossible de charger les alertes.
       </div>`;
    showToast('Erreur chargement alertes', 'error');
  }
}

// ── KPIs ──────────────────────────────────────────────────────
function renderKPIs(stats) {
  if (!stats) return;
  document.getElementById('kpiCritical').textContent = stats.critical       ?? '—';
  document.getElementById('kpiMedium').textContent   = stats.medium         ?? '—';
  document.getElementById('kpiResolved').textContent = stats.resolved_today ?? '—';
}

// ── Config affichage par type d'alerte ───────────────────────
const ALERT_TYPE_LABELS = {
  churn_risk:   'Risque résiliation',
  compliance:   'Non-conformité légale',
  score_drop:   'Score trop bas',
  long_silence: 'Silence excessif',
  anger:        'Colère vocale client',
};
const ALERT_TYPE_CODES = {
  churn_risk:   'type=churn_risk',
  compliance:   'type=compliance',
  score_drop:   'type=score_drop',
  long_silence: 'type=long_silence',
  anger:        'type=anger',
};
const SEVERITY_CFG = {
  critical: { dotColor: '#E24B4A', badgeCls: 'br', label: 'Critique' },
  medium:   { dotColor: '#EF9F27', badgeCls: 'ba', label: 'Moyenne'  },
  info:     { dotColor: '#378ADD', badgeCls: 'bb', label: 'Info'     },
};

// ── Rendu liste ───────────────────────────────────────────────
function renderAlerts(alerts) {
  const el = document.getElementById('alertsList');

  if (!alerts || alerts.length === 0) {
    el.innerHTML = `
      <div style="text-align:center;padding:24px;color:#888;font-size:12px">
        ✓ Aucune alerte dans cette catégorie.
      </div>`;
    return;
  }

  el.innerHTML = alerts.map(a => buildAlertRow(a)).join('');
}

function buildAlertRow(a) {
  const sev      = SEVERITY_CFG[a.severity] || SEVERITY_CFG.info;
  const typeCode = ALERT_TYPE_CODES[a.type]  || `type=${a.type}`;
  const typeLabel = ALERT_TYPE_LABELS[a.type] || a.type;
  const agentName = escHtml(a.agent_name || '—');
  const triggeredAt = a.triggered_at ? formatDate(a.triggered_at) : '—';

  // Bloc "résolu par" si déjà traité
  const resolvedBlock = a.resolved
    ? `<div style="font-size:10px;color:#27500A;margin-top:3px">
         ✓ Traité par <strong>${escHtml(a.resolved_by || '—')}</strong>
         ${a.resolved_at ? ' · ' + formatDate(a.resolved_at) : ''}
       </div>`
    : '';

  // Boutons d'action
  const actionsHtml = a.resolved
    ? `<span class="badge-c bg" style="font-size:10px">Traitée</span>`
    : `<div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end">
         <span class="badge-c ${sev.badgeCls}">${sev.label}</span>
         <a href="/rapport?call_id=${a.call_id}"
            class="btn-c btn-sm" style="text-decoration:none;white-space:nowrap">
           Voir appel
         </a>
         <button class="btn-c btn-sm btn-success-sm"
                 onclick="openResolveModal('${escAttr(a.id)}','${escAttr(agentName + ' — ' + typeLabel)}')">
           Traiter ✓
         </button>
       </div>`;

  // Badge severity sur les alertes résolues
  const resolvedSevBadge = a.resolved
    ? `<span class="badge-c ${sev.badgeCls}" style="opacity:.5;font-size:10px">${sev.label}</span>`
    : '';

  return `
    <div class="alert-row" id="alert-${escAttr(a.id)}"
         style="${a.resolved ? 'opacity:.6' : ''}">
      <div class="adot" style="background:${sev.dotColor}${a.resolved ? ';opacity:.4' : ''}"></div>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;font-weight:600">
          ${typeLabel} — ${agentName}
          <code style="font-size:9px">${typeCode}</code>
        </div>
        <div style="font-size:10px;color:#888;margin-top:1px">
          ${triggeredAt}
          ${a.call_id ? ` · <a href="/rapport?call_id=${a.call_id}"
            style="color:#0C447C;text-decoration:none">Appel →</a>` : ''}
        </div>
        <div style="font-size:11px;margin-top:3px">${escHtml(a.message || '')}</div>
        ${resolvedBlock}
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;
                  align-items:flex-end;flex-shrink:0">
        ${resolvedSevBadge}
        ${actionsHtml}
      </div>
    </div>`;
}

// ── Modal traitement ──────────────────────────────────────────
function openResolveModal(alertId, desc) {
  pendingAlertId = alertId;
  document.getElementById('resolveDesc').textContent = desc;
  document.getElementById('resolvedBy').value        = '';
  const modal = document.getElementById('resolveModal');
  modal.style.display = 'flex';
  modal.onclick = e => { if (e.target === modal) closeResolveModal(); };
  setTimeout(() => document.getElementById('resolvedBy').focus(), 100);
}

function closeResolveModal() {
  document.getElementById('resolveModal').style.display = 'none';
  pendingAlertId = null;
}

async function confirmResolve() {
  if (!pendingAlertId) return;

  const resolvedBy = document.getElementById('resolvedBy').value.trim() || 'Superviseur';
  const btn        = document.getElementById('btnConfirmResolve');
  btn.disabled     = true;
  btn.textContent  = 'Traitement…';

  try {
    const res = await fetch(`/api/alerts/${pendingAlertId}/resolve`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ resolved_by: resolvedBy }),
    });

    if (res.status === 400) {
      const d = await res.json();
      throw new Error(d.detail || 'Alerte déjà traitée.');
    }
    if (!res.ok) throw new Error('Erreur serveur.');

    showToast('Alerte marquée comme traitée.', 'success');
    closeResolveModal();

    // Recharger pour mettre à jour KPIs + liste
    loadAlerts();

  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Confirmer ✓';
  }
}

// ── Utilitaires ───────────────────────────────────────────────
function formatDate(iso) {
  const d   = new Date(iso);
  const now = new Date();
  const isToday =
    d.getDate()     === now.getDate()     &&
    d.getMonth()    === now.getMonth()    &&
    d.getFullYear() === now.getFullYear();
  const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  return isToday
    ? `Auj. ${time}`
    : `${d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })} ${time}`;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Échappe pour les attributs HTML (onclick, id…)
function escAttr(s) {
  return String(s).replace(/'/g,"\\'").replace(/"/g,'&quot;');
}
from fastapi import APIRouter, Query
from core.database import fetchone, fetchall

router = APIRouter()


# ================================================================
# GET /api/dashboard
# ================================================================

@router.get("/api/dashboard")
def get_dashboard(period: str = Query("month", enum=["today", "week", "month"])):
    """
    Retourne toutes les données de la page Dashboard en une seule requête.
    Fait 6 requêtes SQL en interne.

    Paramètre :
        period → today / week / month  (filtre la période affichée)

    Utilisé par : page Dashboard (KPIs + graphiques + derniers appels)
    """

    # ── Traduire period en intervalle SQL ─────────────────────────
    interval_map = {
        "today": "1 day",
        "week":  "7 days",
        "month": "30 days",
    }
    interval = interval_map.get(period, "30 days")

    # ================================================================
    # 1. KPIs principaux
    # ================================================================
    kpis = fetchone("""
        SELECT
            COUNT(c.id)::int                              AS total_calls,
            ROUND(AVG(e.score_total)::numeric, 1)         AS avg_score,
            ROUND(
                100.0 * COUNT(CASE WHEN e.compliance = 'conforme' THEN 1 END)
                / NULLIF(COUNT(e.id), 0), 1
            )                                             AS compliance_rate
        FROM calls c
        LEFT JOIN evaluations e ON e.call_id = c.id
        WHERE c.called_at >= NOW() - INTERVAL %s
          AND c.status = 'evaluated'
    """, (interval,))

    # ================================================================
    # 2. Nombre d'alertes critiques non traitées
    # ================================================================
    alerts_row = fetchone("""
        SELECT COUNT(*)::int AS critical_alerts
        FROM alerts
        WHERE severity = 'critical'
          AND resolved = false
    """)

    # ================================================================
    # 3. Score moyen par équipe
    # ================================================================
    scores_by_team = fetchall("""
        SELECT
            t.name                                        AS team_name,
            ROUND(AVG(e.score_total)::numeric, 1)         AS avg_score,
            COUNT(c.id)::int                              AS total_calls
        FROM calls c
        JOIN evaluations e ON e.call_id = c.id
        JOIN agents a      ON a.id = c.agent_id
        JOIN teams t       ON t.id = a.team_id
        WHERE c.called_at >= NOW() - INTERVAL %s
          AND c.status = 'evaluated'
        GROUP BY t.id, t.name
        ORDER BY avg_score DESC
    """, (interval,))

    # ================================================================
    # 4. Répartition des appels par type
    # ================================================================
    calls_by_type_rows = fetchall("""
        SELECT call_type, COUNT(*)::int AS total
        FROM calls
        WHERE called_at >= NOW() - INTERVAL %s
          AND status = 'evaluated'
        GROUP BY call_type
    """, (interval,))

    calls_by_type = {r["call_type"]: r["total"] for r in calls_by_type_rows} if calls_by_type_rows else {}

    # ================================================================
    # 5. Répartition conformité (pour le graphique donut)
    # ================================================================
    compliance_rows = fetchall("""
        SELECT compliance, COUNT(*)::int AS total
        FROM evaluations e
        JOIN calls c ON c.id = e.call_id
        WHERE c.called_at >= NOW() - INTERVAL %s
          AND c.status = 'evaluated'
        GROUP BY compliance
    """, (interval,))

    compliance_breakdown = {r["compliance"]: r["total"] for r in compliance_rows} if compliance_rows else {}

    # ================================================================
    # 6. Derniers appels évalués (tableau du bas)
    # ================================================================
    recent_calls = fetchall("""
        SELECT
            c.id                                          AS call_id,
            a.full_name                                   AS agent_name,
            a.initials                                    AS agent_initials,
            t.name                                        AS team_name,
            c.called_at,
            c.duration_seconds,
            c.call_type,
            c.priority,
            e.score_total,
            e.compliance,
            e.sentiment_client
        FROM calls c
        JOIN evaluations e ON e.call_id = c.id
        JOIN agents a      ON a.id = c.agent_id
        LEFT JOIN teams t  ON t.id = a.team_id
        WHERE c.called_at >= NOW() - INTERVAL %s
          AND c.status = 'evaluated'
        ORDER BY c.called_at DESC
        LIMIT 10
    """, (interval,))

    # ================================================================
    # Assembler la réponse
    # ================================================================
    kpis_data      = dict(kpis)      if kpis      else {}
    alerts_data    = dict(alerts_row) if alerts_row else {}

    return {
        "period": period,

        # KPIs
        "total_calls":        kpis_data.get("total_calls",     0),
        "avg_score":          float(kpis_data.get("avg_score", 0) or 0),
        "compliance_rate":    float(kpis_data.get("compliance_rate", 0) or 0),
        "critical_alerts":    alerts_data.get("critical_alerts", 0),

        # Graphiques
        "scores_by_team":     [dict(r) for r in scores_by_team]  if scores_by_team  else [],
        "calls_by_type":      calls_by_type,
        "compliance_breakdown": compliance_breakdown,

        # Tableau derniers appels
        "recent_calls": [
            {
                "call_id":        str(r["call_id"]),
                "agent_name":     r["agent_name"],
                "agent_initials": r["agent_initials"],
                "team_name":      r["team_name"],
                "called_at":      r["called_at"].isoformat() if r["called_at"] else None,
                "duration_seconds": r["duration_seconds"],
                "call_type":      r["call_type"],
                "priority":       r["priority"],
                "score_total":    r["score_total"],
                "compliance":     r["compliance"],
                "sentiment_client": r["sentiment_client"],
            }
            for r in recent_calls
        ] if recent_calls else [],
    }

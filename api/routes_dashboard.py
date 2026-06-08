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
        "today": 1,
        "week":  7,
        "month": 30,
    }
    interval_days = interval_map.get(period, 30)
    since = f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {interval_days} DAY)"

    # ================================================================
    # 1. KPIs principaux
    # ================================================================
    kpis = fetchone(f"""
        SELECT
            COUNT(c.id)                                           AS total_calls,
            ROUND(AVG(e.score_total), 1)                          AS avg_score,
            ROUND(
                100.0 * COUNTIF(e.compliance = 'conforme')
                / NULLIF(COUNT(e.id), 0), 1
            )                                                     AS compliance_rate
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c
        LEFT JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e ON e.call_id = c.id
        WHERE c.called_at >= {since}
          AND c.status = 'evaluated'
    """)

    # ================================================================
    # 2. Nombre d'alertes critiques non traitées
    # ================================================================
    alerts_row = fetchone("""
        SELECT COUNTIF(severity = 'critical' AND resolved = false) AS critical_alerts
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.alerts`
    """)

    # ================================================================
    # 3. Score moyen par équipe
    # ================================================================
    scores_by_team = fetchall(f"""
        SELECT
            t.name                                        AS team_name,
            ROUND(AVG(e.score_total), 1)                  AS avg_score,
            COUNT(c.id)                                   AS total_calls
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e ON e.call_id = c.id
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` a      ON a.id = c.agent_id
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` t       ON t.id = a.team_id
        WHERE c.called_at >= {since}
          AND c.status = 'evaluated'
        GROUP BY t.id, t.name
        ORDER BY avg_score DESC
    """)

    # ================================================================
    # 4. Répartition des appels par type
    # ================================================================
    calls_by_type_rows = fetchall(f"""
        SELECT call_type, COUNT(*) AS total
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls`
        WHERE called_at >= {since}
          AND status = 'evaluated'
        GROUP BY call_type
    """)

    calls_by_type = {r["call_type"]: r["total"] for r in calls_by_type_rows} if calls_by_type_rows else {}

    # ================================================================
    # 5. Répartition conformité (pour le graphique donut)
    # ================================================================
    compliance_rows = fetchall(f"""
        SELECT compliance, COUNT(*) AS total
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c ON c.id = e.call_id
        WHERE c.called_at >= {since}
          AND c.status = 'evaluated'
        GROUP BY compliance
    """)

    compliance_breakdown = {r["compliance"]: r["total"] for r in compliance_rows} if compliance_rows else {}

    # ================================================================
    # 6. Derniers appels évalués (tableau du bas)
    # ================================================================
    recent_calls = fetchall(f"""
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
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e ON e.call_id = c.id
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` a      ON a.id = c.agent_id
        LEFT JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` t  ON t.id = a.team_id
        WHERE c.called_at >= {since}
          AND c.status = 'evaluated'
        ORDER BY c.called_at DESC
        LIMIT 10
    """)

    # ================================================================
    # Assembler la réponse
    # ================================================================
    kpis_data   = dict(kpis)      if kpis      else {}
    alerts_data = dict(alerts_row) if alerts_row else {}

    return {
        "period": period,

        # KPIs
        "total_calls":     kpis_data.get("total_calls",     0),
        "avg_score":       float(kpis_data.get("avg_score", 0) or 0),
        "compliance_rate": float(kpis_data.get("compliance_rate", 0) or 0),
        "critical_alerts": alerts_data.get("critical_alerts", 0),

        # Graphiques
        "scores_by_team":       [dict(r) for r in scores_by_team] if scores_by_team else [],
        "calls_by_type":        calls_by_type,
        "compliance_breakdown": compliance_breakdown,

        # Tableau derniers appels
        "recent_calls": [
            {
                "call_id":          str(r["call_id"]),
                "agent_name":       r["agent_name"],
                "agent_initials":   r["agent_initials"],
                "team_name":        r["team_name"],
                "called_at":        r["called_at"].isoformat() if r["called_at"] else None,
                "duration_seconds": r["duration_seconds"],
                "call_type":        r["call_type"],
                "priority":         r["priority"],
                "score_total":      r["score_total"],
                "compliance":       r["compliance"],
                "sentiment_client": r["sentiment_client"],
            }
            for r in recent_calls
        ] if recent_calls else [],
    }
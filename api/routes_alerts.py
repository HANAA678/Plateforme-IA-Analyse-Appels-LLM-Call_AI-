from fastapi import APIRouter, Query, HTTPException
from core.database import fetchone, fetchall, execute
from datetime import datetime

router = APIRouter()


# ================================================================
# GET /api/alerts
# ================================================================

@router.get("/api/alerts")
def get_alerts(
    severity: str = Query(None, enum=["critical", "medium", "info"]),
    resolved: str = Query("false", enum=["false", "true", "all"]),
):
    """
    Retourne la liste des alertes avec leurs stats.
    Utilisé par : page Alertes + badge Dashboard
    """

    # Stats globales
    stats_row = fetchone("""
        SELECT
            COUNT(CASE WHEN severity = 'critical' AND resolved = false THEN 1 END)::int AS critical,
            COUNT(CASE WHEN severity = 'medium'   AND resolved = false THEN 1 END)::int AS medium,
            COUNT(CASE WHEN resolved = true
                        AND resolved_at >= NOW() - INTERVAL '1 day' THEN 1 END)::int    AS resolved_today
        FROM alerts
    """)

    # Filtres dynamiques
    filters = []
    params  = []

    if severity:
        filters.append("a.severity = %s")
        params.append(severity)

    if resolved == "false":
        filters.append("a.resolved = false")
    elif resolved == "true":
        filters.append("a.resolved = true")

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    rows = fetchall(f"""
        SELECT
            a.id,
            a.type,
            a.severity,
            a.message,
            a.resolved,
            a.resolved_by,
            a.resolved_at,
            a.triggered_at,
            a.call_id,
            ag.full_name  AS agent_name,
            ag.initials   AS agent_initials
        FROM alerts a
        JOIN agents ag ON ag.id = a.agent_id
        {where_clause}
        ORDER BY
            a.resolved ASC,
            CASE a.severity WHEN 'critical' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            a.triggered_at DESC
    """, params if params else None)

    return {
        "stats": {
            "critical":       stats_row["critical"]       if stats_row else 0,
            "medium":         stats_row["medium"]         if stats_row else 0,
            "resolved_today": stats_row["resolved_today"] if stats_row else 0,
        },
        "alerts": [
            {
                "id":             str(r["id"]),
                "type":           r["type"],
                "severity":       r["severity"],
                "message":        r["message"],
                "resolved":       r["resolved"],
                "resolved_by":    r["resolved_by"],
                "resolved_at":    r["resolved_at"].isoformat()  if r["resolved_at"]  else None,
                "triggered_at":   r["triggered_at"].isoformat() if r["triggered_at"] else None,
                "call_id":        str(r["call_id"]),
                "agent_name":     r["agent_name"],
                "agent_initials": r["agent_initials"],
            }
            for r in rows
        ] if rows else [],
    }


# ================================================================
# PATCH /api/alerts/{id}/resolve
# ================================================================

@router.patch("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, body: dict):
    """
    Marque une alerte comme traitée.
    Body : { "resolved_by": "Nom du superviseur" }
    Utilisé par : page Alertes (bouton "Traiter")
    """
    alert = fetchone("SELECT id, resolved FROM alerts WHERE id = %s", (alert_id,))
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable.")
    if alert["resolved"]:
        raise HTTPException(status_code=400, detail="Cette alerte est deja traitee.")

    resolved_by = body.get("resolved_by", "").strip() or "Superviseur"
    now         = datetime.utcnow()

    execute("""
        UPDATE alerts
        SET resolved    = true,
            resolved_by = %s,
            resolved_at = %s
        WHERE id = %s
    """, (resolved_by, now, alert_id))

    return {
        "id":          alert_id,
        "resolved":    True,
        "resolved_by": resolved_by,
        "resolved_at": now.isoformat(),
    }

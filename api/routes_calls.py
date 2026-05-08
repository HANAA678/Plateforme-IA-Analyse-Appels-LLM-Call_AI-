from fastapi import APIRouter, Query, HTTPException
from core.database import fetchone, fetchall

router = APIRouter()


# ================================================================
# GET /api/calls  — liste filtrée + pagination
# ================================================================

@router.get("/api/calls")
def get_calls(
    period:    str = Query("month", enum=["today", "week", "month"]),
    score:     str = Query(None,    enum=["high", "medium", "low"]),
    agent_id:  str = Query(None),
    team_id:   str = Query(None),
    call_type: str = Query(None,    enum=["reclamation", "commercial", "technique", "information"]),
    priority:  str = Query(None,    enum=["normale", "haute", "urgente"]),
    search:    str = Query(None),
    page:      int = Query(1, ge=1),
):
    """
    Retourne la liste filtrée des appels avec pagination (25 par page).
    Utilisé par : page Appels (tableau + filtres)
    """

    interval_map = {"today": "1 day", "week": "7 days", "month": "30 days"}
    interval = interval_map.get(period, "30 days")

    # ── Construire les filtres dynamiquement ──────────────────────
    filters = ["c.called_at >= NOW() - INTERVAL %s", "c.status = 'evaluated'"]
    params  = [interval]

    if agent_id:
        filters.append("c.agent_id = %s")
        params.append(agent_id)

    if team_id:
        filters.append("a.team_id = %s")
        params.append(team_id)

    if call_type:
        filters.append("c.call_type = %s")
        params.append(call_type)

    if priority:
        filters.append("c.priority = %s")
        params.append(priority)

    if search:
        filters.append("a.full_name ILIKE %s")
        params.append(f"%{search}%")

    if score == "high":
        filters.append("e.score_total >= 70")
    elif score == "medium":
        filters.append("e.score_total >= 40 AND e.score_total < 70")
    elif score == "low":
        filters.append("e.score_total < 40")

    where_clause = " AND ".join(filters)

    # ── Compter le total (pour la pagination) ────────────────────
    count_row = fetchone(f"""
        SELECT COUNT(*)::int AS total
        FROM calls c
        JOIN evaluations e ON e.call_id = c.id
        JOIN agents a      ON a.id = c.agent_id
        WHERE {where_clause}
    """, params)

    total = count_row["total"] if count_row else 0

    # ── Récupérer la page demandée ───────────────────────────────
    limit  = 25
    offset = (page - 1) * limit

    rows = fetchall(f"""
        SELECT
            c.id                AS call_id,
            a.full_name         AS agent_name,
            a.initials          AS agent_initials,
            t.name              AS team_name,
            c.called_at,
            c.duration_seconds,
            c.call_type,
            c.priority,
            c.status,
            e.score_total,
            e.compliance,
            e.sentiment_client,
            e.sentiment_agent
        FROM calls c
        JOIN evaluations e ON e.call_id = c.id
        JOIN agents a      ON a.id = c.agent_id
        LEFT JOIN teams t  ON t.id = a.team_id
        WHERE {where_clause}
        ORDER BY c.called_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])

    return {
        "total":       total,
        "page":        page,
        "total_pages": (total + limit - 1) // limit,
        "calls": [
            {
                "call_id":          str(r["call_id"]),
                "agent_name":       r["agent_name"],
                "agent_initials":   r["agent_initials"],
                "team_name":        r["team_name"],
                "called_at":        r["called_at"].isoformat() if r["called_at"] else None,
                "duration_seconds": r["duration_seconds"],
                "call_type":        r["call_type"],
                "priority":         r["priority"],
                "status":           r["status"],
                "score_total":      r["score_total"],
                "compliance":       r["compliance"],
                "sentiment_client": r["sentiment_client"],
                "sentiment_agent":  r["sentiment_agent"],
            }
            for r in rows
        ] if rows else [],
    }


# ================================================================
# GET /api/calls/{id}/report  — rapport complet
# ================================================================

@router.get("/api/calls/{call_id}/report")
def get_call_report(call_id: str):
    """
    Retourne le rapport complet d'un appel.
    Joint 5 tables : calls + agents + teams + evaluations + audio_metrics + criteria_config
    Utilisé par : page Rapport
    """

    # ── Appel + agent + équipe ────────────────────────────────────
    call = fetchone("""
        SELECT
            c.id,
            c.called_at,
            c.duration_seconds,
            c.call_type,
            c.priority,
            c.status,
            c.language,
            c.supervisor_notes,
            c.focus_points,
            c.waveform_data,
            a.id            AS agent_id,
            a.full_name     AS agent_name,
            a.initials      AS agent_initials,
            a.email         AS agent_email,
            t.name          AS team_name
        FROM calls c
        JOIN agents a      ON a.id = c.agent_id
        LEFT JOIN teams t  ON t.id = a.team_id
        WHERE c.id = %s
    """, (call_id,))

    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable.")

    if call["status"] != "evaluated":
        raise HTTPException(status_code=400, detail=f"Appel non encore évalué (status={call['status']}).")

    # ── Évaluation Gemini ─────────────────────────────────────────
    evaluation = fetchone("""
        SELECT
            score_total,
            criteria,
            criteria_justifications,
            compliance,
            sentiment_client,
            sentiment_agent,
            summary,
            strengths,
            weaknesses,
            next_action,
            supervisor_feedback,
            timeline,
            keywords,
            evaluated_at
        FROM evaluations
        WHERE call_id = %s
    """, (call_id,))

    # ── Métriques audio ───────────────────────────────────────────
    audio = fetchone("""
        SELECT
            agent_talk_pct,
            client_talk_pct,
            silence_pct,
            silence_max_sec,
            interruptions_count,
            silences,
            diarization
        FROM audio_metrics
        WHERE call_id = %s
    """, (call_id,))

    # ── Grille des critères (pour afficher les barres avec labels) ─
    criteria_config = fetchall("""
        SELECT key, label, max_pts, is_active
        FROM criteria_config
        WHERE is_active = TRUE
        ORDER BY sort_order
    """)

    # ── Assembler la réponse ──────────────────────────────────────
    return {
        "call": {
            "id":               str(call["id"]),
            "called_at":        call["called_at"].isoformat() if call["called_at"] else None,
            "duration_seconds": call["duration_seconds"],
            "call_type":        call["call_type"],
            "priority":         call["priority"],
            "status":           call["status"],
            "language":         call["language"],
            "supervisor_notes": call["supervisor_notes"],
            "focus_points":     call["focus_points"],
            "waveform_data":    call["waveform_data"] or [],
        },
        "agent": {
            "id":       str(call["agent_id"]),
            "full_name": call["agent_name"],
            "initials":  call["agent_initials"],
            "email":     call["agent_email"],
            "team_name": call["team_name"],
        },
        "evaluation": {
            "score_total":              evaluation["score_total"],
            "criteria":                 evaluation["criteria"]                or {},
            "criteria_justifications":  evaluation["criteria_justifications"] or {},
            "compliance":               evaluation["compliance"],
            "sentiment_client":         evaluation["sentiment_client"],
            "sentiment_agent":          evaluation["sentiment_agent"],
            "summary":                  evaluation["summary"],
            "strengths":                evaluation["strengths"],
            "weaknesses":               evaluation["weaknesses"],
            "next_action":              evaluation["next_action"],
            "supervisor_feedback":      evaluation["supervisor_feedback"],
            "timeline":                 evaluation["timeline"]  or [],
            "keywords":                 evaluation["keywords"]  or [],
            "evaluated_at":             evaluation["evaluated_at"].isoformat() if evaluation["evaluated_at"] else None,
        } if evaluation else {},
        "audio": {
            "agent_talk_pct":       audio["agent_talk_pct"],
            "client_talk_pct":      audio["client_talk_pct"],
            "silence_pct":          audio["silence_pct"],
            "silence_max_sec":      audio["silence_max_sec"],
            "interruptions_count":  audio["interruptions_count"],
            "silences":             audio["silences"]     or [],
            "diarization":          audio["diarization"]  or [],
        } if audio else {},
        "criteria_config": [
            {"key": r["key"], "label": r["label"], "max_pts": r["max_pts"]}
            for r in criteria_config
        ] if criteria_config else [],
    }


# ================================================================
# GET /api/calls/{id}/audio  — métriques audio seules
# ================================================================

@router.get("/api/calls/{call_id}/audio")
def get_call_audio(call_id: str):
    """
    Retourne uniquement les métriques du signal WAV.
    Utilisé par : page Analyse audio (graphiques waveform + diarisation)
    """
    call = fetchone("SELECT waveform_data FROM calls WHERE id = %s", (call_id,))
    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable.")

    audio = fetchone("""
        SELECT
            agent_talk_pct,
            client_talk_pct,
            silence_pct,
            silence_max_sec,
            interruptions_count,
            silences,
            diarization
        FROM audio_metrics
        WHERE call_id = %s
    """, (call_id,))

    if not audio:
        raise HTTPException(status_code=404, detail="Métriques audio introuvables.")

    return {
        "waveform_data":        call["waveform_data"]        or [],
        "agent_talk_pct":       audio["agent_talk_pct"],
        "client_talk_pct":      audio["client_talk_pct"],
        "silence_pct":          audio["silence_pct"],
        "silence_max_sec":      audio["silence_max_sec"],
        "interruptions_count":  audio["interruptions_count"],
        "silences":             audio["silences"]    or [],
        "diarization":          audio["diarization"] or [],
    }


# ================================================================
# GET /api/calls/{id}/audio-url  — URL du fichier audio
# ================================================================

@router.get("/api/calls/{call_id}/audio-url")
def get_audio_url(call_id: str):
    """
    Retourne le chemin local du fichier .wav pour le lecteur audio HTML.
    Utilisé par : page Rapport + page Analyse audio (lecteur audio)
    """
    row = fetchone("SELECT audio_url FROM calls WHERE id = %s", (call_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Appel introuvable.")

    return {"call_id": call_id, "url": row["audio_url"]}

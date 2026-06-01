from pipeline.transcribe import (
    transcribe_audio,
    align_with_gemini,
    compute_waveform,
)
from pipeline.diarize import diarize_audio
from pipeline.evaluate import evaluate_transcription
from pipeline.alerts import generate_alerts

import json


def run_pipeline(call_id, audio_path, execute, fetchone, fetchall):

    # ================================================================
    # 1. TRANSCRIPTION
    # ================================================================
    result = transcribe_audio(audio_path)

    text     = result["text"]
    segments = result.get("segments", [])
    duration = result.get("duration", 300)
    language = result.get("language", "fr")

    waveform = compute_waveform(audio_path)

    execute("""
        UPDATE calls
        SET transcription_text = %s,
            duration_seconds   = %s,
            language           = %s,
            waveform_data      = %s,
            status             = 'transcribed'
        WHERE id = %s
    """, (text, int(duration), language, json.dumps(waveform), call_id))

    print(f"✅ Transcribed — durée={int(duration)}s")
    print("CALL ID =", call_id)
    print("AUDIO PATH =", audio_path)
    # ================================================================
    # 2. DIARISATION
    # ================================================================
    diar = diarize_audio(audio_path, total_duration=duration)

    execute("""
        INSERT INTO audio_metrics (
            call_id,
            agent_talk_pct,
            client_talk_pct,
            silence_pct,
            silence_max_sec,
            interruptions_count,
            silences,
            diarization
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (call_id) DO UPDATE SET
            agent_talk_pct      = EXCLUDED.agent_talk_pct,
            client_talk_pct     = EXCLUDED.client_talk_pct,
            silence_pct         = EXCLUDED.silence_pct,
            silence_max_sec     = EXCLUDED.silence_max_sec,
            interruptions_count = EXCLUDED.interruptions_count,
            silences            = EXCLUDED.silences,
            diarization         = EXCLUDED.diarization
    """, (
        call_id,
        diar["agent_talk_pct"],
        diar["client_talk_pct"],
        diar["silence_pct"],
        diar["silence_max_sec"],
        diar["interruptions_count"],
        json.dumps(diar["silences"]),#json.dumps permet de transformer un objet en json car silences est une list et sql ne peut pas stocker ca directement 
        json.dumps(diar["diarization"]),
    ))

    print("✅ Diarized")

    # ================================================================
    # 3. ALIGNEMENT  Agent: / Client:
    # ================================================================
    aligned_text = align_with_gemini(
        diar["diarization"],
        segments,
    )

    execute("""
        UPDATE calls
        SET transcription_text = %s
        WHERE id = %s
    """, (aligned_text, call_id))

    print("✅ Aligned")
    print(aligned_text[:400])
    print(aligned_text)

    # ================================================================
    # 4. ÉVALUATION GEMINI
    # ================================================================
    #RECUPERER supervisor_notes et focus_points from calls
    call_row = fetchone("""
        SELECT supervisor_notes, focus_points
        FROM calls
        WHERE id = %s
    """, (call_id,))

    supervisor_notes = (call_row or {}).get("supervisor_notes", "") or ""
    focus_points     = (call_row or {}).get("focus_points",     "") or ""
#recupere les critères valides  
    rows = fetchall("""
        SELECT key, label, max_pts, description, is_active
        FROM criteria_config
        WHERE is_active = TRUE
        ORDER BY sort_order
    """)
    #on stocke ds criteria_config les critere valide (criteria_config contient key label max_pts description is_active)
    criteria_config = [dict(row) for row in rows] if rows else []

    if not criteria_config: # cad aucun critere n as ete retourné depuis bd alors criteria_config on utiise des autres criteres par defaut 
        criteria_config = [
            {"key": "greeting",   "label": "Accueil & présentation", "max_pts": 20, "description": "Accueil professionnel",          "is_active": True},
            {"key": "listening",  "label": "Écoute active",           "max_pts": 20, "description": "Reformulation et compréhension", "is_active": True},
            {"key": "solution",   "label": "Résolution",              "max_pts": 20, "description": "Résoudre le problème client",    "is_active": True},
            {"key": "compliance", "label": "Conformité",              "max_pts": 20, "description": "Respect des procédures",         "is_active": True},
            {"key": "closing",    "label": "Clôture",                 "max_pts": 20, "description": "Conclusion et synthèse",         "is_active": True},
        ]
        print("[runner] ⚠️ criteria_config vide — valeurs par défaut utilisées")

    print(f"[runner] Envoi à Gemini — {len(aligned_text)} caractères, {len(criteria_config)} critères")

    evaluation = evaluate_transcription(
        transcription    = aligned_text,
        criteria_config  = criteria_config,
        supervisor_notes = supervisor_notes,
        focus_points     = focus_points,
        thresholds       = {"compliance": 70, "alert": 40},
    )

    execute("""
        INSERT INTO evaluations (
            call_id,
            score_total,
            criteria,
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
            criteria_justifications,
            evaluated_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        ON CONFLICT (call_id) DO UPDATE SET
            score_total             = EXCLUDED.score_total,
            criteria                = EXCLUDED.criteria,
            compliance              = EXCLUDED.compliance,
            sentiment_client        = EXCLUDED.sentiment_client,
            sentiment_agent         = EXCLUDED.sentiment_agent,
            summary                 = EXCLUDED.summary,
            strengths               = EXCLUDED.strengths,
            weaknesses              = EXCLUDED.weaknesses,
            next_action             = EXCLUDED.next_action,
            supervisor_feedback     = EXCLUDED.supervisor_feedback,
            timeline                = EXCLUDED.timeline,
            keywords                = EXCLUDED.keywords,
            criteria_justifications = EXCLUDED.criteria_justifications,
            evaluated_at            = NOW()
    """, (
        call_id,
        evaluation["score_total"],
        json.dumps(evaluation["criteria"]),
        evaluation["compliance"],
        evaluation["sentiment_client"],
        evaluation["sentiment_agent"],
        evaluation["summary"],
        evaluation["strengths"],
        evaluation["weaknesses"],
        evaluation["next_action"],
        evaluation["supervisor_feedback"],
        json.dumps(evaluation["timeline"]),
        json.dumps(evaluation["keywords"]),
        json.dumps(evaluation["criteria_justifications"]),
    ))

    execute("""
        UPDATE calls SET status = 'evaluated' WHERE id = %s
    """, (call_id,))

    print(f"✅ Evaluated — score={evaluation['score_total']}, compliance={evaluation['compliance']}")


# ================================================================
# alerts
# ================================================================


    call_row_agent = fetchone("SELECT agent_id FROM calls WHERE id = %s", (call_id,))
    agent_id = (call_row_agent or {}).get("agent_id", "")
    generate_alerts(call_id=call_id, agent_id=agent_id, evaluation=evaluation, diar=diar)
    # ================================================================
    # 5. REFRESH STATS AGENT
    # ================================================================
    _refresh_agent_stats(call_id=call_id, fetchone=fetchone, execute=execute)

    print("✅ Pipeline terminé")
    return aligned_text



# ================================================================
# Helper privé
# ================================================================

def _refresh_agent_stats(call_id, fetchone, execute):
    call_row = fetchone("SELECT agent_id FROM calls WHERE id = %s", (call_id,))
    agent_id = (call_row or {}).get("agent_id")
    if not agent_id:
        return

    stats = fetchone("""
        SELECT
            COUNT(*)::int                         AS total_calls,
            ROUND(AVG(e.score_total)::numeric, 1) AS avg_score
        FROM calls c
        JOIN evaluations e ON e.call_id = c.id
        WHERE c.agent_id = %s
          AND c.called_at >= NOW() - INTERVAL '30 days'
          AND c.status = 'evaluated'
    """, (agent_id,))

    if stats:
        execute("""
            UPDATE agents SET avg_score = %s, total_calls = %s WHERE id = %s
        """, (stats["avg_score"] or 0, stats["total_calls"] or 0, agent_id))
        print(f"✅ Stats agent — avg={stats['avg_score']}, calls={stats['total_calls']}")





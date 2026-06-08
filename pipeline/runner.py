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
        UPDATE `dda-dpl-datalab-sdbx-za.SpeakFlow.calls`
        SET transcription_text = @text,
            duration_seconds   = @duration,
            language           = @language,
            waveform_data      = PARSE_JSON(@waveform),
            status             = 'transcribed'
        WHERE id = @call_id
    """, {
        "text":     text,
        "duration": int(duration),
        "language": language,
        "waveform": json.dumps(waveform),
        "call_id":  call_id,
    })

    print(f"✅ Transcribed — durée={int(duration)}s")
    print("CALL ID =", call_id)
    print("AUDIO PATH =", audio_path)

    # ================================================================
    # 2. DIARISATION
    # ================================================================
    diar = diarize_audio(audio_path, total_duration=duration)

    execute("""
        MERGE `dda-dpl-datalab-sdbx-za.SpeakFlow.audio_metrics` T
        USING (SELECT @call_id AS call_id) S
        ON T.call_id = S.call_id
        WHEN MATCHED THEN UPDATE SET
            agent_talk_pct      = @agent_talk_pct,
            client_talk_pct     = @client_talk_pct,
            silence_pct         = @silence_pct,
            silence_max_sec     = @silence_max_sec,
            interruptions_count = @interruptions_count,
            silences            = PARSE_JSON(@silences),
            diarization         = PARSE_JSON(@diarization)
        WHEN NOT MATCHED THEN INSERT (
            call_id, agent_talk_pct, client_talk_pct,
            silence_pct, silence_max_sec, interruptions_count,
            silences, diarization
        ) VALUES (
            @call_id, @agent_talk_pct, @client_talk_pct,
            @silence_pct, @silence_max_sec, @interruptions_count,
            PARSE_JSON(@silences), PARSE_JSON(@diarization)
        )
    """, {
        "call_id":            call_id,
        "agent_talk_pct":     diar["agent_talk_pct"],
        "client_talk_pct":    diar["client_talk_pct"],
        "silence_pct":        diar["silence_pct"],
        "silence_max_sec":    diar["silence_max_sec"],
        "interruptions_count":diar["interruptions_count"],
        "silences":           json.dumps(diar["silences"]),
        "diarization":        json.dumps(diar["diarization"]),
    })

    print("✅ Diarized")

    # ================================================================
    # 3. ALIGNEMENT  Agent: / Client:
    # ================================================================
    aligned_text = align_with_gemini(
        diar["diarization"],
        segments,
    )

    execute("""
        UPDATE `dda-dpl-datalab-sdbx-za.SpeakFlow.calls`
        SET transcription_text = @aligned_text
        WHERE id = @call_id
    """, {"aligned_text": aligned_text, "call_id": call_id})

    print("✅ Aligned")
    print(aligned_text[:400])
    print(aligned_text)

    # ================================================================
    # 4. ÉVALUATION GEMINI
    # ================================================================
    call_row = fetchone("""
        SELECT supervisor_notes, focus_points
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls`
        WHERE id = @call_id
    """, {"call_id": call_id})

    supervisor_notes = (call_row or {}).get("supervisor_notes", "") or ""
    focus_points     = (call_row or {}).get("focus_points",     "") or ""

    rows = fetchall("""
        SELECT key, label, max_pts, description, is_active
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.criteria_config`
        WHERE is_active = TRUE
        ORDER BY sort_order
    """)
    criteria_config = [dict(row) for row in rows] if rows else []

    if not criteria_config:
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
        MERGE `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` T
        USING (SELECT @call_id AS call_id) S
        ON T.call_id = S.call_id
        WHEN MATCHED THEN UPDATE SET
            score_total             = @score_total,
            criteria                = PARSE_JSON(@criteria),
            compliance              = @compliance,
            sentiment_client        = @sentiment_client,
            sentiment_agent         = @sentiment_agent,
            summary                 = @summary,
            strengths               = @strengths,
            weaknesses              = @weaknesses,
            next_action             = @next_action,
            supervisor_feedback     = @supervisor_feedback,
            timeline                = PARSE_JSON(@timeline),
            keywords                = PARSE_JSON(@keywords),
            criteria_justifications = PARSE_JSON(@criteria_justifications),
            evaluated_at            = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (
            call_id, score_total, criteria, compliance,
            sentiment_client, sentiment_agent, summary,
            strengths, weaknesses, next_action, supervisor_feedback,
            timeline, keywords, criteria_justifications, evaluated_at
        ) VALUES (
            @call_id, @score_total, PARSE_JSON(@criteria), @compliance,
            @sentiment_client, @sentiment_agent, @summary,
            @strengths, @weaknesses, @next_action, @supervisor_feedback,
            PARSE_JSON(@timeline), PARSE_JSON(@keywords), PARSE_JSON(@criteria_justifications), CURRENT_TIMESTAMP()
        )
    """, {
        "call_id":                call_id,
        "score_total":            evaluation["score_total"],
        "criteria":               json.dumps(evaluation["criteria"]),
        "compliance":             evaluation["compliance"],
        "sentiment_client":       evaluation["sentiment_client"],
        "sentiment_agent":        evaluation["sentiment_agent"],
        "summary":                evaluation["summary"],
        "strengths":              evaluation["strengths"],
        "weaknesses":             evaluation["weaknesses"],
        "next_action":            evaluation["next_action"],
        "supervisor_feedback":    evaluation["supervisor_feedback"],
        "timeline":               json.dumps(evaluation["timeline"]),
        "keywords":               json.dumps(evaluation["keywords"]),
        "criteria_justifications":json.dumps(evaluation["criteria_justifications"]),
    })

    execute("""
        UPDATE `dda-dpl-datalab-sdbx-za.SpeakFlow.calls`
        SET status = 'evaluated'
        WHERE id = @call_id
    """, {"call_id": call_id})

    print(f"✅ Evaluated — score={evaluation['score_total']}, compliance={evaluation['compliance']}")

    # ================================================================
    # ALERTS
    # ================================================================
    call_row_agent = fetchone(
        "SELECT agent_id FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` WHERE id = @call_id",
        {"call_id": call_id},
    )
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
    call_row = fetchone(
        "SELECT agent_id FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` WHERE id = @call_id",
        {"call_id": call_id},
    )
    agent_id = (call_row or {}).get("agent_id")
    if not agent_id:
        return

    stats = fetchone("""
        SELECT
            COUNT(*)                     AS total_calls,
            ROUND(AVG(e.score_total), 1) AS avg_score
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e ON e.call_id = c.id
        WHERE c.agent_id = @agent_id
          AND c.called_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
          AND c.status = 'evaluated'
    """, {"agent_id": agent_id})

    if stats:
        execute("""
            UPDATE `dda-dpl-datalab-sdbx-za.SpeakFlow.agents`
            SET avg_score = @avg_score, total_calls = @total_calls
            WHERE id = @agent_id
        """, {
            "avg_score":   stats["avg_score"]   or 0,
            "total_calls": stats["total_calls"]  or 0,
            "agent_id":    agent_id,
        })
        print(f"✅ Stats agent — avg={stats['avg_score']}, calls={stats['total_calls']}")
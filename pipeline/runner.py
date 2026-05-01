from pipeline.transcribe import transcribe_audio, align_transcript
from pipeline.diarize import diarize_audio
import json
from pipeline.transcribe import transcribe_audio, align_transcript, compute_waveform
from pipeline.diarize    import diarize_audio
import json

def run_pipeline(call_id, audio_path, execute, fetchone):

    # ================================================================
    # ÉTAPE 1 : TRANSCRIPTION (WHISPER)
    # ================================================================
    result   = transcribe_audio(audio_path)
    text     = result["text"]
    segments = result.get("segments", [])
    duration = result.get("duration", 300)
    language = result.get("language", "fr")

    # Calculer la waveform miniature (40 valeurs pour le graphique)
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

    print(f"✅ Transcribed — durée={int(duration)}s  waveform={len(waveform)} valeurs")

    # =========================
    # 2. DIARISATION (PYANNOTE)
    # =========================
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
    """, (
        call_id,
        diar["agent_talk_pct"],
        diar["client_talk_pct"],
        diar["silence_pct"],
        diar["silence_max_sec"],
        diar["interruptions_count"],
        json.dumps(diar["silences"]),
        json.dumps(diar["diarization"])
    ))

    print("✅ Diarized")

    # =========================
    # 2.5 ALIGNEMENT
    # =========================
    from pipeline.transcribe import align_transcript, fix_alignment_with_gemini

    segments     = result.get("segments", [])
    aligned_text = align_transcript(segments, diar["diarization"])

    # Correction par Gemini des attributions incorrectes
    aligned_text = fix_alignment_with_gemini(aligned_text)

    execute("""
        UPDATE calls
        SET transcription_text = %s
        WHERE id = %s
    """, (aligned_text, call_id))

    print("✅ Aligned")
    print("--- Aperçu ---")
    print(aligned_text[:500])
    print("--------------")
    # =========================
    # 3. NEXT STEPS (à venir)
    # =========================
    # emotions
    # gemini evaluation
    # alerts

    return aligned_text
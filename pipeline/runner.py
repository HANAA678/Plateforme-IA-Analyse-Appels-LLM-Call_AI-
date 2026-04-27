from pipeline.transcribe import transcribe_audio, align_transcript
from pipeline.diarize import diarize_audio
import json

def run_pipeline(call_id, audio_path, execute, fetchone):

    # =========================
    # 1. TRANSCRIPTION (WHISPER)
    # =========================
    result = transcribe_audio(audio_path)
    text = result["text"]

    # durée réelle si dispo sinon fallback
    duration = result.get("duration", 300)

    execute("""
        UPDATE calls
        SET transcription_text = %s,
            status = %s
        WHERE id = %s
    """, (text, "transcribed", call_id))

    print("✅ Transcribed")

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
    segments = result.get("segments", [])
    aligned_text = align_transcript(segments, diar["diarization"])

    execute("""
        UPDATE calls
        SET transcription_text = %s
        WHERE id = %s
    """, (aligned_text, call_id))

    print("✅ Aligned")
    print("--- Aperçu ---")
    print(aligned_text[:400])
    print("--------------")

    # =========================
    # 3. NEXT STEPS (à venir)
    # =========================
    # emotions
    # gemini evaluation
    # alerts

    return aligned_text
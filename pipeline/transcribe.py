import whisper

# Charger le modèle UNE seule fois (très important)
model = whisper.load_model("base")

def transcribe_audio(file_path: str):
    result = model.transcribe(file_path)

    # durée calculée proprement
    duration = 0
    segments = result.get("segments", [])

    if segments:
        duration = segments[-1]["end"]

    return {
        "text": result["text"].strip(),
        "language": result.get("language", "unknown"),
        "duration": round(duration, 2),
        "segments": segments
    }
def align_transcript(whisper_segments: list, diarization: list) -> str:
    """
    Fusionne les segments Whisper avec les speakers pyannote.
    Retourne un texte formaté :
    Agent: Bonjour madame...
    Client: Oui bonjour...
    """
    if not diarization:
        return " ".join(s["text"] for s in whisper_segments)

    lines = []
    current_speaker = None
    current_text    = []

    for seg in whisper_segments:
        seg_mid = (seg["start"] + seg["end"]) / 2

        # Trouver le locuteur pyannote au milieu du segment Whisper
        speaker = _find_speaker_at(seg_mid, diarization)

        if speaker != current_speaker:
            # Sauvegarder le bloc précédent
            if current_text:
                label = "Agent" if current_speaker == "agent" else "Client"
                lines.append(f"{label}: {' '.join(current_text).strip()}")
            current_speaker = speaker
            current_text    = [seg["text"].strip()]
        else:
            current_text.append(seg["text"].strip())

    # Dernier bloc
    if current_text:
        label = "Agent" if current_speaker == "agent" else "Client"
        lines.append(f"{label}: {' '.join(current_text).strip()}")

    return "\n".join(lines)


def _find_speaker_at(time_sec: float, diarization: list) -> str:
    """Retourne le speaker pyannote à un instant donné."""
    for seg in diarization:
        if seg["start_sec"] <= time_sec <= seg["end_sec"]:
            spk = seg.get("speaker", "")
            return "agent" if ("00" in spk or spk.endswith("_0")) else "client"
    return "client"  # défaut
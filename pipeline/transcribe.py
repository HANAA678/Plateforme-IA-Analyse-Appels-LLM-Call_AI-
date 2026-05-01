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
    Fusionne Whisper + diarization avec mapping correct agent/client
    """

    if not diarization:
        return " ".join(s["text"] for s in whisper_segments)

    agent_speaker = detect_agent_speaker(diarization)

    lines = []
    current_speaker = None
    current_text = []

    for seg in whisper_segments:
        seg_mid = (seg["start"] + seg["end"]) / 2

        raw_speaker = _find_raw_speaker_at(seg_mid, diarization)

        # mapping CORRECT
        speaker = "agent" if raw_speaker == agent_speaker else "client"

        if speaker != current_speaker:
            if current_text:
                label = "Agent" if current_speaker == "agent" else "Client"
                lines.append(f"{label}: {' '.join(current_text).strip()}")

            current_speaker = speaker
            current_text = [seg["text"].strip()]
        else:
            current_text.append(seg["text"].strip())

    # dernier bloc
    if current_text:
        label = "Agent" if current_speaker == "agent" else "Client"
        lines.append(f"{label}: {' '.join(current_text).strip()}")

    return "\n".join(lines)
def detect_agent_speaker(diarization):
    if not diarization:
        return None
    return diarization[0]["speaker"]   # premier qui parle = agent
def _find_raw_speaker_at(time_sec, diarization):
    for seg in diarization:
        if seg["start_sec"] <= time_sec <= seg["end_sec"]:
            return seg["speaker"]
    return None
import numpy as np
import librosa

def compute_waveform(audio_path: str, n: int = 40) -> list:
    """
    Calcule 40 valeurs d'amplitude RMS pour dessiner
    la mini-waveform dans la liste des appels.
    Retourne une liste d'entiers entre 2 et 40.
    """
    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        frame  = max(1, len(y) // n)
        result = []

        for i in range(n):
            chunk = y[i * frame : min((i + 1) * frame, len(y))]
            if len(chunk) == 0:
                result.append(2)
            else:
                rms   = float(np.sqrt(np.mean(chunk ** 2)))
                value = int(rms * 400)
                result.append(max(2, min(40, value)))

        return result

    except Exception as e:
        print(f"[waveform] erreur : {e}")
        return [5] * n   # valeurs par défaut si erreur
def fix_alignment_with_gemini(aligned_text: str) -> str:
    """
    Corrige les attributions Agent/Client incorrectes via Gemini.
    """
    import google.generativeai as genai
    import os

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[fix_alignment] Pas de clé Gemini, on garde l'alignement brut")
        return aligned_text

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f"""Tu reçois la transcription d'un appel de centre d'appel.
Les rôles Agent/Client sont parfois mal attribués à cause d'erreurs de diarisation automatique.

Règles pour identifier l'Agent :
- L'agent présente l'entreprise et se présente au début ("Thank you for calling...", "Bonjour...")
- L'agent pose des questions professionnelles (numéro de compte, vérification identité...)
- L'agent utilise un langage formel et des formules de service
- L'agent ne raconte pas de problèmes personnels

Règles pour identifier le Client :
- Le client explique son problème
- Le client donne ses informations personnelles (nom, numéro de compte...)
- Le client peut être frustré ou raconter des anecdotes personnelles

Corrige UNIQUEMENT les attributions Agent:/Client: incorrectes.
Ne change PAS le texte des phrases.
Garde exactement le même format ligne par ligne : "Agent: ..." ou "Client: ..."
Si une ligne contient les paroles des deux locuteurs, sépare-les en deux lignes.

Transcription à corriger :
{aligned_text}

Retourne UNIQUEMENT la transcription corrigée, sans explication, sans markdown."""

    try:
        response   = model.generate_content(prompt)
        corrected  = response.text.strip()

        lines       = corrected.split("\n")
        valid_lines = [l.strip() for l in lines
                       if l.strip().startswith("Agent:") or l.strip().startswith("Client:")]

        if len(valid_lines) < 3:
            print("[fix_alignment] Résultat invalide, garde l'alignement brut")
            return aligned_text

        print(f"[fix_alignment] ✅ Gemini a corrigé {len(valid_lines)} lignes")
        return "\n".join(valid_lines)

    except Exception as e:
        print(f"[fix_alignment] Erreur Gemini : {e} — garde l'alignement brut")
        return aligned_text
from faster_whisper import WhisperModel
import numpy as np
import librosa
import re
import os
import json
import re
import requests
# ================================================================
# Charger le modèle UNE seule fois
# ================================================================
model = WhisperModel("base", device="cpu", compute_type="int8")


def transcribe_audio(file_path: str):
    segments_gen, info = model.transcribe(file_path, beam_size=5)

    segments = []
    for seg in segments_gen:
        segments.append({
            "start": seg.start,
            "end":   seg.end,
            "text":  seg.text
        })

    duration = segments[-1]["end"] if segments else 0
    text     = " ".join(s["text"].strip() for s in segments)

    return {
        "text":     text.strip(),
        "language": info.language,
        "duration": round(duration, 2),
        "segments": segments
    }



# ================================================================
# Alignement Speaker → Agent/Client via Gemini
# ================================================================

def align_with_gemini(diarization_segments: list, whisper_segments: list) -> str:
    """
    Prend les segments pyannote (SPEAKER_00, SPEAKER_01, etc.) + les segments
    Whisper, les fusionne en un texte brut "SPEAKER_XX: texte", puis demande
    à Gemini qui est l'agent et qui est le client.

    diarization_segments : liste de dicts {start_sec, end_sec, speaker}
    whisper_segments     : liste de dicts {start, end, text}

    Retourne une chaîne multilignes "Agent: ..." / "Client: ..."
    """
    # ── 1. Construire le texte brut avec les labels SPEAKER_XX ────────
    raw_lines = _build_raw_transcript(whisper_segments, diarization_segments)
    if not raw_lines:
        return " ".join(s["text"].strip() for s in whisper_segments)

    raw_text = "\n".join(raw_lines)
    print(f"[gemini_align] Transcription brute ({len(raw_lines)} lignes) envoyée à Gemini")

    # ── 2. Appel Gemini ───────────────────────────────────────────────
    result = _call_gemini(raw_text)
    if not result:
        print("[gemini_align] ❌ Gemini a échoué — retour du texte brut")
        return raw_text

    return result

#la fct qui fait fusion pour avoir cette forme là :     ## speaker : text ##
def _build_raw_transcript(whisper_segments: list, diarization: list) -> list:
    """
    Fusionne Whisper + pyannote et retourne des lignes "SPEAKER_XX: texte".
    Les segments Whisper qui chevauchent plusieurs speakers sont découpés.
    """
    #cela est executé seulement si le résultat de pyannote est vide cad que pyannote n'arrive pas a détecter aucun speaker par ex audio très court 
    if not diarization:   # diarization est une liste pour chaque élément sous la forme {start ,end,speaker}
        return [f"SPEAKER_00: {s['text'].strip()}" for s in whisper_segments]# on boucle sur tout les segment Whisper:on prend le texte et on ajoute SPEAKER_00: devant

    lines = [] #C’est la liste finale que la fonction va retourner comme ca ["SPEAKER_00: bonjour","SPEAKER_01: oui bonjour",...] 
    current_speaker = None
    current_parts   = []
#seg est un  dictionnaire contient start end et text donc seg["text"] c'est le texte 
    for seg in whisper_segments:
        text     = seg["text"].strip() # supprime les espaces inutiles par ex les espaces au debut et a la fin strip ne supprime pas les espaces au milieu pour avoir la transcription nettoyé sans avoir des espaces bizarres ou des enlève \n et \t ds transcriprion 
        speakers = _find_speakers_in_range(seg["start"], seg["end"], diarization)
          
        if len(speakers) <= 1: #si aucun speaker ou un seul 
            #spk recoit le speaker retourné par la fct _find_speakers_in_range speakers ou bien si aucun speaker alors SPEAKER_00
            spk = speakers[0] if speakers else "SPEAKER_00"
            if spk == current_speaker:
                current_parts.append(text)
            else:
                if current_parts and current_speaker:
                    lines.append(f"{current_speaker}: {' '.join(current_parts)}")
                current_speaker = spk
                current_parts   = [text]
        else:
            if current_parts and current_speaker:
                lines.append(f"{current_speaker}: {' '.join(current_parts)}")
                current_parts   = []
                current_speaker = None

            sub = _split_text_by_speakers_raw(text, speakers)
            for spk, chunk in sub:
                if chunk:
                    lines.append(f"{spk}: {chunk}")

    if current_parts and current_speaker:
        lines.append(f"{current_speaker}: {' '.join(current_parts)}")

    return lines
# cette fonction fait l’alignement Whisper ↔ speakers pyannote c'est comme s'il fait le regroupement de speaker à segment associé
# retourne liste de speakers ds un segment whisper 
def _find_speakers_in_range(start: float, end: float, diarization: list) -> list:
    found = [] #va contenir speakers trouvés 
    for seg in diarization:
        #c'est comme si on vérifie si un segment whisper contient un seul speaker ou deux c'est comme si on vérifie est ce que les segment de diarization sont inclues au meme segmebnt whisper 
        overlap_start = max(start, seg["start_sec"]) 
        overlap_end   = min(end,   seg["end_sec"])   
        if overlap_end > overlap_start: #si chevauchement 
            spk = seg.get("speaker", "SPEAKER_00")#recupérer le speaker si il existe sinon speaker00
            if not found or found[-1] != spk:
                found.append(spk) #ajouter ce speaker ds la liste 
    return found if found else ["SPEAKER_00"]

#exemple: 
 # chevauchemnt 0_____7 un seul segment whiper        0____3 4______7  2 speakers       segment de diarization {start end speaker}
 # chevauchemnt 0_____5 un seul segment whiper         0____5          1 seul speaker   segment de diarization


def _split_text_by_speakers_raw(text: str, speakers: list) -> list:
    sentences = re.split(r'(?<=[.?!])\s+', text.strip())
    sentences = [s for s in sentences if s]
    if len(sentences) < 2:
        return [(speakers[0], text)]
    result  = []
    per_spk = max(1, len(sentences) // len(speakers))
    for i, spk in enumerate(speakers):
        if i < len(speakers) - 1:
            chunk = " ".join(sentences[i * per_spk:(i + 1) * per_spk])
        else:
            chunk = " ".join(sentences[i * per_spk:])
        if chunk:
            result.append((spk, chunk))
    return result if result else [(speakers[0], text)]






  # ================================================================
# Appel Gemini
# ================================================================

def _call_gemini(raw_transcript: str) -> str:
    """
    Envoie la transcription brute (SPEAKER_XX) à Gemini et récupère
    la version corrigée avec les labels Agent/Client.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[gemini_align] Pas de clé GEMINI_API_KEY — alignement ignoré")
        return ""

    prompt = _build_prompt(raw_transcript)

    # Gemini 2.0 Flash (modèle rapide, gratuit, adapté à cette tâche)
    model   = "gemini-2.0-flash"
    url     = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature":   0.0,
            "maxOutputTokens": 4096,
        }
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=90)
            data = resp.json()

            if "error" in data:
                print(f"[gemini_align] Erreur API (tentative {attempt}): {data['error'].get('message')}")
                continue

            text = (
                data
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )

            if not text:
                print(f"[gemini_align] Réponse vide (tentative {attempt})")
                continue

            # Valider et nettoyer la réponse
            validated = _validate_response(text, raw_transcript)
            if validated:
                print(f"[gemini_align] ✅ Succès ({len(validated.splitlines())} lignes)")
                return validated

        except Exception as e:
            print(f"[gemini_align] Exception (tentative {attempt}): {e}")

    return ""


def _build_prompt(raw_transcript: str) -> str:
    return f"""
Tu es un système STRICT d'analyse de conversations téléphoniques.

Tu reçois une transcription avec des labels SPEAKER_XX.

🎯 OBJECTIF :
1. Identifier quel speaker est l'Agent et lequel est le Client (globalement)
2. Remplacer SPEAKER_XX par "Agent:" ou "Client:" dans TOUT le texte

---

🚨 IMPORTANT (CRITIQUE) :

Tu dois d'abord déterminer :
- SPEAKER_00 = Agent ou Client ?
- SPEAKER_01 = Agent ou Client ?

Ensuite appliquer ce mapping à TOUTES les lignes.

❌ Tu ne dois PAS classifier ligne par ligne indépendamment
❌ Tu dois garder une cohérence globale

---

🧠 INDICES :

AGENT :
- ouvre l'appel
- parle au nom d’une entreprise
- pose des questions structurées
- guide la conversation
- ton professionnel

CLIENT :
- répond
- donne ses infos personnelles
- phrases courtes
- parfois confus ou émotionnel

---

📏 CONTRAINTES STRICTES :

- Ne modifie JAMAIS le texte
- Ne corrige PAS
- Ne reformule PAS
- Même nombre de lignes EXACT
- Même ordre EXACT

---

📤 FORMAT :

Agent: texte exact
Client: texte exact

Aucune explication.

---

TRANSCRIPTION :

{raw_transcript}
"""
def _validate_response(text: str, original: str) -> str:
    """
    Vérifie que la réponse de Gemini est valide :
    - contient uniquement des lignes Agent: / Client:
    - nombre de lignes cohérent avec l'original
    """
    cleaned = text.replace("```", "").strip()
    valid_lines = [
        l.strip() for l in cleaned.splitlines()
        if l.strip().startswith("Agent:") or l.strip().startswith("Client:")
    ]

    original_lines = [
        l for l in original.splitlines()
        if l.strip()
    ]
    min_expected = max(2, int(len(original_lines) * 0.5))

    if len(valid_lines) < min_expected:
        print(f"[gemini_align] ⚠️ Réponse trop courte : {len(valid_lines)}/{len(original_lines)} lignes")
        return ""

    return "\n".join(valid_lines)


# ================================================================
# Waveform (inchangée)
# ================================================================
def compute_waveform(audio_path: str, n: int = 40) -> list:
    import numpy as np
    import librosa
    try:
        y, sr  = librosa.load(audio_path, sr=None, mono=True)
        frame  = max(1, len(y) // n)
        result = []
        for i in range(n):
            chunk = y[i * frame: min((i + 1) * frame, len(y))]
            if len(chunk) == 0:
                result.append(2)
            else:
                rms   = float(np.sqrt(np.mean(chunk ** 2)))
                value = int(rms * 400)
                result.append(max(2, min(40, value)))
        return result
    except Exception as e:
        print(f"[waveform] erreur : {e}")
        return [5] * n

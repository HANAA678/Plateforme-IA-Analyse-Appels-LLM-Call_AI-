from faster_whisper import WhisperModel
import numpy as np
import librosa
import re

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
# Détection inversion globale des speakers
# ================================================================

# Mots typiques d'un agent qui ouvre l'appel
_AGENT_OPENERS = [
    "thank you for calling", "merci d'appeler", "bonjour.*comment puis",
    "my name is", "je m'appelle", "je vous appelle", "je vous contacte",
    "comment puis-je", "how can i assist", "how may i help",
    "je me permets de vous", "j'ai l'honneur", "société", "assurance",
    "service client", "customer service",
]

# Mots typiques d'un client qui répond au téléphone (première réplique)
_CLIENT_OPENERS = [
    r"^oui[\.\,\?]?$", r"^allo[\.\,\?]?$", r"^allô[\.\,\?]?$",
    r"^yes[\.\,\?]?$", r"^hello[\.\,\?]?$", r"^bonjour[\.\,\?]?$",
    r"^ouais[\.\,\?]?$", r"^à l'eau[\.\,\?]?$", r"^speaking[\.\,\?]?$",
]


def _is_agent_text(text: str) -> bool:
    t = text.lower().strip()
    return any(re.search(p, t) for p in _AGENT_OPENERS)


def _is_client_opener(text: str) -> bool:
    t = text.lower().strip()
    # Très court ET ressemble à une réponse de décroché
    return len(t.split()) <= 4 and any(re.match(p, t) for p in _CLIENT_OPENERS)


def _should_flip_speakers(aligned_text: str) -> bool:
    """
    Détecte si pyannote a inversé Agent/Client globalement.
    Retourne True si on doit flipper tous les labels.

    Cas 1 : La première ligne est "Agent: Oui" / "Agent: Allo" (= client qui décroche)
    Cas 2 : La première ligne Agent est très courte ET la 2ème ligne Client contient
            des formules d'agent (nom de l'entreprise, "comment puis-je", etc.)
    Cas 3 : Score — si les lignes Agent contiennent plus de mots-client
            que les lignes Client, c'est inversé.
    """
    lines = [
        l.strip() for l in aligned_text.split("\n")
        if l.strip().startswith("Agent:") or l.strip().startswith("Client:")
    ]
    if not lines:
        return False

    # ── Cas 1 : première ligne Agent = décroché typique client ─────────
    first = lines[0]
    if first.startswith("Agent:"):
        first_text = first[len("Agent:"):].strip()
        if _is_client_opener(first_text):
            print("[flip_check] 🔄 Cas 1 : première ligne Agent = décroché client → flip")
            return True

    # ── Cas 2 : la 2ème ligne Client contient des formules d'agent ─────
    if len(lines) >= 2:
        second = lines[1]
        if second.startswith("Client:"):
            second_text = second[len("Client:"):].strip()
            if _is_agent_text(second_text):
                print("[flip_check] 🔄 Cas 2 : 2ème ligne Client = formule agent → flip")
                return True

    # ── Cas 3 : score global ────────────────────────────────────────────
    agent_texts  = " ".join(l[len("Agent:"):].strip()  for l in lines if l.startswith("Agent:"))
    client_texts = " ".join(l[len("Client:"):].strip() for l in lines if l.startswith("Client:"))

    agent_score  = sum(1 for p in _AGENT_OPENERS if re.search(p, agent_texts.lower()))
    client_score = sum(1 for p in _AGENT_OPENERS if re.search(p, client_texts.lower()))

    if client_score > agent_score:
        print(f"[flip_check] 🔄 Cas 3 : score agent dans Client ({client_score}) > Agent ({agent_score}) → flip")
        return True

    print(f"[flip_check] ✅ Pas d'inversion détectée (agent_score={agent_score}, client_score={client_score})")
    return False


def _flip_labels(aligned_text: str) -> str:
    """Inverse tous les labels Agent ↔ Client."""
    result = []
    for line in aligned_text.split("\n"):
        if line.startswith("Agent:"):
            result.append("Client:" + line[len("Agent:"):])
        elif line.startswith("Client:"):
            result.append("Agent:" + line[len("Client:"):])
        else:
            result.append(line)
    return "\n".join(result)


# ================================================================
# Alignement Whisper + Pyannote
# ================================================================
def align_transcript(whisper_segments: list, diarization: list) -> str:
    """
    Fusionne les segments Whisper avec les speakers pyannote.
    Découpe les segments Whisper qui chevauchent 2+ locuteurs.
    """
    if not diarization:
        return " ".join(s["text"] for s in whisper_segments)

    lines           = []
    current_speaker = None
    current_text    = []

    for seg in whisper_segments:
        text = seg["text"].strip()
        speakers_in_seg = _find_speakers_in_range(seg["start"], seg["end"], diarization)

        if len(speakers_in_seg) <= 1:
            speaker = speakers_in_seg[0] if speakers_in_seg else "client"

            if speaker != current_speaker:
                if current_text:
                    label = "Agent" if current_speaker == "agent" else "Client"
                    lines.append(f"{label}: {' '.join(current_text).strip()}")
                current_speaker = speaker
                current_text    = [text]
            else:
                current_text.append(text)

        else:
            if current_text:
                label = "Agent" if current_speaker == "agent" else "Client"
                lines.append(f"{label}: {' '.join(current_text).strip()}")
                current_text    = []
                current_speaker = None

            sub_lines = _split_text_by_speakers(text, speakers_in_seg)
            for spk, chunk in sub_lines:
                if chunk:
                    label = "Agent" if spk == "agent" else "Client"
                    lines.append(f"{label}: {chunk}")

    if current_text:
        label = "Agent" if current_speaker == "agent" else "Client"
        lines.append(f"{label}: {' '.join(current_text).strip()}")

    raw = "\n".join(lines)

    # ── Détection et correction d'inversion globale ────────────────────
    if _should_flip_speakers(raw):
        raw = _flip_labels(raw)

    return raw


def _find_speaker_at(time_sec: float, diarization: list) -> str:
    for seg in diarization:
        if seg["start_sec"] <= time_sec <= seg["end_sec"]:
            spk = seg.get("speaker", "")
            return "agent" if ("00" in spk or spk.endswith("_0")) else "client"
    return "client"


def _find_speakers_in_range(start: float, end: float, diarization: list) -> list:
    found = []
    for seg in diarization:
        overlap_start = max(start, seg["start_sec"])
        overlap_end   = min(end,   seg["end_sec"])
        if overlap_end > overlap_start:
            spk  = seg.get("speaker", "")
            role = "agent" if ("00" in spk or spk.endswith("_0")) else "client"
            if not found or found[-1] != role:
                found.append(role)
    return found if found else ["client"]


def _split_text_by_speakers(text: str, speakers: list) -> list:
    if len(speakers) == 1:
        return [(speakers[0], text)]

    sentences = re.split(r'(?<=[.?!])\s+', text.strip())
    sentences = [s for s in sentences if s]

    if len(sentences) < 2:
        return [(speakers[0], text)]

    result  = []
    per_spk = max(1, len(sentences) // len(speakers))

    for i, spk in enumerate(speakers):
        if i < len(speakers) - 1:
            chunk = " ".join(sentences[i * per_spk : (i + 1) * per_spk])
        else:
            chunk = " ".join(sentences[i * per_spk :])
        if chunk:
            result.append((spk, chunk))

    return result if result else [(speakers[0], text)]


# ================================================================
# Waveform
# ================================================================
def compute_waveform(audio_path: str, n: int = 40) -> list:
    try:
        y, sr  = librosa.load(audio_path, sr=None, mono=True)
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
        return [5] * n


# ================================================================
# Extraction robuste du texte depuis la réponse OpenRouter
# ================================================================
def _extract_content(data: dict) -> str:
    if "choices" not in data or not data["choices"]:
        return ""

    message = data["choices"][0].get("message", {}) or {}

    content = message.get("content")
    if content and isinstance(content, str) and content.strip():
        return content.strip()

    reasoning = message.get("reasoning_content")
    if reasoning and isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()

    if isinstance(content, list):
        texts  = [b.get("text", "") for b in content if isinstance(b, dict)]
        joined = " ".join(t for t in texts if t).strip()
        if joined:
            return joined

    return ""


# ================================================================
# Appel OpenRouter avec retry
# ================================================================
def _call_openrouter(model_id: str, messages: list, api_key: str,
                     max_retries: int = 3) -> str:
    import requests

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model_id,
                    "messages":    messages,
                    "temperature": 0.0,
                    "max_tokens":  3000,
                },
                timeout=90
            )

            data = response.json()

            if "error" in data:
                code = data["error"].get("code", "?")
                msg  = data["error"].get("message", "")
                print(f"[fix_alignment] {model_id} → erreur {code}: {msg}")
                return ""

            text = _extract_content(data)

            if not text:
                print(f"[fix_alignment] {model_id} → contenu vide (tentative {attempt}/{max_retries})")
                continue

            return text

        except Exception as e:
            print(f"[fix_alignment] {model_id} → exception (tentative {attempt}): {e}")
            continue

    return ""


# ================================================================
# Correction alignement via OpenRouter
# ================================================================
def fix_alignment_with_openrouter(aligned_text: str) -> str:
    """
    Passe de polish finale : corrige les labels résiduels et les lignes mixtes.
    À ce stade, l'inversion globale a déjà été corrigée en Python.
    Le LLM n'a plus qu'à gérer les cas locaux.
    """
    import os
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("[fix_alignment] Pas de clé OpenRouter — alignement brut conservé")
        return aligned_text

    system_prompt = """Tu es un expert en analyse de transcriptions de centres d'appels.
Ta mission : corriger les labels Agent/Client ET découper les lignes qui mélangent plusieurs locuteurs.

RÈGLES ABSOLUES :
1. Ne modifie JAMAIS le texte des phrases — uniquement les labels
2. Chaque ligne DOIT commencer par "Agent:" ou "Client:" — rien d'autre
3. Pas d'introduction, pas d'explication, pas de markdown, pas de commentaires
4. Tu PEUX et DOIS découper une ligne en plusieurs si elle contient les deux locuteurs
5. Retourne UNIQUEMENT les lignes corrigées, dans le même ordre logique"""

    user_prompt = f"""## CONTEXTE
Appel téléphonique entre un agent de call center et un client.
Note : l'inversion globale Agent/Client a déjà été corrigée automatiquement.
Il reste à corriger les erreurs locales (quelques lignes mal attribuées).

---

## IDENTIFIER L'AGENT (employé de l'entreprise)
- Ouvre l'appel : "Bonjour [Entreprise], je suis [Prénom]..." ou appelle le client
- Pose des questions pro : identité, numéro de compte, adresse, disponibilité
- Propose des solutions, crée des dossiers, fixe des rappels
- Conclut l'appel avec des formules de politesse professionnelles
- Ton : formel, calme, même face à un client frustré
- NE donne JAMAIS ses informations personnelles (mutuelle, adresse, compte)

## IDENTIFIER LE CLIENT (personne qui appelle ou est appelée)
- Répond au téléphone : "Oui", "Allo", court décroché
- Explique son problème ou répond aux questions
- DONNE ses infos : nom, numéro de compte, adresse, email, mutuelle, prix payé
- Peut être frustré, confus, faire des digressions (blagues, anecdotes)
- Ses réponses sont souvent COURTES ("Oui", "Non", "D'accord", "Vers 14h")

---

## RÈGLE CLÉS POUR LES RÉPONSES COURTES
- "Oui", "Non", "D'accord", "Ouais" isolés après une question de l'agent → CLIENT
- "Ma mutuelle c'est...", "Mon numéro c'est...", "C'est en..." → CLIENT qui donne ses infos
- "Ben c'est..." suivi d'un montant ou d'une info personnelle → CLIENT
- "Merci" en fin d'appel peut être les deux → garder le contexte

---

## HEURISTIQUES
1. Le premier locuteur est presque toujours l'Agent (sauf si c'est "Oui" / "Allo" = client qui décroche)
2. Alternance Agent→Client→Agent est la norme
3. Lignes très courtes ("Oui", "Non", "103") après une question longue → CLIENT
4. Lignes longues avec explication professionnelle → AGENT
5. Deux lignes consécutives même label avec contenus opposés → l'une est mal labelisée

---

## ⚠️ LIGNES MIXTES — DÉCOUPE OBLIGATOIRE

ENTRÉE:
Agent: Vers 14h ça vous convient ? D'accord. Super, je vous rappelle.

SORTIE:
Agent: Vers 14h ça vous convient ?
Client: D'accord.
Agent: Super, je vous rappelle.

---

## EXEMPLES

### Exemple 1 — Client confus attribué à l'agent :
ENTRÉE:
Agent: Ah, let me see now. Where did I put that? My account number is, um, wait, that's not it.
Client: That's okay, sir. Take your time.

SORTIE:
Client: Ah, let me see now. Where did I put that? My account number is, um, wait, that's not it.
Agent: That's okay, sir. Take your time.

### Exemple 2 — Client donne sa mutuelle :
ENTRÉE:
Agent: Et dites-moi le nom de votre mutuelle ?
Agent: Ma mutuelle, c'est la mutuelle générale.
Agent: D'accord, et combien vous payez ?
Agent: Ben, c'est 103 euros.

SORTIE:
Agent: Et dites-moi le nom de votre mutuelle ?
Client: Ma mutuelle, c'est la mutuelle générale.
Agent: D'accord, et combien vous payez ?
Client: Ben, c'est 103 euros.

### Exemple 3 — Réponses courtes client :
ENTRÉE:
Agent: Est-ce que vous êtes au courant de cette réforme ?
Agent: Non.
Agent: D'accord, c'est une nouvelle réforme qui permet...
Agent: D'accord.

SORTIE:
Agent: Est-ce que vous êtes au courant de cette réforme ?
Client: Non.
Agent: D'accord, c'est une nouvelle réforme qui permet...
Client: D'accord.

### Exemple 4 — Fin d'appel mixte :
ENTRÉE:
Agent: Très bien. Alors vers 14 heures je vous rappelle. D'accord ? D'accord. Super. Merci.

SORTIE:
Agent: Très bien. Alors vers 14 heures je vous rappelle. D'accord ?
Client: D'accord.
Agent: Super. Merci.

---

## TRANSCRIPTION À CORRIGER

{aligned_text}

---

Retourne UNIQUEMENT les lignes "Agent: ..." ou "Client: ...". Zéro texte avant ou après."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    original_lines = [
        l for l in aligned_text.split("\n")
        if l.strip().startswith("Agent:") or l.strip().startswith("Client:")
    ]
    min_expected = max(3, int(len(original_lines) * 0.5))

    def parse_and_validate(raw_text: str, model_id: str):
        cleaned = raw_text.replace("```", "").strip()
        valid_lines = [
            l.strip() for l in cleaned.split("\n")
            if l.strip().startswith("Agent:") or l.strip().startswith("Client:")
        ]
        if len(valid_lines) < min_expected:
            print(f"[fix_alignment] {model_id} → trop court ({len(valid_lines)}/{len(original_lines)})")
            return None
        print(f"[fix_alignment] ✅ {model_id} → {len(valid_lines)} lignes (était {len(original_lines)})")
        return "\n".join(valid_lines)

    # ── openrouter/free EN PREMIER ─────────────────────────────────────
    print("[fix_alignment] Tentative avec openrouter/free (retry=3)...")
    raw = _call_openrouter("openrouter/free", messages, api_key, max_retries=3)
    if raw:
        result = parse_and_validate(raw, "openrouter/free")
        if result:
            return result

    # ── Fallbacks ──────────────────────────────────────────────────────
    FALLBACK_MODELS = [
        {"id": "meta-llama/llama-3.3-70b-instruct:free",      "supports_system": True},
        {"id": "nvidia/llama-3.1-nemotron-70b-instruct:free",  "supports_system": True},
        {"id": "google/gemma-3-27b-it:free",                   "supports_system": False},
        {"id": "google/gemma-3-12b-it:free",                   "supports_system": False},
    ]

    for model_cfg in FALLBACK_MODELS:
        model_id        = model_cfg["id"]
        supports_system = model_cfg["supports_system"]

        print(f"[fix_alignment] Fallback → {model_id}...")

        if supports_system:
            msgs = messages
        else:
            merged = f"{system_prompt}\n\n---\n\n{user_prompt}"
            msgs   = [{"role": "user", "content": merged}]

        raw = _call_openrouter(model_id, msgs, api_key, max_retries=1)
        if raw:
            result = parse_and_validate(raw, model_id)
            if result:
                return result

    print("[fix_alignment] ❌ Tous les modèles ont échoué — alignement brut conservé")
    return aligned_text

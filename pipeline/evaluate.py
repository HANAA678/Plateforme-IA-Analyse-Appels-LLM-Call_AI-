import os
import json
import re
import requests
from dotenv import load_dotenv
load_dotenv()
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

def evaluate_transcription(
    transcription: str,
    criteria_config: list,
    supervisor_notes: str = "",
    focus_points: str = "",
    thresholds: dict = None,
) -> dict:
    if thresholds is None:
        thresholds = {"compliance": 70, "alert": 40}

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY manquant dans les variables d'environnement")

    prompt = _build_prompt(
        transcription, criteria_config, supervisor_notes, focus_points, thresholds
    )

    result = _call_gemini(api_key, prompt)
    if result is None:
        raise RuntimeError("Gemini n'a pas retourné de réponse valide après 3 tentatives")

    _validate_and_fix(result, criteria_config, thresholds)
    return result


def _build_prompt(transcription, criteria_config, supervisor_notes, focus_points, thresholds):

    total_max = sum(c["max_pts"] for c in criteria_config if c.get("is_active", True))

    criteria_lines = "\n".join(
        f'  - clé="{c["key"]}" | label="{c["label"]}" | max={c["max_pts"]} pts | {c["description"]}'
        for c in criteria_config if c.get("is_active", True)
    )

    criteria_json_example = json.dumps(
        {c["key"]: f"0 à {c['max_pts']}" for c in criteria_config if c.get("is_active", True)},
        ensure_ascii=False
    )

    justif_json_example = json.dumps(
        {c["key"]: "explication..." for c in criteria_config if c.get("is_active", True)},
        ensure_ascii=False
    )

    context_section = ""
    if supervisor_notes:
        context_section += f"\nCONTEXTE SUPERVISEUR : {supervisor_notes}"
    if focus_points:
        context_section += f"\nPOINTS À VÉRIFIER : {focus_points}"

    return f"""Tu es un évaluateur qualité expert pour centre d'appel.
{context_section}

═══════════════════════════════════════
LECTURE OBLIGATOIRE DE LA TRANSCRIPTION
═══════════════════════════════════════
- Tu DOIS analyser toute la transcription du début à la fin
- Tu NE DOIS PAS te baser uniquement sur le début
- Tu DOIS prendre en compte le début, le milieu ET la fin
- Il est INTERDIT d’ignorer une partie de la conversation
- Si un élément apparaît à la fin → il DOIT être pris en compte

═══════════════════════════════════════
CRITÈRES D'ÉVALUATION (total {total_max} pts)
═══════════════════════════════════════
{criteria_lines}

RÈGLES DE CONFORMITÉ :
- score >= {thresholds['compliance']} → compliance = "conforme"
- {thresholds['alert']} <= score < {thresholds['compliance']} → compliance = "partiel"
- score < {thresholds['alert']} → compliance = "non-conforme"

═══════════════════════════════════════
RÈGLES DE NOTATION — STRICTES
═══════════════════════════════════════
1. Si un critère N'EST PAS OBSERVABLE :
   → score = 0
   → justification obligatoire

2. Chaque score DOIT être basé sur un exemple concret extrait de la transcription
   (début, milieu ou fin).

3. Si aucun exemple précis n’existe → score faible ou 0

4. Cohérence obligatoire :
   si justification contient "non observable", "non abordé", etc.
   → score = 0 OBLIGATOIRE

5. Tu DOIS analyser toute la conversation avant de répondre

6. Le score_total doit être EXACTEMENT la somme des critères

═══════════════════════════════════════
FORMAT DE RÉPONSE — JSON STRICT
═══════════════════════════════════════

{{
  "score_total": <somme exacte>,
  "criteria": {criteria_json_example},
  "compliance": "conforme|partiel|non-conforme",
  "sentiment_client": "positif|neutre|negatif",
  "sentiment_agent": "professionnel|neutre|non-professionnel",
  "summary": "<2 phrases>",
  "strengths": "<1 phrase>",
  "weaknesses": "<1 phrase>",
  "next_action": "<action>",
  "supervisor_feedback": "<réponse aux focus_points>",
  "timeline": [
    {{"time_sec": 0, "time_label": "0:00", "event": "...", "type": "ok|warning|issue"}}
  ],
  "keywords": ["mot1", "mot2"],
  "criteria_justifications": {justif_json_example}
}}

Retourne UNIQUEMENT ce JSON.

═══════════════════════════════════════
TRANSCRIPTION COMPLÈTE (À ANALYSER ENTIEREMENT)
═══════════════════════════════════════
{transcription}
"""


def _call_gemini(api_key: str, prompt: str) -> dict | None:
    url = f"{GEMINI_URL}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.0,
            "maxOutputTokens": 4096,
        },
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=90)
            data = resp.json()

            if "error" in data:
                print(f"[evaluate] ❌ Erreur API (tentative {attempt}) : {data['error'].get('message')}")
                continue

            raw_text = (
                data
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )

            if not raw_text:
                print(f"[evaluate] ⚠️ Réponse vide (tentative {attempt})")
                continue

            parsed = _parse_json(raw_text)
            if parsed is not None:
                print(f"[evaluate] ✅ Évaluation reçue (tentative {attempt})")
                return parsed

        except requests.RequestException as e:
            print(f"[evaluate] ❌ Erreur réseau (tentative {attempt}) : {e}")
        except Exception as e:
            print(f"[evaluate] ❌ Exception (tentative {attempt}) : {e}")

    return None


def _parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    print(f"[evaluate] ⚠️ JSON invalide :\n{cleaned[:300]}")
    return None


def _validate_and_fix(result: dict, criteria_config: list, thresholds: dict) -> None:
    """
    Validation + correction en deux passes :
    Passe 1 — nettoyer les clés et borner les valeurs
    Passe 2 — détecter les contradictions score élevé / justification négative et corriger
    """
    total_max = sum(c["max_pts"] for c in criteria_config if c.get("is_active", True))

    # ── Champs simples ────────────────────────────────────────────
    if not isinstance(result.get("criteria"), dict):
        result["criteria"] = {}
    result.setdefault("criteria_justifications", {})
    result.setdefault("timeline", [])
    result.setdefault("keywords", [])
    for field in ("summary", "strengths", "weaknesses", "next_action", "supervisor_feedback"):
        result.setdefault(field, "")

    # ── Passe 1 : clés et bornes ──────────────────────────────────
    known_keys = {c["key"] for c in criteria_config}

    # Supprimer les clés inventées
    for k in list(result["criteria"].keys()):
        if k not in known_keys:
            print(f"[evaluate] ⚠️ Clé inventée supprimée : '{k}'")
            del result["criteria"][k]

    # Ajouter les clés manquantes et borner
    for c in criteria_config:
        key = c["key"]
        if key not in result["criteria"]:
            result["criteria"][key] = 0
            print(f"[evaluate] ⚠️ Clé manquante ajoutée à 0 : '{key}'")
        else:
            result["criteria"][key] = max(0, min(c["max_pts"], int(result["criteria"][key])))

    # ── Passe 2 : cohérence score ↔ justification ─────────────────
    # Mots qui indiquent qu'un critère n'est pas observable
    non_observable_markers = (
        "non observable", "non abordé", "pas abordé", "pas encore",
        "non évalué", "absent", "aucune tentative", "n'est pas encore",
        "ne montre pas", "difficile d'évaluer", "pas de", "aucune résolution",
        "non effectué", "non réalisé",
    )

    for c in criteria_config:
        key     = c["key"]
        score   = result["criteria"].get(key, 0)
        justif  = result["criteria_justifications"].get(key, "").lower()
        max_pts = c["max_pts"]

        # Si la justification dit "non observable" mais le score est > 0
        if any(marker in justif for marker in non_observable_markers) and score > 0:
            print(f"[evaluate] 🔧 Contradiction détectée sur '{key}' : "
                  f"score={score} mais justification=non observable → forcé à 0")
            result["criteria"][key] = 0

    # ── Recalculer score_total après corrections ──────────────────
    recalculated = sum(result["criteria"].values())
    if recalculated != result.get("score_total"):
        print(f"[evaluate] 🔧 score_total corrigé : {result.get('score_total')} → {recalculated}")
        result["score_total"] = recalculated

    # Borner entre 0 et total_max
    result["score_total"] = max(0, min(total_max, result["score_total"]))

    # ── Compliance recalculée sur le vrai score ───────────────────
    score = result["score_total"]
    valid_compliance = {"conforme", "partiel", "non-conforme"}
    if result.get("compliance") not in valid_compliance:
        if score >= thresholds["compliance"]:
            result["compliance"] = "conforme"
        elif score >= thresholds["alert"]:
            result["compliance"] = "partiel"
        else:
            result["compliance"] = "non-conforme"

    # Sentiments
    if result.get("sentiment_client") not in {"positif", "neutre", "negatif"}:
        result["sentiment_client"] = "neutre"
    if result.get("sentiment_agent") not in {"professionnel", "neutre", "non-professionnel"}:
        result["sentiment_agent"] = "neutre"

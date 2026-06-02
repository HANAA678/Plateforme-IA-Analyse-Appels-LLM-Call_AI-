import uuid
import json
import re
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from core.database import fetchone, fetchall, execute

import google.generativeai as genai

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ================================================================
# GET /api/calls/{call_id}/coaching  — lire la fiche d'un appel
# ================================================================

@router.get("/api/calls/{call_id}/coaching")
def get_call_coaching(call_id: str):
    """
    Retourne la fiche coaching générée pour un appel spécifique.
    404 si pas encore générée.
    Utilisé par : page Coaching (depuis liste appels)
    """
    call = fetchone("""
        SELECT c.id, a.full_name, a.initials, a.id AS agent_id
        FROM calls c
        JOIN agents a ON a.id = c.agent_id
        WHERE c.id = %s
    """, (call_id,))

    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable.")

    note = fetchone("""
        SELECT
            weak_points,
            vocal_issues,
            recommended_training,
            performance_summary,
            avg_score_at_generation,
            calls_analyzed,
            generated_at,
            example_call_id
        FROM coaching_notes
        WHERE agent_id = %s
        ORDER BY generated_at DESC
        LIMIT 1
    """, (str(call["agent_id"]),))

    if not note:
        raise HTTPException(status_code=404, detail="Fiche coaching non encore générée pour cet appel.")

    return {
        "call_id":                 str(note["example_call_id"]) if note["example_call_id"] else call_id,
        "agent_name":              call["full_name"],
        "agent_initials":          call["initials"],
        "weak_points":             note["weak_points"],
        "vocal_issues":            note["vocal_issues"],
        "recommended_training":    note["recommended_training"],
        "performance_summary":     note["performance_summary"],
        "avg_score_at_generation": float(note["avg_score_at_generation"]) if note["avg_score_at_generation"] else None,
        "calls_analyzed":          note["calls_analyzed"],
        "generated_at":            note["generated_at"].isoformat() if note["generated_at"] else None,
    }


# ================================================================
# POST /api/calls/{call_id}/coaching/generate  — générer la fiche
# ================================================================

@router.post("/api/calls/{call_id}/coaching/generate")
def generate_call_coaching(call_id: str):
    """
    Génère la fiche coaching à partir d'UN appel spécifique.
    Utilisé par : page Coaching (bouton "Générer")
    """

    # ── 1. Récupérer l'appel + son évaluation + audio ────────────
    call = fetchone("""
        SELECT
            c.id, c.call_type, c.duration_seconds, c.called_at,
            c.focus_points, c.supervisor_notes,
            a.id         AS agent_id,
            a.full_name,
            a.initials,
            e.score_total,
            e.compliance,
            e.summary,
            e.strengths,
            e.weaknesses,
            e.next_action,
            e.supervisor_feedback,
            e.criteria,
            e.timeline,
            e.keywords,
            am.agent_wpm,
            am.client_wpm,
            am.interruptions_count,
            am.silence_max_sec,
            am.silence_pct,
            am.agent_talk_pct,
            am.noise_level,
            am.emotions_agent,
            am.emotions_client
        FROM calls c
        JOIN agents a         ON a.id      = c.agent_id
        LEFT JOIN evaluations e  ON e.call_id = c.id
        LEFT JOIN audio_metrics am ON am.call_id = c.id
        WHERE c.id = %s AND c.status = 'evaluated'
    """, (call_id,))

    if not call:
        raise HTTPException(status_code=404, detail="Appel introuvable ou non encore évalué.")

    # ── 2. Construire le contexte pour Gemini ─────────────────────
    score       = call["score_total"] or 0
    compliance  = call["compliance"]  or "inconnu"
    call_type   = call["call_type"]   or "inconnu"
    weaknesses  = call["weaknesses"]  or "non renseigné"
    strengths   = call["strengths"]   or "non renseigné"
    summary     = call["summary"]     or "non renseigné"
    next_action = call["next_action"] or "aucune"

    # Données audio
    vocal_lines = []
    if call["agent_wpm"]:
        vocal_lines.append(f"Débit agent : {call['agent_wpm']} mots/min")
    if call["client_wpm"]:
        vocal_lines.append(f"Débit client : {call['client_wpm']} mots/min")
    if call["interruptions_count"] is not None:
        vocal_lines.append(f"Interruptions : {call['interruptions_count']}")
    if call["silence_max_sec"] is not None:
        vocal_lines.append(f"Silence max : {call['silence_max_sec']}s")
    if call["agent_talk_pct"]:
        vocal_lines.append(f"Parole agent : {call['agent_talk_pct']}%")
    if call["noise_level"]:
        vocal_lines.append(f"Bruit de fond : {call['noise_level']}")

    vocal_context = " | ".join(vocal_lines) if vocal_lines else "Données vocales non disponibles."

    # Émotions
    emotions_ctx = ""
    if call["emotions_agent"]:
        emotions_ctx += f"Émotions agent : {json.dumps(call['emotions_agent'])}. "
    if call["emotions_client"]:
        emotions_ctx += f"Émotions client : {json.dumps(call['emotions_client'])}."

    # Critères détaillés
    criteria_ctx = ""
    if call["criteria"]:
        criteria_ctx = f"Notes par critère : {json.dumps(call['criteria'])}."

    # Notes superviseur
    supervisor_ctx = ""
    if call["supervisor_notes"]:
        supervisor_ctx += f"Contexte superviseur : {call['supervisor_notes']}. "
    if call["focus_points"]:
        supervisor_ctx += f"Points à vérifier : {call['focus_points']}."

    # ── 3. Prompt Gemini ──────────────────────────────────────────
    prompt = f"""Tu es un coach qualité expert pour centre d'appel.

Agent : {call['full_name']}
Type d'appel : {call_type}
Score obtenu : {score}/100
Conformité   : {compliance}

Résumé de l'appel : {summary}
Points forts      : {strengths}
Points faibles    : {weaknesses}
Action CRM        : {next_action}
{criteria_ctx}

Métriques audio :
{vocal_context}
{emotions_ctx}

{supervisor_ctx}

Sur la base de CET appel uniquement, génère une fiche coaching.
Réponds UNIQUEMENT avec ce JSON (sans markdown, sans texte avant ou après) :
{{
  "weak_points":          "problèmes identifiés dans cet appel (2-3 phrases concrètes)",
  "vocal_issues":         "problèmes vocaux détectés ou 'Aucun problème vocal détecté'",
  "recommended_training": "formation recommandée avec délai précis",
  "performance_summary":  "résumé objectif de la performance sur cet appel (2 phrases)"
}}"""

    # ── 4. Appel Gemini ───────────────────────────────────────────
    try:
        print(f"[coaching] Génération pour appel {call_id} — agent {call['full_name']}")
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY non configurée dans .env")

        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"[coaching] Réponse brute : {raw[:300]}")
        raw = re.sub(r"```json|```", "", raw).strip()
        coaching_data = json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"[coaching] JSON invalide, fallback : {e}")
        coaching_data = {
            "weak_points":          weaknesses,
            "vocal_issues":         vocal_context,
            "recommended_training": "Module qualité à définir selon le superviseur.",
            "performance_summary":  f"Score : {score}/100. Conformité : {compliance}.",
        }
    except Exception as e:
        print(f"[coaching] ERREUR : {type(e).__name__} — {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Gemini : {str(e)}")

    # ── 5. Sauvegarder (INSERT ou UPDATE par agent + call) ────────
    now = datetime.utcnow()
    agent_id = str(call["agent_id"])

    existing = fetchone("""
        SELECT id FROM coaching_notes
        WHERE agent_id = %s AND example_call_id = %s
    """, (agent_id, call_id))

    if existing:
        execute("""
            UPDATE coaching_notes SET
                weak_points             = %s,
                vocal_issues            = %s,
                recommended_training    = %s,
                performance_summary     = %s,
                avg_score_at_generation = %s,
                calls_analyzed          = 1,
                generated_at            = %s
            WHERE agent_id = %s AND example_call_id = %s
        """, (
            coaching_data.get("weak_points"),
            coaching_data.get("vocal_issues"),
            coaching_data.get("recommended_training"),
            coaching_data.get("performance_summary"),
            float(score),
            now,
            agent_id, call_id,
        ))
    else:
        execute("""
            INSERT INTO coaching_notes (
                id, agent_id,
                weak_points, vocal_issues, recommended_training,
                example_call_id, performance_summary,
                avg_score_at_generation, calls_analyzed, generated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s)
        """, (
            str(uuid.uuid4()),
            agent_id,
            coaching_data.get("weak_points"),
            coaching_data.get("vocal_issues"),
            coaching_data.get("recommended_training"),
            call_id,
            coaching_data.get("performance_summary"),
            float(score),
            now,
        ))

    print(f"[coaching] Fiche sauvegardée OK")

    return {
        "call_id":             call_id,
        "agent_name":          call["full_name"],
        "agent_initials":      call["initials"],
        "generated_at":        now.isoformat(),
        "avg_score_at_generation": float(score),
        "calls_analyzed":      1,
        **coaching_data,
    }


# ── Helper ────────────────────────────────────────────────────
def _extract_section(text: str, key: str) -> str:
    match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""
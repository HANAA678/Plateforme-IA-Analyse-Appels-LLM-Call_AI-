import uuid
from datetime import datetime
from core.database import execute


def generate_alerts(
    call_id: str,
    agent_id: str,
    evaluation: dict,
    diar: dict,
    thresholds: dict = None,
) -> list:
    """
    Génère les alertes automatiques après l'évaluation d'un appel.

    Sources de données :
        evaluation : dict retourné par evaluate.py
                     → score_total, compliance, sentiment_client, keywords
        diar       : dict retourné par diarize_audio()
                     → silence_max_sec

    5 règles :
        1. score_drop    — score trop bas            (critique)
        2. compliance    — appel non-conforme         (critique)
        3. churn_risk    — mots-clés résiliation      (critique)
        4. long_silence  — silence excessif           (moyenne)
        5. anger         — sentiment_client = negatif (moyenne)
    """
    if thresholds is None:
        thresholds = {
            "score_critical":   40,
            "score_compliance": 70,
            "silence_max_sec":  60,
        }

    alerts_inserted = []

    score       = evaluation.get("score_total", 100)
    compliance  = evaluation.get("compliance", "conforme")
    keywords    = [k.lower() for k in evaluation.get("keywords", [])]
    sentiment   = evaluation.get("sentiment_client", "neutre")
    silence_max = diar.get("silence_max_sec", 0)

    # ── 1. Score trop bas ─────────────────────────────────────────
    if score < thresholds["score_critical"]:
        alerts_inserted.append(_insert_alert(
            call_id=call_id,
            agent_id=agent_id,
            alert_type="score_drop",
            severity="critical",
            message=f"Score {score}/100 en dessous du seuil critique ({thresholds['score_critical']}).",
        ))

    # ── 2. Non-conformité ─────────────────────────────────────────
    if compliance == "non-conforme" and score < thresholds["score_compliance"]:
        alerts_inserted.append(_insert_alert(
            call_id=call_id,
            agent_id=agent_id,
            alert_type="compliance",
            severity="critical",
            message=f"Appel non-conforme (score {score}/100). Vérification requise avant archivage.",
        ))

    # ── 3. Risque résiliation ─────────────────────────────────────
    churn_keywords = {"résiliation", "résilier", "annuler", "quitter", "partir"}
    found = churn_keywords & set(keywords)
    if found:
        alerts_inserted.append(_insert_alert(
            call_id=call_id,
            agent_id=agent_id,
            alert_type="churn_risk",
            severity="critical",
            message=f"Risque résiliation détecté. Mots-clés : {', '.join(found)}.",
        ))

    # ── 4. Silence excessif ───────────────────────────────────────
    if silence_max >= thresholds["silence_max_sec"]:
        minutes = silence_max // 60
        seconds = silence_max % 60
        alerts_inserted.append(_insert_alert(
            call_id=call_id,
            agent_id=agent_id,
            alert_type="long_silence",
            severity="medium",
            message=f"Silence excessif de {minutes}m{seconds:02d}s détecté durant l'appel.",
        ))

    # ── 5. Client négatif (depuis sentiment_client de Gemini) ─────
    if sentiment == "negatif":
        alerts_inserted.append(_insert_alert(
            call_id=call_id,
            agent_id=agent_id,
            alert_type="anger",
            severity="medium",
            message="Sentiment client négatif détecté par l'analyse Gemini. Suivi recommandé.",
        ))

    print(f"[alerts] {len(alerts_inserted)} alerte(s) générée(s) pour l'appel {call_id}")
    return alerts_inserted


def _insert_alert(
    call_id: str,
    agent_id: str,
    alert_type: str,
    severity: str,
    message: str,
) -> dict:
    """Insère une alerte en BDD et retourne son dict."""
    alert_id = str(uuid.uuid4())
    now = datetime.utcnow()

    execute(
        """
        INSERT INTO `dda-dpl-datalab-sdbx-za.SpeakFlow.alerts`
        (id, call_id, agent_id, type, severity, message, resolved, triggered_at)
        VALUES (@alert_id, @call_id, @agent_id, @type, @severity, @message, false, @triggered_at)
        """,
        {
            "alert_id":    alert_id,
            "call_id":     call_id,
            "agent_id":    agent_id,
            "type":        alert_type,
            "severity":    severity,
            "message":     message,
            "triggered_at": now,
        },
    )

    print(f"[alerts] [{severity.upper()}] {alert_type} — {message}")

    return {
        "id":           alert_id,
        "call_id":      call_id,
        "agent_id":     agent_id,
        "type":         alert_type,
        "severity":     severity,
        "message":      message,
        "resolved":     False,
        "triggered_at": now.isoformat(),
    }
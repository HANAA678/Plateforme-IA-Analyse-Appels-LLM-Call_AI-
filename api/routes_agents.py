import uuid
from fastapi import APIRouter, HTTPException
from core.database import fetchall, fetchone, execute

router = APIRouter()


# ================================================================
# ÉQUIPES
# ================================================================

@router.get("/api/teams")
def get_teams():
    """
    Retourne la liste de toutes les équipes.
    Utilisé par : page Upload (filtre agent), page Agents (filtre équipe)
    """
    rows = fetchall("SELECT id, name, supervisor_name FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` ORDER BY name")
    return [dict(r) for r in rows] if rows else []


@router.post("/api/teams", status_code=201)
def create_team(body: dict):
    """
    Crée une nouvelle équipe.
    Body : { "name": "Équipe A", "supervisor_name": "Hassan" }
    """
    name            = body.get("name", "").strip()
    supervisor_name = body.get("supervisor_name", "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Le champ 'name' est obligatoire.")

    team_id = str(uuid.uuid4())
    execute(
        "INSERT INTO `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` (id, name, supervisor_name) VALUES (@team_id, @name, @supervisor_name)",
        {"team_id": team_id, "name": name, "supervisor_name": supervisor_name or None},
    )
    return {"id": team_id, "name": name, "supervisor_name": supervisor_name}


# ================================================================
# AGENTS
# ================================================================

@router.get("/api/agents")
def get_agents(team_id: str = None):
    """
    Retourne la liste des agents triée par score décroissant.
    Paramètre optionnel : team_id pour filtrer par équipe.
    Utilisé par : page Upload (menu déroulant), page Agents (tableau)
    """
    if team_id:
        rows = fetchall(
            """
            SELECT
                a.id,
                a.full_name,
                a.initials,
                a.email,
                a.avg_score,
                a.total_calls,
                t.name AS team_name
            FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` a
            LEFT JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` t ON t.id = a.team_id
            WHERE a.team_id = @team_id
            ORDER BY a.avg_score DESC
            """,
            {"team_id": team_id},
        )
    else:
        rows = fetchall(
            """
            SELECT
                a.id,
                a.full_name,
                a.initials,
                a.email,
                a.avg_score,
                a.total_calls,
                t.name AS team_name
            FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` a
            LEFT JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` t ON t.id = a.team_id
            ORDER BY a.avg_score DESC
            """
        )
    return [dict(r) for r in rows] if rows else []


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str):
    """
    Retourne le détail d'un agent + son historique de score sur 12 semaines.
    Utilisé par : page Agents (détail), page Coaching
    """
    agent = fetchone(
        """
        SELECT
            a.id,
            a.full_name,
            a.initials,
            a.email,
            a.avg_score,
            a.total_calls,
            t.name AS team_name
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` a
        LEFT JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` t ON t.id = a.team_id
        WHERE a.id = @agent_id
        """,
        {"agent_id": agent_id},
    )

    if not agent:
        raise HTTPException(status_code=404, detail="Agent introuvable.")

    # Historique score par semaine sur les 12 dernières semaines
    history_rows = fetchall(
        """
        SELECT
            DATE_TRUNC(c.called_at, WEEK)  AS week,
            ROUND(AVG(e.score_total), 1)   AS avg_score
        FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` c
        JOIN `dda-dpl-datalab-sdbx-za.SpeakFlow.evaluations` e ON e.call_id = c.id
        WHERE c.agent_id = @agent_id
          AND c.called_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 12 WEEK)
          AND c.status = 'evaluated'
        GROUP BY DATE_TRUNC(c.called_at, WEEK)
        ORDER BY week ASC
        """,
        {"agent_id": agent_id},
    )

    score_history = [float(r["avg_score"]) for r in history_rows] if history_rows else []

    return {**dict(agent), "score_history": score_history}


@router.post("/api/agents", status_code=201)
def create_agent(body: dict):
    """
    Crée un nouvel agent. Calcule les initiales automatiquement.
    Body : { "full_name": "Karim Alaoui", "email": "karim@test.ma", "team_id": "uuid" }
    Utilisé par : page Agents (bouton "Ajouter un agent")
    """
    full_name = body.get("full_name", "").strip()
    email     = body.get("email", "").strip()
    team_id   = body.get("team_id", "").strip() or None

    if not full_name:
        raise HTTPException(status_code=400, detail="Le champ 'full_name' est obligatoire.")

    # Calcul automatique des initiales (ex: "Karim Alaoui" → "KA")
    parts    = full_name.split()
    initials = "".join(p[0].upper() for p in parts[:3])

    # Vérifier que team_id existe si fourni
    if team_id:
        team = fetchone(
            "SELECT id FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.teams` WHERE id = @team_id",
            {"team_id": team_id},
        )
        if not team:
            raise HTTPException(status_code=400, detail="team_id invalide.")

    agent_id = str(uuid.uuid4())
    execute(
        """
        INSERT INTO `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` (id, team_id, full_name, initials, email, avg_score, total_calls)
        VALUES (@agent_id, @team_id, @full_name, @initials, @email, 0, 0)
        """,
        {
            "agent_id":  agent_id,
            "team_id":   team_id,
            "full_name": full_name,
            "initials":  initials,
            "email":     email or None,
        },
    )

    return {
        "id":        agent_id,
        "full_name": full_name,
        "initials":  initials,
        "email":     email,
        "team_id":   team_id,
    }
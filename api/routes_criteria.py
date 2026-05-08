from fastapi import APIRouter, HTTPException
from core.database import fetchall, fetchone, execute

router = APIRouter()


# ================================================================
# CRITÈRES
# ================================================================

@router.get("/api/criteria")
def get_criteria():
    """
    Retourne la liste des 5 critères d'évaluation.
    Utilisé par : page Upload (aperçu des critères)
                  page Rapport (barres de score par critère)
    """
    rows = fetchall(
        """
        SELECT id, key, label, max_pts, description, is_active, sort_order
        FROM criteria_config
        ORDER BY sort_order
        """
    )
    return [dict(r) for r in rows] if rows else []


@router.put("/api/criteria/{key}")
def update_criteria(key: str, body: dict):
    """
    Modifie un critère existant (label, description, max_pts, is_active).
    Identifié par sa clé unique (ex: "greeting", "listening"...).
    Utilisé par : page Paramètres (si ajoutée plus tard)

    Body (tous les champs sont optionnels) :
    {
      "label":       "Nouveau label",
      "description": "Nouvelle description",
      "max_pts":     20,
      "is_active":   true
    }
    """
    # Vérifier que le critère existe
    existing = fetchone(
        "SELECT id FROM criteria_config WHERE key = %s",
        (key,),
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f"Critère '{key}' introuvable.")

    # Construire la mise à jour dynamiquement
    # (on ne met à jour que les champs fournis dans le body)
    allowed_fields = {"label", "description", "max_pts", "is_active"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}

    if not updates:
        raise HTTPException(
            status_code=400,
            detail=f"Aucun champ valide fourni. Champs acceptés : {allowed_fields}",
        )

    set_clause = ", ".join(f"{field} = %s" for field in updates)
    values     = list(updates.values()) + [key]

    execute(
        f"UPDATE criteria_config SET {set_clause} WHERE key = %s",
        values,
    )

    # Retourner le critère mis à jour
    updated = fetchone(
        "SELECT id, key, label, max_pts, description, is_active, sort_order FROM criteria_config WHERE key = %s",
        (key,),
    )
    return dict(updated)

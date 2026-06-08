import os
import uuid
import shutil
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from core.database import execute, fetchone, fetchall
from pipeline.runner import run_pipeline

router = APIRouter()

UPLOAD_DIR = "/tmp/audio"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ================================================================
# POST /api/upload
# ================================================================

@router.post("/api/upload")
async def upload_call(
    file:             UploadFile = File(...),
    agent_id:         str        = Form(...),
    called_at:        str        = Form(...),
    call_type:        str        = Form("information"),
    priority:         str        = Form("normale"),
    supervisor_notes: str        = Form(""),
    focus_points:     str        = Form(""),
):
    # ── 1. Valider le fichier ──────────────────────────────────────
    if not file.filename.endswith(".wav"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .wav sont acceptés.")

    # ── 2. Valider call_type et priority ──────────────────────────
    valid_call_types = {"reclamation", "commercial", "technique", "information"}
    valid_priorities = {"normale", "haute", "urgente"}
    if call_type not in valid_call_types:
        raise HTTPException(status_code=400, detail=f"call_type invalide. Valeurs acceptées : {valid_call_types}")
    if priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"priority invalide. Valeurs acceptées : {valid_priorities}")

    # ── 3. Valider l'agent ────────────────────────────────────────
    agent = fetchone(
        "SELECT id FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.agents` WHERE id = @agent_id",
        {"agent_id": agent_id},
    )
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} introuvable.")

    # ── 4. Sauvegarder le fichier localement ──────────────────────
    call_id    = str(uuid.uuid4())
    filename   = f"{call_id}.wav"
    audio_path = os.path.join(UPLOAD_DIR, filename)

    with open(audio_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # ── 5. Parser called_at ───────────────────────────────────────
    try:
        called_at_dt = datetime.fromisoformat(called_at)
    except ValueError:
        called_at_dt = datetime.now()

    # ── 6. Créer la ligne dans calls (status = pending) ───────────
    audio_url = f"/tmp/audio/{filename}"

    execute("""
        INSERT INTO `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` (
            id, agent_id, audio_url, called_at,
            call_type, priority,
            supervisor_notes, focus_points,
            status, created_at
        )
        VALUES (@call_id, @agent_id, @audio_url, @called_at,
                @call_type, @priority,
                @supervisor_notes, @focus_points,
                'pending', CURRENT_TIMESTAMP())
    """, {
        "call_id":          call_id,
        "agent_id":         agent_id,
        "audio_url":        audio_url,
        "called_at":        called_at_dt,
        "call_type":        call_type,
        "priority":         priority,
        "supervisor_notes": supervisor_notes or None,
        "focus_points":     focus_points     or None,
    })

    print(f"[upload] Appel {call_id} créé — lancement pipeline...")

    # ── 7. Lancer le pipeline (synchrone) ─────────────────────────
    try:
        aligned_text = run_pipeline(
            call_id    = call_id,
            audio_path = audio_path,
            execute    = execute,
            fetchone   = fetchone,
            fetchall   = fetchall,
        )
    except Exception as e:
        execute(
            "UPDATE `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` SET status = 'failed' WHERE id = @call_id",
            {"call_id": call_id},
        )
        print(f"[upload] Pipeline echoue : {e}")
        raise HTTPException(status_code=500, detail=f"Erreur pipeline : {str(e)}")

    # ── 8. Retourner la réponse avec la transcription alignée ─────
    return JSONResponse(status_code=200, content={
        "call_id":      call_id,
        "status":       "evaluated",
        "message":      "Pipeline termine avec succes.",
        "aligned_text": aligned_text or "",
    })


# ================================================================
# GET /api/calls/{id}/status  — polling toutes les 3s
# ================================================================

@router.get("/api/calls/{call_id}/status")
def get_call_status(call_id: str):
    """
    Retourne le statut + la transcription alignée si disponible.
    Valeurs : pending → transcribed → evaluated → failed
    """
    row = fetchone(
        "SELECT status, transcription_text FROM `dda-dpl-datalab-sdbx-za.SpeakFlow.calls` WHERE id = @call_id",
        {"call_id": call_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Appel introuvable.")

    return {
        "call_id":            call_id,
        "status":             row["status"],
        "transcription_text": row["transcription_text"] or "",
    }
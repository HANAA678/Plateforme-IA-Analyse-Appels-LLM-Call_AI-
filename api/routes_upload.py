from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
from datetime import datetime
import uuid
import os

from pipeline.runner import run_pipeline
from core.database import fetchone, execute

router = APIRouter()


def process_call(call_id: str):

    call = fetchone("SELECT * FROM calls WHERE id=%s", (call_id,))

    if not call:
        return

    # SUPPRIMÉ : status "processing" n'existe pas

    audio_path = os.path.join(
        "uploads",
        os.path.basename(call["audio_url"])
    )

    # récupérer le texte correctement
    text = run_pipeline(call_id, audio_path, execute, fetchone)

    print("TEXT:", text)


@router.post("/api/upload")
async def upload_audio(
    file: UploadFile = File(...),
    agent_id: str = Form(...),
    called_at: str = Form(...),
    call_type: str = Form(...),
    priority: str = Form(...),
    supervisor_notes: str = Form(None),
    focus_points: str = Form(None),
    background_tasks: BackgroundTasks = None
):

    content = await file.read()

    os.makedirs("uploads", exist_ok=True)

    filename = f"{uuid.uuid4()}.wav"
    filepath = os.path.join("uploads", filename)

    with open(filepath, "wb") as f:
        f.write(content)

    audio_url = f"/uploads/{filename}"
    called_at_dt = datetime.fromisoformat(called_at)

    result = fetchone("""
        INSERT INTO calls (
            agent_id, audio_url, called_at, status,
            call_type, priority, supervisor_notes, focus_points
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        agent_id,
        audio_url,
        called_at_dt,
        "pending",
        call_type,
        priority,
        supervisor_notes,
        focus_points
    ))

    call_id = result["id"]

    if background_tasks:
        background_tasks.add_task(process_call, str(call_id))

    return {
        "message": "upload successful",
        "call_id": str(call_id),
        "audio_url": audio_url,
        "status": "pending"
    }
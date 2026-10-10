import io
import json
import logging
import shutil
import uuid
from typing import Any, Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile

from backend.app.config import settings
from backend.app.db import create_job_record, get_db_connection, get_job, init_db, list_jobs
from backend.app.storage import save_uploaded_file
from backend.app.transcription import transcribe_audio, validate_audio_file

logger = logging.getLogger(__name__)
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

app = FastAPI(title=settings.APP_NAME)


def normalize_segments(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, list):
        return raw
    return []


def serialize_job(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": row["id"],
        "status": row["status"],
        "filename": row["filename"],
        "original_name": row["original_name"],
        "storage_path": row["storage_path"],
        "language": row.get("language"),
        "transcript": row.get("transcript"),
        "segments": normalize_segments(row.get("segments")),
        "error": row.get("error"),
        "retry_count": row.get("retry_count", 0),
        "max_retries": row.get("max_retries", settings.MAX_RETRIES),
        "worker_name": row.get("worker_name"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "processing_started_at": row.get("processing_started_at"),
        "finished_at": row.get("finished_at"),
        "metadata": row.get("metadata", {}),
    }


@app.on_event("startup")
async def startup_event() -> None:
    try:
        init_db()
    except Exception as exc:  # pragma: no cover - depends on local DB availability
        logger.warning("Database initialization failed during startup: %s", exc)


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    db_ok = False
    try:
        conn = get_db_connection()
        if conn is None:
            db_ok = True
        else:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            db_ok = True
    except Exception as exc:  # pragma: no cover - depends on runtime DB
        logger.warning("Database health check failed: %s", exc)

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "ffmpeg": ffmpeg_ok,
        "service": "fastapi",
    }


@app.post("/api/jobs/upload")
async def upload_audio(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file name provided")

    file_bytes = await file.read()
    try:
        validate_audio_file(file.filename, len(file_bytes))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex
    storage_path = save_uploaded_file(io.BytesIO(file_bytes), file.filename)
    new_record = create_job_record(
        job_id=job_id,
        original_name=file.filename,
        storage_path=storage_path,
        filename=f"{job_id}_{file.filename}",
    )

    return {
        "job_id": job_id,
        "status": new_record["status"],
        "filename": file.filename,
        "storage_path": storage_path,
    }


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str) -> Dict[str, Any]:
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_job(row)


@app.get("/api/jobs")
async def get_jobs() -> List[Dict[str, Any]]:
    rows = list_jobs()
    return [serialize_job(row) for row in rows]


@app.post("/api/jobs/{job_id}/transcribe")
async def trigger_transcription(job_id: str) -> Dict[str, Any]:
    current = get_job(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if current["status"] == "completed":
        return serialize_job(current)

    try:
        result = transcribe_audio(current["storage_path"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc

    from backend.app.db import update_job_status

    updated = update_job_status(
        job_id,
        status="completed",
        language=result["language"],
        transcript=result["transcript"],
        segments=result["segments"],
        error=None,
    )
    return serialize_job(updated)

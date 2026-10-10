import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from backend.app.config import settings

logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        connect_timeout=5,
    )


def init_db() -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    language TEXT,
                    transcript TEXT,
                    segments JSONB NOT NULL DEFAULT '[]'::jsonb,
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    processing_started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ,
                    worker_name TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs (status, updated_at);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_processing_started ON jobs (processing_started_at);"
            )
            conn.commit()
    logger.info("Database initialized")


def create_job_record(job_id: str, original_name: str, storage_path: str, filename: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO jobs (id, filename, original_name, storage_path, status, retry_count, max_retries, metadata)
                VALUES (%s, %s, %s, %s, 'queued', 0, %s, %s)
                RETURNING *;
                """,
                (
                    job_id,
                    filename,
                    original_name,
                    storage_path,
                    settings.MAX_RETRIES,
                    json.dumps({"source": "upload"}),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s;", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def list_jobs() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100;"
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def update_job_status(
    job_id: str,
    *,
    status: Optional[str] = None,
    language: Optional[str] = None,
    transcript: Optional[str] = None,
    segments: Optional[List[Dict[str, Any]]] = None,
    error: Optional[str] = None,
    retry_count: Optional[int] = None,
    worker_name: Optional[str] = None,
    finished_at: Optional[datetime] = None,
    processing_started_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing = get_job(job_id)
    if existing is None:
        raise ValueError(f"Job {job_id} does not exist")

    if segments is not None:
        payload_segments = json.dumps(segments)
    elif isinstance(existing.get("segments"), str):
        payload_segments = existing["segments"]
    elif existing.get("segments") is not None:
        payload_segments = json.dumps(existing["segments"])
    else:
        payload_segments = "[]"

    payload = {
        "status": status if status is not None else existing["status"],
        "language": language if language is not None else existing["language"],
        "transcript": transcript if transcript is not None else existing["transcript"],
        "segments": payload_segments,
        "error": error if error is not None else existing["error"],
        "retry_count": retry_count if retry_count is not None else existing["retry_count"],
        "worker_name": worker_name if worker_name is not None else existing["worker_name"],
        "finished_at": finished_at if finished_at is not None else existing.get("finished_at"),
        "processing_started_at": processing_started_at if processing_started_at is not None else existing.get("processing_started_at"),
        "updated_at": datetime.now(timezone.utc),
    }

    if metadata is not None:
        payload["metadata"] = json.dumps(metadata)
    elif existing.get("metadata") is not None and not isinstance(existing.get("metadata"), str):
        payload["metadata"] = json.dumps(existing["metadata"])

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = %s,
                    language = %s,
                    transcript = %s,
                    segments = %s::jsonb,
                    error = %s,
                    retry_count = %s,
                    worker_name = %s,
                    finished_at = %s,
                    processing_started_at = %s,
                    updated_at = %s,
                    metadata = COALESCE(%s::jsonb, metadata)
                WHERE id = %s
                RETURNING *;
                """,
                (
                    payload["status"],
                    payload["language"],
                    payload["transcript"],
                    payload["segments"],
                    payload["error"],
                    payload["retry_count"],
                    payload["worker_name"],
                    payload["finished_at"],
                    payload["processing_started_at"],
                    payload["updated_at"],
                    payload.get("metadata"),
                    job_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def recover_stale_jobs() -> List[str]:
    stale_deadline = datetime.now(timezone.utc) - timedelta(seconds=settings.STALE_JOB_TIMEOUT_SECONDS)
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE status = 'processing' AND processing_started_at < %s ORDER BY created_at ASC;",
                (stale_deadline,),
            )
            rows = cur.fetchall()
            recovered = []
            for row in rows:
                row_dict = dict(row)
                retry_count = int(row_dict["retry_count"])
                if retry_count >= int(row_dict["max_retries"]):
                    cur.execute(
                        "UPDATE jobs SET status = 'failed', error = 'Job timed out and exhausted retries', updated_at = NOW(), finished_at = NOW() WHERE id = %s;",
                        (row_dict["id"],),
                    )
                else:
                    next_retry = retry_count + 1
                    cur.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued',
                            retry_count = %s,
                            error = 'Recovered after worker failure; retrying',
                            updated_at = NOW(),
                            processing_started_at = NULL,
                            worker_name = NULL
                        WHERE id = %s;
                        """,
                        (next_retry, row_dict["id"]),
                    )
                recovered.append(row_dict["id"])
            conn.commit()
            return recovered


def claim_next_job(worker_name: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE jobs j
                SET status = 'processing',
                    worker_name = %s,
                    processing_started_at = NOW(),
                    updated_at = NOW(),
                    error = NULL
                FROM candidate
                WHERE j.id = candidate.id
                RETURNING j.*;
                """,
                (worker_name,),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

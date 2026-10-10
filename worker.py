import argparse
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, Optional

from backend.app.config import settings
from backend.app.db import claim_next_job, get_job, init_db, recover_stale_jobs, update_job_status
from backend.app.transcription import transcribe_audio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")


def process_job(job: Dict[str, object], worker_name: str) -> None:
    job_id = str(job["id"])
    job_record = get_job(job_id)
    if job_record is None:
        logger.warning("Job %s no longer exists; skipping.", job_id)
        return

    try:
        result = transcribe_audio(str(job_record["storage_path"]), model_size=settings.MODEL_SIZE)
        update_job_status(
            job_id,
            status="completed",
            language=result["language"],
            transcript=result["transcript"],
            segments=result["segments"],
            error=None,
            metadata={"duration": result["duration"]},
        )
        logger.info("Completed job %s with %s segments", job_id, len(result["segments"]))
    except Exception as exc:  # pragma: no cover - exercised in runtime
        retry_count = int(job_record.get("retry_count", 0)) + 1
        if retry_count < int(job_record.get("max_retries", settings.MAX_RETRIES)):
            update_job_status(
                job_id,
                status="queued",
                retry_count=retry_count,
                error=f"Processing failed: {exc}; retrying",
                worker_name=None,
                processing_started_at=None,
            )
            logger.warning("Job %s failed, requeued (attempt %s/%s): %s", job_id, retry_count, job_record.get("max_retries"), exc)
        else:
            update_job_status(
                job_id,
                status="failed",
                retry_count=retry_count,
                error=str(exc),
                worker_name=None,
                finished_at=None,
                processing_started_at=None,
            )
            logger.error("Job %s permanently failed: %s", job_id, exc)


def run_worker_loop(concurrency: int = 1, poll_seconds: float = 3.0) -> None:
    init_db()
    worker_name = f"worker-{concurrency}"
    futures: Dict[Future, str] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while True:
            recover_stale_jobs()
            for future in list(futures.keys()):
                if future.done():
                    try:
                        future.result()
                    finally:
                        futures.pop(future, None)

            while len(futures) < concurrency:
                job = claim_next_job(worker_name)
                if job is None:
                    break
                future = executor.submit(process_job, job, worker_name)
                futures[future] = str(job["id"])

            if not futures:
                logger.info("No jobs available; sleeping for %.1f seconds", poll_seconds)
                time.sleep(poll_seconds)
            else:
                time.sleep(0.5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queued audio transcription workers")
    parser.add_argument("--concurrency", type=int, default=settings.WORKER_CONCURRENCY)
    parser.add_argument("--poll-seconds", type=float, default=settings.WORKER_POLL_SECONDS)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_worker_loop(concurrency=args.concurrency, poll_seconds=args.poll_seconds)

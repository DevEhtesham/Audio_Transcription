import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

from faster_whisper import WhisperModel

from backend.app.config import settings

logger = logging.getLogger(__name__)


def validate_audio_file(filename: str, file_size_bytes: int) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {filename}. Allowed: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}"
        )

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise ValueError(
            f"File is too large ({file_size_bytes / (1024 * 1024):.1f} MB). Maximum allowed: {settings.MAX_FILE_SIZE_MB} MB."
        )


def build_segment_payload(segments: Iterable[Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = (segment.text or "").strip()
        if not text:
            continue
        results.append(
            {
                "id": index,
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": text,
            }
        )
    return results


def transcribe_audio(file_path: str, model_size: str | None = None) -> Dict[str, Any]:
    model_name = model_size or settings.MODEL_SIZE
    logger.info("Loading Whisper model %s", model_name)
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        download_root=settings.MODEL_CACHE_DIR,
    )

    segments, info = model.transcribe(file_path, beam_size=5, vad_filter=True)
    segment_payload = build_segment_payload(segments)
    transcript = " ".join(item["text"] for item in segment_payload)

    return {
        "transcript": transcript.strip(),
        "language": info.language or "unknown",
        "duration": round(float(info.duration), 3),
        "segments": segment_payload,
    }

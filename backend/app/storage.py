import os
import uuid
from pathlib import Path

from backend.app.config import settings


def sanitize_filename(name: str) -> str:
    root = Path(name).name
    safe = root.replace(" ", "_")
    safe = "".join(ch for ch in safe if ch.isalnum() or ch in {"_", ".", "-"})
    return safe or "audio"


def save_uploaded_file(file_obj, original_name: str) -> str:
    safe_name = sanitize_filename(original_name)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    target_dir = Path(settings.UPLOAD_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / unique_name
    with open(destination, "wb") as file_handle:
        file_handle.write(file_obj.read())
    return str(destination)

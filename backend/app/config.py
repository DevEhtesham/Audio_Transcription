import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = os.getenv("APP_NAME", "audio-transcription-system")
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))
    STREAMLIT_HOST = os.getenv("STREAMLIT_HOST", "0.0.0.0")
    STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "transcription")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "storage/uploads")
    MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR", ".cache/faster_whisper")
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "250"))
    ALLOWED_EXTENSIONS = {
        ext.strip().lower()
        for ext in os.getenv("ALLOWED_EXTENSIONS", ".wav,.mp3,.flac,.m4a,.ogg,.aac,.webm,.wma").split(",")
        if ext.strip()
    }

    MODEL_SIZE = os.getenv("MODEL_SIZE", "tiny")
    WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
    WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "3.0"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    STALE_JOB_TIMEOUT_SECONDS = int(os.getenv("STALE_JOB_TIMEOUT_SECONDS", "1800"))
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

    @classmethod
    def ensure_paths(cls):
        Path(cls.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.MODEL_CACHE_DIR).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_paths()

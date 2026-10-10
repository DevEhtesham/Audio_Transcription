import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health_endpoint(monkeypatch):
    monkeypatch.setattr("backend.app.main.get_db_connection", lambda: None)
    with patch("backend.app.main.shutil.which", return_value="/usr/bin/ffmpeg"):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ok", "degraded"}
    assert data["ffmpeg"] is True


def test_upload_endpoint(monkeypatch):
    monkeypatch.setattr("backend.app.main.save_uploaded_file", lambda file_obj, name: "/tmp/demo.wav")

    def fake_create_job_record(job_id, original_name, storage_path, filename):
        return {"id": job_id, "status": "queued"}

    monkeypatch.setattr("backend.app.main.create_job_record", fake_create_job_record)

    response = client.post(
        "/api/jobs/upload",
        files={"file": ("demo.wav", io.BytesIO(b"RIFF...."), "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["filename"] == "demo.wav"


def test_job_status_response(monkeypatch):
    monkeypatch.setattr("backend.app.main.get_job", lambda job_id: {
        "id": job_id,
        "status": "completed",
        "filename": "demo.wav",
        "original_name": "demo.wav",
        "storage_path": "/tmp/demo.wav",
        "language": "en",
        "transcript": "hello world",
        "segments": [{"start": 0.0, "end": 1.2, "text": "hello world"}],
        "error": None,
        "retry_count": 0,
        "max_retries": 3,
        "worker_name": "worker-1",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "processing_started_at": "2024-01-01T00:00:00Z",
        "finished_at": "2024-01-01T00:00:10Z",
        "metadata": {},
    })

    response = client.get("/api/jobs/test-job")
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "test-job"
    assert payload["status"] == "completed"
    assert payload["transcript"] == "hello world"
    assert payload["segments"][0]["text"] == "hello world"

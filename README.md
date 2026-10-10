# Audio Transcription System

A local audio transcription app built with FastAPI, Streamlit, PostgreSQL, and faster-whisper. Upload an audio file in the web interface, let a background worker transcribe it, then view or download the transcript and timestamped segments.

## Features

- Audio upload with extension and file-size validation.
- PostgreSQL-backed job queue and status tracking.
- Background transcription with faster-whisper.
- Transcript, detected language, duration, and timestamped segments.
- TXT and JSON transcript downloads.
- Retry handling and recovery of jobs left processing after a worker interruption.

## Architecture

The app runs as three processes, with PostgreSQL as a separate service:

1. **Streamlit** provides the upload and results interface (`http://localhost:8501`).
2. **FastAPI** accepts uploads and serves job status (`http://localhost:8000`).
3. **Worker** polls PostgreSQL for queued jobs and runs transcription.
4. **PostgreSQL** stores job metadata and results. Uploaded audio is stored on disk under `storage/uploads/`.

The normal lifecycle is `queued -> processing -> completed` or `failed`. Streamlit polls the API while the worker processes the audio. Multiple workers can claim different jobs safely using PostgreSQL's `FOR UPDATE SKIP LOCKED` query.

## Requirements

- Windows with Python 3.11 recommended.
- PostgreSQL installed and running, with credentials that match `.env`.
- FFmpeg available for audio decoding support. faster-whisper uses PyAV/FFmpeg libraries to read audio; the API health endpoint also reports whether the `ffmpeg` executable is discoverable on `PATH`.

The first transcription may take longer because faster-whisper downloads the configured model into the model cache.

## Setup (Windows PowerShell)

Run commands from the project root:

```powershell
cd "C:\Users\<you>\Desktop\My_Projects\Audio_transcription_system"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `DB_PASSWORD` to the password for your PostgreSQL user. Do not commit `.env`; it is excluded by `.gitignore`.

If PowerShell blocks venv activation, either open a PowerShell session permitted to run the activation script or run the venv's Python directly, for example:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Create the database

Make sure PostgreSQL is running and accepting connections on the host and port configured in `.env` (defaults: `localhost:5432`). Create the database once, using the PostgreSQL command-line tools:

```powershell
createdb -h localhost -p 5432 -U postgres transcription
```

Enter the PostgreSQL password when prompted. If the `transcription` database already exists, skip this step. The API initializes the `jobs` table and its indexes at startup; the worker also calls the same initialization routine.

## Run the application

Keep PostgreSQL running, then open three PowerShell terminals in the project root. Activate `.venv` in each terminal, or use the `.venv` executable paths shown below.

**Terminal 1: FastAPI backend**

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2: background worker**

```powershell
.\.venv\Scripts\python.exe worker.py
```

The worker uses `WORKER_CONCURRENCY` and `WORKER_POLL_SECONDS` from `.env` by default. They can also be overridden with command-line options:

```powershell
.\.venv\Scripts\python.exe worker.py --concurrency 2 --poll-seconds 3
```

**Terminal 3: Streamlit interface**

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.port 8501
```

Open <http://localhost:8501> in a browser. The API documentation is available at <http://localhost:8000/docs>.

## Upload-to-transcript flow

1. Streamlit sends the selected file to `POST /api/jobs/upload`.
2. FastAPI checks the file extension and configured size limit, saves it with a unique name, then inserts a `queued` job in PostgreSQL.
3. The worker claims the oldest queued job, marks it `processing`, and sends the saved file to faster-whisper.
4. faster-whisper decodes the audio through its audio backend and returns recognized text, language, duration, and segments.
5. The worker stores those results and marks the job `completed`. On processing errors it requeues the job within the retry limit, then marks it `failed` if attempts are exhausted.
6. Streamlit polls the job-status endpoint and displays the final transcript, segment timestamps, and download buttons.

## Configuration

Settings are loaded from `.env` by `backend/app/config.py`. Common options:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `localhost` / `5432` | PostgreSQL host and port |
| `DB_NAME` | `transcription` | Database name |
| `DB_USER` / `DB_PASSWORD` | `postgres` / `postgres` | Database login; replace the password locally |
| `UPLOAD_DIR` | `storage/uploads` | Location of saved audio files |
| `MAX_FILE_SIZE_MB` | `250` | Maximum accepted upload size |
| `ALLOWED_EXTENSIONS` | `.wav,.mp3,.flac,.m4a,.ogg,.aac,.webm,.wma` | Accepted file extensions |
| `MODEL_SIZE` | `tiny` | faster-whisper model size |
| `MODEL_CACHE_DIR` | `.cache/faster_whisper` | Downloaded model cache directory |
| `WORKER_CONCURRENCY` | `2` | Jobs processed concurrently by one worker process |
| `WORKER_POLL_SECONDS` | `3.0` | Delay between checks when no job is queued |
| `MAX_RETRIES` | `3` | Maximum processing attempts per job |
| `STALE_JOB_TIMEOUT_SECONDS` | `1800` | Time before a stuck processing job can be recovered |
| `API_BASE_URL` | `http://localhost:8000` | Backend URL used by Streamlit |

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Reports API, database, and FFmpeg executable health |
| `POST` | `/api/jobs/upload` | Uploads a file and creates a queued job |
| `GET` | `/api/jobs/{job_id}` | Returns status and, when ready, transcript data |
| `GET` | `/api/jobs` | Lists the latest jobs |
| `POST` | `/api/jobs/{job_id}/transcribe` | Runs transcription synchronously through the API instead of the worker queue |

The queued upload endpoint returns a job ID and initial status. Poll `GET /api/jobs/{job_id}` to retrieve the final response, including `transcript`, `language`, `segments`, and any `error`.

## Tests

Run the test suite from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The API tests cover health, upload validation/response, and job-status serialization.

## Troubleshooting

- **Database authentication failed:** Check `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`, then restart the API and worker so they reload the settings.
- **Connection refused:** Confirm the PostgreSQL service is running and listening on the configured host and port.
- **Job remains queued:** Confirm the worker process is running and connects to the same database as the API.
- **Transcription fails:** Check the worker terminal for the error. Confirm the audio is readable and that the faster-whisper model can be downloaded or loaded from the configured cache.
- **FFmpeg health is false:** Ensure the FFmpeg executable is on `PATH`. This health indicator checks the executable; PyAV's FFmpeg libraries are used by faster-whisper for decoding.

import json
import os
import time
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SUPPORTED_TYPES = ["wav", "mp3", "flac", "m4a", "ogg", "aac", "webm", "wma"]


st.set_page_config(page_title="Audio Transcription", layout="wide")


def fetch_job(job_id: str) -> Dict[str, Any]:
    response = requests.get(f"{API_BASE_URL}/api/jobs/{job_id}", timeout=30)
    if response.status_code == 404:
        raise LookupError(f"Job {job_id} not found")
    response.raise_for_status()
    return response.json()


def upload_audio(file_obj) -> Dict[str, Any]:
    files = {"file": (file_obj.name, file_obj.getvalue(), file_obj.type or "application/octet-stream")}
    response = requests.post(f"{API_BASE_URL}/api/jobs/upload", files=files, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("detail", response.text))
    return response.json()


st.title("Audio Transcription Dashboard")
st.caption("Upload audio files and track the transcription queue in real time.")

with st.sidebar:
    st.header("Service health")
    try:
        health = requests.get(f"{API_BASE_URL}/api/health", timeout=20)
        if health.ok:
            payload = health.json()
            st.success(f"Status: {payload.get('status', 'unknown')}")
            st.write(payload)
        else:
            st.error("API health endpoint unavailable")
    except requests.RequestException as exc:
        st.error(f"Unable to reach backend: {exc}")

uploaded = st.file_uploader("Choose an audio file", type=SUPPORTED_TYPES, accept_multiple_files=False)

if uploaded is not None:
    if st.button("Upload and transcribe"):
        try:
            result = upload_audio(uploaded)
            st.session_state["job_id"] = result["job_id"]
            st.session_state["current_job"] = result
            st.success(f"Job created: {result['job_id']}")
        except Exception as exc:
            st.error(f"Upload failed: {exc}")

if "job_id" in st.session_state:
    job_id = st.session_state["job_id"]
    job = None
    status_container = st.empty()

    while True:
        try:
            job = fetch_job(job_id)
        except requests.RequestException:
            status_container.warning("Waiting for backend to respond...")
            time.sleep(2)
            continue
        except LookupError:
            st.error(f"Could not find the transcription job {job_id}.")
            break

        status = job.get("status", "unknown")
        status_container.info(f"Current status: {status}")

        if status in {"completed", "failed"}:
            break
        time.sleep(2)

    if job:
        st.subheader("Job details")
        st.json({
            "job_id": job["job_id"],
            "status": job["status"],
            "retry_count": job.get("retry_count", 0),
            "error": job.get("error"),
        })

        if job["status"] == "completed":
            transcript = job.get("transcript", "")
            segments = job.get("segments", [])
            st.subheader("Transcript")
            st.text_area("Final transcript", value=transcript, height=240)
            if transcript:
                st.download_button(
                    label="Download TXT",
                    data=transcript,
                    file_name=f"{job_id}.txt",
                    mime="text/plain",
                )
                st.download_button(
                    label="Download JSON",
                    data=json.dumps({"job_id": job_id, "language": job.get("language"), "transcript": transcript, "segments": segments}, indent=2),
                    file_name=f"{job_id}.json",
                    mime="application/json",
                )

            if segments:
                segments_df = pd.DataFrame(segments)
                st.subheader("Segment timestamps")
                st.dataframe(segments_df[["start", "end", "text"]], use_container_width=True)

        elif job["status"] == "failed":
            st.error(job.get("error", "The job failed without a detailed error."))

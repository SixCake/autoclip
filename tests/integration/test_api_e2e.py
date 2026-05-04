"""Integration test: FastAPI app via TestClient.

Coverage:
- GET /health returns 200 + version
- POST /api/jobs accepts multipart upload, persists Job + Video, dispatches subprocess
  (subprocess is mocked to avoid kicking off real pipeline)
- GET /api/jobs/{id} returns DB summary + state.json
- POST /api/jobs/{id}/cancel touches .cancel signal
- 404 on unknown job_id

We patch jobs.mp.Process to a no-op so file uploads don't trigger real pipelines.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from autoclip.config import Settings
from autoclip.main import create_app


@pytest.fixture()
def isolated_app(tmp_path: Path, monkeypatch):
    """Create a fresh FastAPI app with data_dir pointing at tmp_path."""

    # Force settings to use tmp_path as data_dir
    def fake_get_settings():
        s = Settings(data_dir=tmp_path)
        s.ensure_data_dir()
        return s

    monkeypatch.setattr("autoclip.main.get_settings", fake_get_settings)
    monkeypatch.setattr("autoclip.api.jobs.get_settings", fake_get_settings)

    # No-op subprocess so file uploads don't kick off a real pipeline
    fake_process_class = MagicMock()
    fake_process_instance = MagicMock()
    fake_process_instance.pid = 12345
    fake_process_class.return_value = fake_process_instance
    monkeypatch.setattr("autoclip.api.jobs.mp.Process", fake_process_class)

    app = create_app()
    with TestClient(app) as client:
        yield client, tmp_path, fake_process_class


def test_health_endpoint(isolated_app):
    client, _, _ = isolated_app
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_create_job_uploads_and_dispatches(isolated_app):
    client, tmp_path, fake_process_class = isolated_app

    fake_video_bytes = b"\x00\x01\x02fake-mp4-bytes" * 100  # ~1500 bytes
    files = {"file": ("sample.mp4", io.BytesIO(fake_video_bytes), "video/mp4")}
    data = {
        "target_duration_sec": "60",
        "style_preset": "plot_summary",
        "agreement_accepted": "true",
    }

    r = client.post("/api/jobs", files=files, data=data)
    assert r.status_code == 201, r.text

    body = r.json()
    assert body["status"] == "pending"
    assert body["size_bytes"] == len(fake_video_bytes)
    assert len(body["file_hash"]) == 64  # sha256 hex
    job_id = body["job_id"]

    # source.mp4 was written
    source_path = tmp_path / "jobs" / str(job_id) / "source.mp4"
    assert source_path.exists()
    assert source_path.read_bytes() == fake_video_bytes

    # state.json initialised
    state_path = tmp_path / "jobs" / str(job_id) / "state.json"
    assert state_path.exists()

    # Subprocess was kicked off (but our mock didn't actually run it)
    fake_process_class.assert_called_once()


def test_get_job_returns_db_and_state(isolated_app):
    client, tmp_path, _ = isolated_app

    # Create a job first
    files = {"file": ("v.mp4", io.BytesIO(b"data" * 50), "video/mp4")}
    data = {"target_duration_sec": "30", "agreement_accepted": "true"}
    create_resp = client.post("/api/jobs", files=files, data=data)
    job_id = create_resp.json()["job_id"]

    # Now GET it
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["id"] == job_id
    assert body["job"]["status"] == "pending"
    assert body["job"]["target_duration_sec"] == 30
    assert body["job"]["agreement_accepted_at"] is not None
    # state.json content present
    assert body["state"] is not None
    assert "stages" in body["state"]
    assert len(body["state"]["stages"]) == 5  # all 5 stages present


def test_get_job_404_on_unknown_id(isolated_app):
    client, _, _ = isolated_app
    r = client.get("/api/jobs/99999")
    assert r.status_code == 404


def test_list_jobs_returns_newest_first(isolated_app):
    client, _, _ = isolated_app

    # Create 3 jobs
    job_ids = []
    for i in range(3):
        files = {"file": (f"v{i}.mp4", io.BytesIO(b"x" * (10 + i)), "video/mp4")}
        data = {"target_duration_sec": str(20 + i), "agreement_accepted": "false"}
        resp = client.post("/api/jobs", files=files, data=data)
        job_ids.append(resp.json()["job_id"])

    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    # Newest first
    returned_ids = [item["id"] for item in body["items"]]
    assert returned_ids == list(reversed(job_ids))


def test_cancel_job_writes_cancel_signal(isolated_app):
    client, tmp_path, _ = isolated_app

    files = {"file": ("v.mp4", io.BytesIO(b"data"), "video/mp4")}
    data = {"target_duration_sec": "30", "agreement_accepted": "false"}
    job_id = client.post("/api/jobs", files=files, data=data).json()["job_id"]

    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 202
    assert r.json() == {"job_id": job_id, "cancelled": True}

    cancel_file = tmp_path / "jobs" / str(job_id) / ".cancel"
    assert cancel_file.exists()


def test_cancel_job_404_on_unknown_id(isolated_app):
    client, _, _ = isolated_app
    r = client.post("/api/jobs/99999/cancel")
    assert r.status_code == 404

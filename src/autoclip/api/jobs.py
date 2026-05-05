"""HTTP API for Job CRUD + cancel.

Endpoints:
- POST /api/jobs          — upload video + form params, dispatch pipeline subprocess
- GET  /api/jobs          — list all jobs (newest first)
- GET  /api/jobs/{id}     — return state.json content for one job
- POST /api/jobs/{id}/cancel — touch .cancel signal

Design notes (per M1.4 key-design):
- Uploaded file path is NOT stored in state.json (zero-knowledge §16.5);
  the convention is data/{job_id}/source.mp4
- Pipeline runs in a detached mp.Process(spawn) — API does not wait
- Agreement enforcement is M3.9 — here we just persist the field as nullable
"""

from __future__ import annotations

import hashlib
import logging
import multiprocessing as mp
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import Job, JobStatus, Video
from ..pipeline.runner import PipelineRunner
from ..pipeline.state import JobStateFile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming hash + write


# ---------------------------------------------------------------------------
# Subprocess entry for the WHOLE pipeline (started from POST /api/jobs)
# ---------------------------------------------------------------------------

def _run_pipeline_in_subprocess(job_dir_str: str) -> None:
    """Detached subprocess entry: drive PipelineRunner to completion.

    Module-level so it pickles cleanly under spawn. Runs in a fresh
    interpreter; failures are captured into state.json by the runner.
    """
    runner = PipelineRunner(Path(job_dir_str))
    try:
        runner.run(resume=True)
    except Exception:  # noqa: BLE001 — top-level subprocess: log and exit
        logger.exception("Pipeline subprocess crashed at job_dir=%s", job_dir_str)


# ---------------------------------------------------------------------------
# Dependency: session factory from app.state
# ---------------------------------------------------------------------------

def get_session_factory(request: Request) -> Any:
    """Return the SQLAlchemy session factory mounted on app.state."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database session factory not initialised",
        )
    return factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stream_save_and_hash(upload: UploadFile, dest: Path) -> tuple[str, int]:
    """Stream-write upload to dest while computing SHA-256. Returns (hash, size)."""
    hasher = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        while True:
            chunk = upload.file.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            f.write(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def _job_dir(job_id: int) -> Path:
    """Per-job working directory: data/{job_id}/."""
    return get_settings().data_dir / "jobs" / str(job_id)


# ---------------------------------------------------------------------------
# POST /api/jobs — upload + dispatch
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(  # noqa: PLR0913 — multipart form needs many params
    file: Annotated[UploadFile, File(description="Source video file")],
    target_duration_sec: Annotated[int, Form(ge=10, le=600)],
    style_preset: Annotated[str, Form()] = "plot_summary",
    agreement_accepted: Annotated[bool, Form()] = False,  # noqa: FBT002 — form field
    session_factory: Annotated[Any, Depends(get_session_factory)] = None,
) -> dict[str, Any]:
    """Create a new pipeline job and dispatch its subprocess."""
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file.filename missing")

    # M3.9: agreement must be accepted (K11 backend gate)
    if not agreement_accepted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户协议必须勾选同意才能创建任务")

    # M4.3: validate style_preset enum
    _VALID_STYLE_PRESETS = frozenset({"plot_summary", "humor_roast", "serious_review"})
    if style_preset not in _VALID_STYLE_PRESETS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"style_preset 不合法: {style_preset!r}，合法值: {sorted(_VALID_STYLE_PRESETS)}",
        )

    # Step 1: create Job record (we need its auto-id to know the job_dir)
    with session_scope(session_factory) as sess:
        job = Job(
            video_id=0,  # placeholder; updated after we know the Video
            target_duration_sec=target_duration_sec,
            style_preset=style_preset,
            status=JobStatus.PENDING,
            agreement_accepted_at=datetime.now(UTC) if agreement_accepted else None,
        )
        # Bootstrap with a temp Video so FK doesn't blow up on insert
        # (Real Video will be set after we hash the upload.)
        bootstrap_video = Video(
            filename_hash="pending",
            original_filename=file.filename,
            duration_sec=0.0,
        )
        sess.add(bootstrap_video)
        sess.flush()
        job.video_id = bootstrap_video.id
        sess.add(job)
        sess.flush()
        job_id = job.id
        bootstrap_video_id = bootstrap_video.id

    # Step 2: stream-save + hash the upload to data/{job_id}/source.mp4
    job_dir = _job_dir(job_id)
    source_path = job_dir / "source.mp4"
    file_hash, size_bytes = _stream_save_and_hash(file, source_path)

    # Step 3: dedup Video by hash (or update bootstrap if first sighting)
    with session_scope(session_factory) as sess:
        existing = sess.execute(
            select(Video).where(Video.filename_hash == file_hash)
        ).scalar_one_or_none()
        if existing is not None and existing.id != bootstrap_video_id:
            # Real Video already exists — point Job at it and drop bootstrap
            job_obj = sess.get(Job, job_id)
            job_obj.video_id = existing.id
            bootstrap = sess.get(Video, bootstrap_video_id)
            sess.delete(bootstrap)
            video_id = existing.id
        else:
            # First sighting — promote bootstrap to real Video
            bootstrap = sess.get(Video, bootstrap_video_id)
            bootstrap.filename_hash = file_hash
            # duration_sec stays 0.0 here; ingest stage will probe + update
            video_id = bootstrap_video_id

    # Step 4: initialise state.json
    state = JobStateFile(job_dir)
    state.init_state(
        job_id=job_id,
        video_hash=file_hash,
        target_duration_sec=target_duration_sec,
        style_preset=style_preset,
    )

    # Step 5: dispatch detached subprocess (don't join — fire and forget)
    proc = mp.Process(
        target=_run_pipeline_in_subprocess,
        args=(str(job_dir),),
        name=f"autoclip-pipeline-job-{job_id}",
        daemon=False,
    )
    proc.start()
    logger.info(
        "Job %d dispatched: video_id=%d hash=%s size=%d pid=%s",
        job_id, video_id, file_hash[:8], size_bytes, proc.pid,
    )

    return {
        "job_id": job_id,
        "video_id": video_id,
        "status": JobStatus.PENDING.value,
        "size_bytes": size_bytes,
        "file_hash": file_hash,
    }


# ---------------------------------------------------------------------------
# GET /api/jobs — list
# ---------------------------------------------------------------------------

@router.get("")
def list_jobs(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List jobs newest-first. Returns DB summary (NOT state.json detail)."""
    with session_scope(session_factory) as sess:
        rows = sess.execute(
            select(Job).order_by(Job.id.desc()).limit(limit).offset(offset)
        ).scalars().all()
        items = [
            {
                "id": j.id,
                "video_id": j.video_id,
                "target_duration_sec": j.target_duration_sec,
                "style_preset": j.style_preset,
                "status": j.status.value,
                "progress": j.progress,
                "created_at": j.created_at.isoformat(),
            }
            for j in rows
        ]
    return {"items": items, "limit": limit, "offset": offset, "count": len(items)}


# ---------------------------------------------------------------------------
# GET /api/jobs/{id} — state.json detail
# ---------------------------------------------------------------------------

@router.get("/{job_id}")
def get_job(
    job_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Return state.json content + DB row summary for one job."""
    with session_scope(session_factory) as sess:
        job = sess.get(Job, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")
        db_summary = {
            "id": job.id,
            "video_id": job.video_id,
            "target_duration_sec": job.target_duration_sec,
            "style_preset": job.style_preset,
            "status": job.status.value,
            "progress": job.progress,
            "regenerate_count": job.regenerate_count,
            "agreement_accepted_at": (
                job.agreement_accepted_at.isoformat() if job.agreement_accepted_at else None
            ),
        }

    state = JobStateFile(_job_dir(job_id))
    state_payload: dict[str, Any] | None = state.load() if state.exists() else None
    return {"job": db_summary, "state": state_payload}


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/cancel — touch .cancel
# ---------------------------------------------------------------------------

@router.post("/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_job(
    job_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Request cancellation by touching .cancel in the job dir."""
    with session_scope(session_factory) as sess:
        job = sess.get(Job, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")

    state = JobStateFile(_job_dir(job_id))
    if not state.exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job {job_id} has no state.json yet; nothing to cancel",
        )
    state.request_cancel()
    return {"job_id": job_id, "cancelled": True}


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/regenerate — M4.4 one-click regenerate
# ---------------------------------------------------------------------------

@router.post("/{job_id}/regenerate", status_code=status.HTTP_202_ACCEPTED)
def regenerate_job(
    job_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Reset script/assembly/render stages and rerun pipeline from SCRIPT.

    Limits: max 3 regenerations per job (K4 cost control).
    Does NOT re-run ingest/index — reuses shots.json + asr.json.
    """
    import shutil

    with session_scope(session_factory) as sess:
        job = sess.get(Job, job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} not found")
        if job.regenerate_count >= 3:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Job {job_id} has reached the maximum of 3 regenerations",
            )
        job.regenerate_count += 1

    job_dir = _job_dir(job_id)
    state = JobStateFile(job_dir)
    if not state.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id} state.json not found")

    # Delete downstream artifacts so pipeline rebuilds them
    for artifact in ("timeline.json", "assembly.json", "self_evaluation.json"):
        artifact_path = job_dir / artifact
        if artifact_path.exists():
            artifact_path.unlink()

    output_dir = job_dir / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Reset SCRIPT/ASSEMBLY/RENDER stages to PENDING in state.json
    from ..pipeline.state import Stage, StageState, StageStatus
    current = state.load()
    for stage_name in (Stage.SCRIPT.value, Stage.ASSEMBLY.value, Stage.RENDER.value):
        current["stages"][stage_name] = StageState().to_dict()
    state._save_atomic(current)  # noqa: SLF001

    # Dispatch new subprocess — PipelineRunner will skip DONE ingest/index
    proc = mp.Process(
        target=_run_pipeline_in_subprocess,
        args=(str(job_dir),),
        name=f"autoclip-regen-job-{job_id}",
        daemon=False,
    )
    proc.start()
    logger.info("Job %d regeneration dispatched (count=%d)", job_id, job.regenerate_count)

    return {"job_id": job_id, "regenerate_count": job.regenerate_count, "status": "regenerating"}


# ---------------------------------------------------------------------------
# GET /api/jobs/{id}/download/{filename} — download output zip
# ---------------------------------------------------------------------------

@router.get("/{job_id}/download/{filename}")
def download_output(
    job_id: int,
    filename: str,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> Any:
    """Download an output zip from the job's output/ directory."""
    from fastapi.responses import FileResponse

    output_path = _job_dir(job_id) / "output" / filename
    if not output_path.exists() or not output_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File {filename} not found for job {job_id}")
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/zip",
    )

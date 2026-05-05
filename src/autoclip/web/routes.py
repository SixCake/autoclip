"""Web UI routes — Jinja2 template pages for AutoClip."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..db import session_scope
from ..models import Job, JobStatus
from sqlalchemy import select

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def get_session_factory(request: Request) -> Any:
    factory = getattr(request.app.state, "session_factory", None)
    return factory


def _job_dir(job_id: int) -> Path:
    return get_settings().data_dir / "jobs" / str(job_id)


@router.get("/", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    """Upload page — main entry point."""
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(
    request: Request,
    session_factory: Annotated[Any, Depends(get_session_factory)] = None,
) -> HTMLResponse:
    """Jobs list page."""
    jobs: list[dict] = []
    if session_factory:
        with session_scope(session_factory) as sess:
            rows = sess.execute(
                select(Job).order_by(Job.id.desc()).limit(50)
            ).scalars().all()
            jobs = [
                {
                    "id": j.id,
                    "target_duration_sec": j.target_duration_sec,
                    "style_preset": j.style_preset,
                    "status": j.status.value,
                    "progress": j.progress,
                    "created_at": j.created_at.isoformat() if j.created_at else "",
                }
                for j in rows
            ]
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail_page(
    request: Request,
    job_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)] = None,
) -> HTMLResponse:
    """Job detail + progress page."""
    job_data: dict | None = None
    state_data: dict | None = None

    if session_factory:
        with session_scope(session_factory) as sess:
            job = sess.get(Job, job_id)
            if job:
                job_data = {
                    "id": job.id,
                    "target_duration_sec": job.target_duration_sec,
                    "style_preset": job.style_preset,
                    "status": job.status.value,
                    "progress": job.progress,
                    "regenerate_count": job.regenerate_count,
                }

    from ..pipeline.state import JobStateFile
    state_file = JobStateFile(_job_dir(job_id))
    if state_file.exists():
        state_data = state_file.load()

    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job_data, "state": state_data, "job_id": job_id},
    )


@router.get("/jobs/{job_id}/result", response_class=HTMLResponse)
def job_result_page(
    request: Request,
    job_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)] = None,
) -> HTMLResponse:
    """Job result download page."""
    job_data: dict | None = None
    downloads: list[dict] = []
    self_eval: dict | None = None

    if session_factory:
        with session_scope(session_factory) as sess:
            job = sess.get(Job, job_id)
            if job:
                job_data = {
                    "id": job.id,
                    "status": job.status.value,
                    "regenerate_count": job.regenerate_count,
                }

    output_dir = _job_dir(job_id) / "output"
    if output_dir.exists():
        for zip_file in output_dir.glob("*.zip"):
            downloads.append({
                "name": zip_file.name,
                "url": f"/api/jobs/{job_id}/download/{zip_file.name}",
                "size_mb": round(zip_file.stat().st_size / 1024 / 1024, 2),
            })

    eval_path = _job_dir(job_id) / "self_evaluation.json"
    if eval_path.exists():
        try:
            self_eval = json.loads(eval_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "job": job_data,
            "job_id": job_id,
            "downloads": downloads,
            "self_eval": self_eval,
        },
    )


@router.get("/agreement", response_class=HTMLResponse)
def agreement_page(request: Request) -> HTMLResponse:
    """Full user agreement page."""
    import markdown as md
    agreement_path = Path("docs/legal/user-agreement-v0.1.md")
    if agreement_path.exists():
        content_html = md.markdown(agreement_path.read_text(encoding="utf-8"))
    else:
        content_html = "<p>用户协议文件未找到。</p>"
    return templates.TemplateResponse(
        "agreement.html", {"request": request, "content_html": content_html}
    )

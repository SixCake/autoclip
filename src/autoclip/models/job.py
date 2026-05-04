"""Job model — tracks one user pipeline submission through 5 stages."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class JobStatus(str, enum.Enum):
    """Top-level job lifecycle status (orthogonal to per-stage status)."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    target_duration_sec: Mapped[int] = mapped_column(nullable=False)
    style_preset: Mapped[str] = mapped_column(String(64), default="plot_summary", nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status_enum"),
        default=JobStatus.PENDING,
        nullable=False,
    )
    progress: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Reserved for M3.9 (user agreement enforcement)
    agreement_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Reserved for M4.4 (regenerate count limit)
    regenerate_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Relationships
    video: Mapped["Video"] = relationship(back_populates="jobs")  # noqa: F821
    timeline: Mapped["Timeline | None"] = relationship(  # noqa: F821
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} video_id={self.video_id} status={self.status.value}>"

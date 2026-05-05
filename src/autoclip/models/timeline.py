"""Timeline / NarrationSentence / TimelineSegment models.

TimelineSegment is the unified intermediate layer per design.md §17.4 —
it carries BOTH source time (in original video) AND target time (in final cut),
mapping 1:1 to pyJianYingDraft's source_timerange / target_timerange.
"""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .shot import Shot


class BindingMethod(str, enum.Enum):
    """How a TimelineSegment's time was determined."""

    HINT_UNIFORM = "hint_uniform"  # M2a baseline: uniform split within paragraph hint window
    EVIDENCE = "evidence"  # M2b: high-confidence keyword match
    EVIDENCE_LOWCONFIDENCE = "evidence_lowconfidence"  # M2b: matched but conf < threshold
    FALLBACK_UNIFORM = "fallback_uniform"  # M2b when resolve returns None (fall back to paragraph hint)


class Timeline(Base):
    """One generated narration timeline for a Job (1:1 with Job)."""

    __tablename__ = "timelines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, unique=True, index=True
    )
    total_duration_sec: Mapped[float] = mapped_column(nullable=False)

    # Reserved for M2b.5 (binder version tracking)
    binder_version: Mapped[str] = mapped_column(String(32), default="v1-naive", nullable=False)

    # Relationships
    job: Mapped["Job"] = relationship(back_populates="timeline")  # noqa: F821
    sentences: Mapped[list["NarrationSentence"]] = relationship(
        back_populates="timeline",
        cascade="all, delete-orphan",
        order_by="NarrationSentence.order_idx",
    )
    segments: Mapped[list["TimelineSegment"]] = relationship(
        back_populates="timeline",
        cascade="all, delete-orphan",
        order_by="TimelineSegment.order",
    )


class NarrationSentence(Base):
    """One sentence of generated narration script."""

    __tablename__ = "narration_sentences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("timelines.id"), nullable=False, index=True
    )
    order_idx: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON list[str]: keywords for reverse ASR lookup (M2a.3 / M2b.2)
    evidence_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    paragraph_idx: Mapped[int] = mapped_column(nullable=False)

    timeline: Mapped["Timeline"] = relationship(back_populates="sentences")
    segments: Mapped[list["TimelineSegment"]] = relationship(
        back_populates="sentence",
        cascade="all, delete-orphan",
        order_by="TimelineSegment.order",
    )


class TimelineSegment(Base):
    """Unified intermediate layer carrying source AND target time (design.md §17.4).

    Maps 1:1 to pyJianYingDraft's VideoSegment(source_timerange, target_timerange)
    and JsonTimelineExporter equivalents. NO conversion layer needed downstream.
    """

    __tablename__ = "timeline_segments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timeline_id: Mapped[int] = mapped_column(
        ForeignKey("timelines.id"), nullable=False, index=True
    )
    sentence_id: Mapped[int] = mapped_column(
        ForeignKey("narration_sentences.id"), nullable=False, index=True
    )
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id"), nullable=False, index=True)

    # Order within parent sentence (NOT global order)
    order: Mapped[int] = mapped_column(nullable=False)

    # === Source time (in original video) ===
    source_start_sec: Mapped[float] = mapped_column(nullable=False)
    source_end_sec: Mapped[float] = mapped_column(nullable=False)

    # === Target time (in final timeline) ===
    target_start_sec: Mapped[float] = mapped_column(nullable=False)
    target_end_sec: Mapped[float] = mapped_column(nullable=False)

    # Invariant: source_end - source_start == target_end - target_start == duration_sec
    duration_sec: Mapped[float] = mapped_column(nullable=False)

    # Why this shot was picked (LLM rationale, optional)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Original audio volume during this segment (M3-b strategy: 0.15 default)
    use_original_audio_volume: Mapped[float] = mapped_column(default=0.15, nullable=False)

    # How this segment's time was resolved
    binding_method: Mapped[BindingMethod] = mapped_column(
        SAEnum(BindingMethod, name="binding_method_enum"),
        default=BindingMethod.FALLBACK_UNIFORM,
        nullable=False,
    )

    # Relationships
    timeline: Mapped["Timeline"] = relationship(back_populates="segments")
    sentence: Mapped["NarrationSentence"] = relationship(back_populates="segments")
    shot: Mapped["Shot"] = relationship()  # one-way; Shot doesn't need back ref

    def __repr__(self) -> str:
        return (
            f"<TimelineSegment id={self.id} sentence={self.sentence_id} shot={self.shot_id} "
            f"src=[{self.source_start_sec:.2f}-{self.source_end_sec:.2f}] "
            f"tgt=[{self.target_start_sec:.2f}-{self.target_end_sec:.2f}] "
            f"method={self.binding_method.value}>"
        )

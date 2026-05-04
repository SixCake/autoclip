"""Video model — zero-knowledge: stores only filename hash, not absolute path.

Reference: design.md §16.5 (zero-knowledge architecture).
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # K10: only hash, never absolute path
    filename_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_sec: Mapped[float] = mapped_column(nullable=False)

    # Relationships
    jobs: Mapped[list["Job"]] = relationship(  # noqa: F821
        back_populates="video",
        cascade="all, delete-orphan",
    )
    shots: Mapped[list["Shot"]] = relationship(  # noqa: F821
        back_populates="video",
        cascade="all, delete-orphan",
    )
    asr_sentences: Mapped[list["ASRSentence"]] = relationship(  # noqa: F821
        back_populates="video",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Video id={self.id} hash={self.filename_hash[:8]}... duration={self.duration_sec}s>"

"""Shot and ASRSentence models — products of Index stage."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Shot(Base):
    """A continuous shot detected by PySceneDetect."""

    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    order_idx: Mapped[int] = mapped_column(nullable=False)
    start_sec: Mapped[float] = mapped_column(nullable=False)
    end_sec: Mapped[float] = mapped_column(nullable=False)

    video: Mapped["Video"] = relationship(back_populates="shots")  # noqa: F821

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def __repr__(self) -> str:
        return (
            f"<Shot id={self.id} video_id={self.video_id} "
            f"order={self.order_idx} [{self.start_sec:.2f}-{self.end_sec:.2f}]s>"
        )


class ASRSentence(Base):
    """One ASR-recognized sentence with timing."""

    __tablename__ = "asr_sentences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    order_idx: Mapped[int] = mapped_column(nullable=False)
    start_sec: Mapped[float] = mapped_column(nullable=False)
    end_sec: Mapped[float] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(32), nullable=True)

    video: Mapped["Video"] = relationship(back_populates="asr_sentences")  # noqa: F821

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def __repr__(self) -> str:
        return (
            f"<ASRSentence id={self.id} order={self.order_idx} "
            f"text={self.text[:20]!r}...>"
        )

"""Narrative IR data models for Scripting stage (M2a.2 + M2a.3).

Defines:
    Character: Structured role card inferred from dialogue context.
    KeyAct: One key plot act with time window and involved characters.
    PlotOutline: Aggregated outline with title_guess, genre, main_characters, key_acts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# === Pydantic raw models for strict LLM output validation ===

class _CharacterRaw(BaseModel):
    """Pydantic model for validating LLM output of a single character."""
    role: str = Field(..., description="Functional role label like '男主'/'女主'/'反派A'")
    name: str | None = Field(None, description="Explicit name if mentioned in dialogue, else null")
    description: str = Field(..., description="One-sentence character portrait")


class _KeyActRaw(BaseModel):
    """Pydantic model for validating LLM output of a single key act."""
    act_idx: int = Field(..., ge=1, le=5, description="Act index 1-5")
    name: str = Field(..., description="Short act name like '开场冲突'")
    approx_start_sec: float = Field(..., ge=0, description="Approximate start time in seconds")
    approx_end_sec: float = Field(..., ge=0, description="Approximate end time in seconds")
    summary: str = Field(..., description="Brief summary of what happens in this act")
    involved_characters: list[str] = Field(default_factory=list, description="List of Character.role values appearing in this act")


class _PlotOutlineRaw(BaseModel):
    """Pydantic model for validating full LLM output of plot outline."""
    title_guess: str = Field(..., description="Guessed video title")
    genre: str = Field(..., description="Video genre like '喜剧'/'动作'/'悬疑'")
    main_characters: list[_CharacterRaw] = Field(default_factory=list, description="2-6 main characters")
    plot_summary: str = Field(..., description="Overall plot summary in 3-5 sentences")
    key_acts: list[_KeyActRaw] = Field(..., min_length=3, max_length=5, description="3-5 key acts")


# === Dataclass models for business logic ===

@dataclass(frozen=True)
class Character:
    """Structured character card inferred from dialogue context."""
    role: str
    name: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KeyAct:
    """One key plot act with approximate time window."""
    act_idx: int
    name: str
    approx_start_sec: float
    approx_end_sec: float
    summary: str
    involved_characters: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.act_idx < 1 or self.act_idx > 5:
            raise ValueError(f"act_idx must be 1-5, got {self.act_idx}")
        if self.approx_start_sec < 0:
            raise ValueError(f"approx_start_sec must be non-negative, got {self.approx_start_sec}")
        if self.approx_end_sec < self.approx_start_sec:
            raise ValueError(f"approx_end_sec ({self.approx_end_sec}) must be >= approx_start_sec ({self.approx_start_sec})")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlotOutline:
    """Aggregated plot outline with characters and key acts."""
    title_guess: str
    genre: str
    main_characters: list[Character] = field(default_factory=list)
    plot_summary: str = ""
    key_acts: list[KeyAct] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_guess": self.title_guess,
            "genre": self.genre,
            "main_characters": [c.to_dict() for c in self.main_characters],
            "plot_summary": self.plot_summary,
            "key_acts": [a.to_dict() for a in self.key_acts],
        }

"""Tests for autoclip.models — ORM schema integrity + relationship correctness.

Covers M1.2 acceptance:
- 6 models can create_all without errors
- Video → Job FK + back_populates works
- TimelineSegment carries source AND target time (design.md §17.4)
- evidence_keywords JSON list serializes round-trip via SQLite
- Shot.duration_sec computed property
- BindingMethod enum default = FALLBACK_UNIFORM
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from autoclip.db import (
    create_memory_engine,
    drop_all,
    init_db,
    make_session_factory,
)
from autoclip.models import (
    ASRSentence,
    Base,
    BindingMethod,
    Job,
    JobStatus,
    NarrationSentence,
    Shot,
    Timeline,
    TimelineSegment,
    Video,
)


@pytest.fixture()
def session() -> Session:
    """Provide a clean in-memory SQLite session per test."""
    engine = create_memory_engine()
    init_db(engine)
    factory = make_session_factory(engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        drop_all(engine)
        engine.dispose()


def test_metadata_creates_all_tables() -> None:
    """All 7 tables (videos, jobs, shots, asr_sentences, timelines,
    narration_sentences, timeline_segments) must be discoverable."""
    expected = {
        "videos",
        "jobs",
        "shots",
        "asr_sentences",
        "timelines",
        "narration_sentences",
        "timeline_segments",
    }
    actual = set(Base.metadata.tables.keys())
    assert expected.issubset(actual), f"Missing tables: {expected - actual}"


def test_video_job_relationship(session: Session) -> None:
    """Video → Job back_populates works; cascade delete works."""
    v = Video(filename_hash="a" * 64, original_filename="movie.mp4", duration_sec=5400.0)
    j1 = Job(target_duration_sec=60, style_preset="plot_summary")
    j2 = Job(target_duration_sec=180, style_preset="humor_roast")
    v.jobs.extend([j1, j2])
    session.add(v)
    session.commit()

    # Relationship works
    fetched = session.query(Video).filter_by(filename_hash="a" * 64).one()
    assert len(fetched.jobs) == 2
    assert {j.target_duration_sec for j in fetched.jobs} == {60, 180}
    assert fetched.jobs[0].status == JobStatus.PENDING  # default
    assert fetched.jobs[0].progress == 0.0  # default

    # Cascade delete: deleting Video removes its Jobs
    session.delete(fetched)
    session.commit()
    assert session.query(Job).count() == 0


def test_timeline_segment_carries_dual_time(session: Session) -> None:
    """TimelineSegment must carry BOTH source AND target time (design.md §17.4)."""
    v = Video(filename_hash="b" * 64, original_filename="x.mp4", duration_sec=600.0)
    j = Job(target_duration_sec=90)
    v.jobs.append(j)
    shot = Shot(order_idx=0, start_sec=10.0, end_sec=15.5)
    v.shots.append(shot)
    session.add(v)
    session.commit()

    timeline = Timeline(job_id=j.id, total_duration_sec=90.0)
    sentence = NarrationSentence(
        order_idx=0,
        text="主角推开了门",
        evidence_keywords=["推门", "主角"],
        paragraph_idx=0,
    )
    timeline.sentences.append(sentence)
    session.add(timeline)
    session.commit()

    seg = TimelineSegment(
        timeline_id=timeline.id,
        sentence_id=sentence.id,
        shot_id=shot.id,
        order=0,
        # Source time differs from target time — that's the whole point
        source_start_sec=10.0,
        source_end_sec=15.5,
        target_start_sec=0.0,
        target_end_sec=5.5,
        duration_sec=5.5,
        rationale="LLM picked this shot for door-opening visual",
    )
    session.add(seg)
    session.commit()

    fetched = session.query(TimelineSegment).one()
    # Both source AND target times preserved
    assert fetched.source_start_sec == 10.0
    assert fetched.source_end_sec == 15.5
    assert fetched.target_start_sec == 0.0
    assert fetched.target_end_sec == 5.5
    # Defaults
    assert fetched.use_original_audio_volume == 0.15
    assert fetched.binding_method == BindingMethod.FALLBACK_UNIFORM
    # Invariant: durations match
    assert (fetched.source_end_sec - fetched.source_start_sec) == fetched.duration_sec
    assert (fetched.target_end_sec - fetched.target_start_sec) == fetched.duration_sec


def test_evidence_keywords_json_roundtrip(session: Session) -> None:
    """NarrationSentence.evidence_keywords (JSON list[str]) survives DB roundtrip."""
    v = Video(filename_hash="c" * 64, original_filename="y.mp4", duration_sec=300.0)
    j = Job(target_duration_sec=60)
    v.jobs.append(j)
    session.add(v)
    session.commit()
    timeline = Timeline(job_id=j.id, total_duration_sec=60.0)
    session.add(timeline)
    session.commit()

    keywords = ["电话", "喂", "你好", "中文混合English"]
    sentence = NarrationSentence(
        timeline_id=timeline.id,
        order_idx=0,
        text="他接起了电话",
        evidence_keywords=keywords,
        paragraph_idx=2,
    )
    session.add(sentence)
    session.commit()
    session.expire_all()  # force reload from DB

    fetched = session.query(NarrationSentence).one()
    assert fetched.evidence_keywords == keywords
    assert isinstance(fetched.evidence_keywords, list)


def test_shot_duration_sec_computed() -> None:
    """Shot.duration_sec is a derived @property (no DB column)."""
    shot = Shot(order_idx=0, start_sec=12.5, end_sec=20.0)
    assert shot.duration_sec == 7.5


def test_asr_sentence_basic(session: Session) -> None:
    """ASRSentence basic CRUD + duration_sec property."""
    v = Video(filename_hash="d" * 64, original_filename="z.mp4", duration_sec=120.0)
    asr = ASRSentence(
        order_idx=0, start_sec=1.5, end_sec=4.0, text="测试句子", speaker="speaker_0"
    )
    v.asr_sentences.append(asr)
    session.add(v)
    session.commit()

    fetched = session.query(ASRSentence).one()
    assert fetched.text == "测试句子"
    assert fetched.duration_sec == 2.5
    assert fetched.speaker == "speaker_0"


def test_timeline_unique_per_job(session: Session) -> None:
    """One Job has at most one Timeline (uselist=False)."""
    v = Video(filename_hash="e" * 64, original_filename="w.mp4", duration_sec=300.0)
    j = Job(target_duration_sec=60)
    v.jobs.append(j)
    session.add(v)
    session.commit()

    timeline = Timeline(job_id=j.id, total_duration_sec=60.0)
    session.add(timeline)
    session.commit()

    session.refresh(j)
    assert j.timeline is not None
    assert j.timeline.binder_version == "v1-naive"  # default

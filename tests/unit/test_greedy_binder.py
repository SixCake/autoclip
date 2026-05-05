"""Unit tests for greedy_binder (M2a.5)."""

import pytest

from autoclip.algo.greedy_binder import (
    DEFAULT_MIN_SEGMENT_SEC,
    BindingResult,
    BoundSegment,
    bind_naively,
)
from autoclip.algo.narrative_ir import NarrativeIR, NarrativeParagraph, NarrativeSentence
from autoclip.algo.shot_detector import Shot
from autoclip.models.timeline import BindingMethod


def _mk_shots(boundaries: list[tuple[float, float]]) -> list[Shot]:
    """Helper: build list[Shot] with sequential idx from (start,end) tuples."""
    return [Shot(idx=i, start_sec=s, end_sec=e) for i, (s, e) in enumerate(boundaries)]


def _mk_para(idx: int, start: float, end: float, n_sent: int) -> NarrativeParagraph:
    """Helper: build NarrativeParagraph with N trivial sentences."""
    return NarrativeParagraph(
        paragraph_idx=idx,
        topic=f"para{idx}",
        approx_source_start_sec=start,
        approx_source_end_sec=end,
        sentences=[
            NarrativeSentence(sentence_idx=i + 1, text=f"sent{i+1}", evidence_keywords=[])
            for i in range(n_sent)
        ],
    )


class TestUniformSplit:
    """Test uniform splitting of paragraph windows."""

    def test_paragraph_10_to_40_three_sentences_each_10s(self):
        """Paragraph [10, 40] with 3 sentences -> [10,20] [20,30] [30,40]."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 10.0, 40.0, 3)])
        shots = _mk_shots([(0, 60)])
        result = bind_naively(ir, shots)

        assert len(result.segments) == 3
        windows = [(s.source_start_sec, s.source_end_sec) for s in result.segments]
        assert windows == [(10.0, 20.0), (20.0, 30.0), (30.0, 40.0)]

    def test_single_sentence_takes_whole_paragraph(self):
        ir = NarrativeIR(paragraphs=[_mk_para(1, 5.0, 25.0, 1)])
        shots = _mk_shots([(0, 30)])
        result = bind_naively(ir, shots)
        assert len(result.segments) == 1
        assert result.segments[0].source_start_sec == 5.0
        assert result.segments[0].source_end_sec == 25.0


class TestParagraphClamp:
    """Test paragraph window clamping when exceeding video bounds."""

    def test_paragraph_end_exceeds_video_clamped(self):
        """Paragraph [50, 200] with video_end=100 -> clamped to [50, 100]."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 50.0, 200.0, 2)])
        shots = _mk_shots([(0, 100)])  # video_end = 100
        result = bind_naively(ir, shots)

        assert len(result.segments) == 2
        # Each sentence gets 25s window
        assert result.segments[0].source_start_sec == 50.0
        assert result.segments[0].source_end_sec == 75.0
        assert result.segments[1].source_start_sec == 75.0
        assert result.segments[1].source_end_sec == 100.0

    def test_paragraph_window_within_video_bounds_no_clamp(self):
        """Sanity check: when window fully inside [0, video_end], no clamping."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 5.0, 25.0, 2)])
        shots = _mk_shots([(0, 60)])
        result = bind_naively(ir, shots)
        # 2 sentences in [5, 25] -> [5, 15] and [15, 25]
        assert result.segments[0].source_start_sec == 5.0
        assert result.segments[0].source_end_sec == 15.0
        assert result.segments[1].source_start_sec == 15.0
        assert result.segments[1].source_end_sec == 25.0


class TestMinSegmentExpansion:
    """Test the min_segment_sec expansion logic."""

    def test_segment_below_min_expanded_within_paragraph(self):
        """Paragraph [10, 11.2] with 3 sentences: each 0.4s < 0.8 default -> expand."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 10.0, 11.2, 3)])
        shots = _mk_shots([(0, 30)])
        result = bind_naively(ir, shots)

        # Each segment should be expanded to at least min_segment_sec (0.8),
        # but bounded by parent paragraph [10.0, 11.2]
        for seg in result.segments:
            # Either reaches min_segment_sec OR is bounded by parent paragraph width
            assert seg.duration_sec >= min(DEFAULT_MIN_SEGMENT_SEC, 1.2) or \
                   seg.duration_sec == pytest.approx(1.2, abs=0.01)

    def test_custom_min_segment_sec_respected(self):
        """min_segment_sec=2.0 should produce segments >= 2s when room allows."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 0.0, 30.0, 5)])  # each = 6s naturally
        shots = _mk_shots([(0, 60)])
        result = bind_naively(ir, shots, min_segment_sec=2.0)

        for seg in result.segments:
            assert seg.duration_sec >= 2.0

    def test_invalid_min_segment_sec_raises(self):
        ir = NarrativeIR(paragraphs=[_mk_para(1, 0.0, 10.0, 1)])
        shots = _mk_shots([(0, 20)])
        with pytest.raises(ValueError, match="min_segment_sec must be positive"):
            bind_naively(ir, shots, min_segment_sec=0)
        with pytest.raises(ValueError, match="min_segment_sec must be positive"):
            bind_naively(ir, shots, min_segment_sec=-1)


class TestShotOverlapMatching:
    """Test that overlapping shots are correctly attached."""

    def test_segment_overlapping_two_shots(self):
        """Segment [10, 20] overlaps shots [0,15] and [15,30] -> both ids."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 10.0, 20.0, 1)])
        shots = _mk_shots([(0, 15), (15, 30)])
        result = bind_naively(ir, shots)
        assert sorted(result.segments[0].source_shot_ids) == [0, 1]

    def test_segment_overlapping_single_shot(self):
        """Segment [5, 10] entirely inside shot 0 [0, 15]."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 5.0, 10.0, 1)])
        shots = _mk_shots([(0, 15), (15, 30)])
        result = bind_naively(ir, shots)
        assert result.segments[0].source_shot_ids == [0]

    def test_three_sentences_three_shots_one_each(self):
        """[10,40] / 3 sentences each ~10s, shot boundaries align."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 10.0, 40.0, 3)])
        shots = _mk_shots([(10, 20), (20, 30), (30, 40)])
        result = bind_naively(ir, shots)
        # Note: Python's strict inequality (s.start < seg_end and s.end > seg_start)
        # means boundary-touching shots WON'T overlap. Each sentence picks exactly 1.
        assert result.segments[0].source_shot_ids == [0]
        assert result.segments[1].source_shot_ids == [1]
        assert result.segments[2].source_shot_ids == [2]


class TestExtremeFallback:
    """Test the nearest-shot fallback when no overlap exists."""

    def test_no_overlap_falls_back_to_nearest_shot(self):
        """Segment [50, 60] with shots only at [0,10] [100,110] -> nearest [0,10]."""
        # Construct a paragraph that lands in a gap (impossible with PySceneDetect
        # output but tests the safety net)
        ir = NarrativeIR(paragraphs=[_mk_para(1, 50.0, 60.0, 1)])
        # Manually construct shots with a big gap
        shots = [
            Shot(idx=0, start_sec=0.0, end_sec=10.0),
            Shot(idx=1, start_sec=100.0, end_sec=110.0),
        ]
        result = bind_naively(ir, shots)
        # Segment center = 55, distance to shot 0 (start=0) is 55, to shot 1 (start=100) is 45
        # So nearest by start_sec is shot 1
        assert result.segments[0].source_shot_ids == [1]

    def test_empty_shots_returns_empty_result(self):
        ir = NarrativeIR(paragraphs=[_mk_para(1, 0.0, 10.0, 2)])
        result = bind_naively(ir, [])
        assert result.segments == []
        assert result.fallback_count == 0
        assert result.total_count == 0
        assert result.fallback_ratio == 0.0


class TestBindingResultProperties:
    """Test BindingResult.fallback_ratio and total_count properties."""

    def test_fallback_ratio_zero_for_m2a_baseline(self):
        """M2a baseline always uses HINT_UNIFORM, fallback_count = 0."""
        ir = NarrativeIR(paragraphs=[_mk_para(1, 0.0, 30.0, 3)])
        shots = _mk_shots([(0, 30)])
        result = bind_naively(ir, shots)
        assert result.fallback_count == 0
        assert result.total_count == 3
        assert result.fallback_ratio == 0.0

    def test_fallback_ratio_empty_does_not_raise(self):
        """Division-by-zero guard: empty result -> ratio = 0.0."""
        result = BindingResult(segments=[], fallback_count=0)
        assert result.fallback_ratio == 0.0
        assert result.total_count == 0

    def test_fallback_ratio_with_synthetic_count(self):
        """Synthetic test: 2 fallback / 5 total = 0.4."""
        segs = [
            BoundSegment(
                paragraph_idx=1, sentence_idx=i, sentence_text=f"s{i}",
                source_start_sec=float(i), source_end_sec=float(i + 1),
                source_shot_ids=[0],
            )
            for i in range(5)
        ]
        result = BindingResult(segments=segs, fallback_count=2)
        assert result.fallback_ratio == pytest.approx(0.4)
        assert result.total_count == 5


class TestBindingMethodAlwaysHintUniform:
    """Verify M2a baseline only writes BindingMethod.HINT_UNIFORM."""

    def test_all_segments_use_hint_uniform(self):
        ir = NarrativeIR(paragraphs=[
            _mk_para(1, 0.0, 10.0, 2),
            _mk_para(2, 10.0, 20.0, 3),
        ])
        shots = _mk_shots([(0, 20)])
        result = bind_naively(ir, shots)
        assert all(s.binding_method == BindingMethod.HINT_UNIFORM for s in result.segments)


class TestSerialization:
    """Test to_dict() serialization for both BoundSegment and BindingResult."""

    def test_bound_segment_to_dict(self):
        seg = BoundSegment(
            paragraph_idx=1, sentence_idx=2, sentence_text="hello",
            source_start_sec=1.0, source_end_sec=3.5, source_shot_ids=[0, 1, 2],
        )
        d = seg.to_dict()
        assert d == {
            "paragraph_idx": 1,
            "sentence_idx": 2,
            "sentence_text": "hello",
            "source_start_sec": 1.0,
            "source_end_sec": 3.5,
            "source_shot_ids": [0, 1, 2],
            "binding_method": "hint_uniform",
        }

    def test_binding_result_to_dict_includes_ratio(self):
        ir = NarrativeIR(paragraphs=[_mk_para(1, 0.0, 10.0, 2)])
        shots = _mk_shots([(0, 10)])
        result = bind_naively(ir, shots)
        d = result.to_dict()
        assert d["total_count"] == 2
        assert d["fallback_count"] == 0
        assert d["fallback_ratio"] == 0.0
        assert len(d["segments"]) == 2


class TestMultiParagraph:
    """Test that multiple paragraphs are processed independently in order."""

    def test_two_paragraphs_segments_in_order(self):
        ir = NarrativeIR(paragraphs=[
            _mk_para(1, 0.0, 10.0, 2),
            _mk_para(2, 10.0, 30.0, 3),
        ])
        shots = _mk_shots([(0, 30)])
        result = bind_naively(ir, shots)

        assert len(result.segments) == 5
        # Para 1: 2 sentences in [0,10]
        assert result.segments[0].paragraph_idx == 1
        assert result.segments[1].paragraph_idx == 1
        # Para 2: 3 sentences in [10,30]
        assert result.segments[2].paragraph_idx == 2
        assert result.segments[3].paragraph_idx == 2
        assert result.segments[4].paragraph_idx == 2

    def test_empty_paragraph_skipped(self):
        """Paragraph with zero sentences should be silently skipped."""
        para_empty = NarrativeParagraph(
            paragraph_idx=1, topic="empty",
            approx_source_start_sec=0.0, approx_source_end_sec=10.0,
            sentences=[],
        )
        para_normal = _mk_para(2, 10.0, 20.0, 2)
        ir = NarrativeIR(paragraphs=[para_empty, para_normal])
        shots = _mk_shots([(0, 20)])
        result = bind_naively(ir, shots)
        assert len(result.segments) == 2
        assert all(s.paragraph_idx == 2 for s in result.segments)

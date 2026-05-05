"""Unit tests for NarrativeIR parsing (M2a.3).

Covers:
- Valid IR parsing from LLM JSON response
- Schema error handling (invalid JSON / missing fields)
- iter_sentences() flattening logic
"""

import pytest

from autoclip.algo.narrative_ir import NarrativeIR, NarrativeParagraph, NarrativeSentence
from autoclip.prompts.narrative_ir import parse_narrative_ir_response


class TestParseNarrativeIRValid:
    """Test valid NarrativeIR parsing."""

    def test_parse_valid_narrative_ir(self):
        """Parse a valid NarrativeIR JSON response."""
        raw_json = """
        {
          "paragraphs": [
            {
              "paragraph_idx": 1,
              "topic": "开场冲突",
              "approx_source_start_sec": 0.0,
              "approx_source_end_sec": 30.5,
              "sentences": [
                {
                  "sentence_idx": 1,
                  "text": "男主在街头遭遇反派伏击。",
                  "evidence_keywords": ["男主", "街头", "伏击"]
                },
                {
                  "sentence_idx": 2,
                  "text": "女主及时出现解围。",
                  "evidence_keywords": ["女主", "解围"]
                }
              ]
            },
            {
              "paragraph_idx": 2,
              "topic": "反转揭秘",
              "approx_source_start_sec": 30.5,
              "approx_source_end_sec": 60.0,
              "sentences": [
                {
                  "sentence_idx": 3,
                  "text": "原来反派是男主的旧友。",
                  "evidence_keywords": ["反派", "旧友"]
                }
              ]
            }
          ]
        }
        """
        ir = parse_narrative_ir_response(raw_json)

        assert isinstance(ir, NarrativeIR)
        assert len(ir.paragraphs) == 2

        # Check first paragraph
        para1 = ir.paragraphs[0]
        assert para1.paragraph_idx == 1
        assert para1.topic == "开场冲突"
        assert para1.approx_source_start_sec == 0.0
        assert para1.approx_source_end_sec == 30.5
        assert len(para1.sentences) == 2

        # Check sentences in first paragraph
        sent1 = para1.sentences[0]
        assert sent1.sentence_idx == 1
        assert sent1.text == "男主在街头遭遇反派伏击。"
        assert sent1.evidence_keywords == ["男主", "街头", "伏击"]

        sent2 = para1.sentences[1]
        assert sent2.sentence_idx == 2
        assert sent2.text == "女主及时出现解围。"
        assert sent2.evidence_keywords == ["女主", "解围"]

        # Check second paragraph
        para2 = ir.paragraphs[1]
        assert para2.paragraph_idx == 2
        assert len(para2.sentences) == 1
        assert para2.sentences[0].sentence_idx == 3


class TestParseNarrativeIRError:
    """Test error handling in NarrativeIR parsing."""

    def test_parse_invalid_json(self):
        """Raise ValueError on invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_narrative_ir_response("{ invalid json }")

    def test_parse_missing_paragraphs_field(self):
        """Handle missing 'paragraphs' field gracefully (empty IR)."""
        raw_json = "{}"
        ir = parse_narrative_ir_response(raw_json)
        assert isinstance(ir, NarrativeIR)
        assert len(ir.paragraphs) == 0

    def test_parse_malformed_sentence(self):
        """Raise KeyError on malformed sentence data."""
        raw_json = """
        {
          "paragraphs": [
            {
              "paragraph_idx": 1,
              "topic": "test",
              "approx_source_start_sec": 0.0,
              "approx_source_end_sec": 10.0,
              "sentences": [
                {
                  "sentence_idx": 1
                }
              ]
            }
          ]
        }
        """
        with pytest.raises(KeyError):
            parse_narrative_ir_response(raw_json)


class TestNarrativeIRMethods:
    """Test NarrativeIR helper methods."""

    def test_iter_sentences_flat(self):
        """iter_sentences() returns all sentences in order."""
        sentences_p1 = [
            NarrativeSentence(sentence_idx=1, text="句1", evidence_keywords=[]),
            NarrativeSentence(sentence_idx=2, text="句2", evidence_keywords=[]),
        ]
        sentences_p2 = [
            NarrativeSentence(sentence_idx=3, text="句3", evidence_keywords=[]),
        ]

        ir = NarrativeIR(
            paragraphs=[
                NarrativeParagraph(
                    paragraph_idx=1,
                    topic="段落1",
                    approx_source_start_sec=0.0,
                    approx_source_end_sec=10.0,
                    sentences=sentences_p1,
                ),
                NarrativeParagraph(
                    paragraph_idx=2,
                    topic="段落2",
                    approx_source_start_sec=10.0,
                    approx_source_end_sec=20.0,
                    sentences=sentences_p2,
                ),
            ]
        )

        flat = ir.iter_sentences()
        assert len(flat) == 3
        assert flat[0].sentence_idx == 1
        assert flat[1].sentence_idx == 2
        assert flat[2].sentence_idx == 3

    def test_total_sentences(self):
        """total_sentences() returns correct count."""
        ir = NarrativeIR(
            paragraphs=[
                NarrativeParagraph(
                    paragraph_idx=1,
                    topic="段落1",
                    approx_source_start_sec=0.0,
                    approx_source_end_sec=10.0,
                    sentences=[
                        NarrativeSentence(sentence_idx=1, text="句1"),
                        NarrativeSentence(sentence_idx=2, text="句2"),
                    ],
                ),
                NarrativeParagraph(
                    paragraph_idx=2,
                    topic="段落2",
                    approx_source_start_sec=10.0,
                    approx_source_end_sec=20.0,
                    sentences=[
                        NarrativeSentence(sentence_idx=3, text="句3"),
                    ],
                ),
            ]
        )

        assert ir.total_sentences() == 3

    def test_empty_ir(self):
        """Empty NarrativeIR has zero sentences."""
        ir = NarrativeIR(paragraphs=[])
        assert ir.total_sentences() == 0
        assert ir.iter_sentences() == []

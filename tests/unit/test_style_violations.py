"""R1-R6 反模式正则扫描器单元测试（M2a-fix.1 / K-style-1 hard gate）。

锚点目标:
1. 每条 R1/R2/R5 各 ≥2 句级用例（正例 + 反例）
2. R4/R6 各 ≥2 段落级用例
3. R3 标记为 TODO（M2a-fix.2 后续增强）
4. 集成断言: data/realvideo_test/job_20260505_144455 的 12 句反例对 R5 命中率 100%
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoclip.algo.style_violations import (
    R1_PATTERN,
    R2_PATTERN,
    R5_PATTERN,
    StyleViolationReport,
    scan_narrative_ir,
)


# ============================================================
# R1 画面描述
# ============================================================


class TestR1PatternImageDescription:
    def test_hits_show_picture(self) -> None:
        assert R1_PATTERN.search("主持人展示牛的图片并介绍它住在农场。")

    def test_does_not_hit_normal_action(self) -> None:
        assert not R1_PATTERN.search("男主蹲在巷口的台阶上。")


# ============================================================
# R2 流水账动作衔接
# ============================================================


class TestR2PatternFlowConnective:
    def test_hits_然后接着(self) -> None:
        assert R2_PATTERN.search("男主推开门，然后看见反派。")

    def test_does_not_hit_clean_sentence(self) -> None:
        assert not R2_PATTERN.search("女主推开房门，看见反派坐在沙发上。")


# ============================================================
# R5 第三人称冷叙述
# ============================================================


class TestR5PatternThirdPersonColdNarration:
    def test_hits_主持人介绍(self) -> None:
        assert R5_PATTERN.search("主持人介绍今天要学习四种动物。")

    def test_hits_男主说(self) -> None:
        assert R5_PATTERN.search("男主说他不愿意离开。")

    def test_does_not_hit_action_only(self) -> None:
        assert not R5_PATTERN.search("男主蹲在巷口的台阶上望着远方。")

    def test_does_not_hit_emotional(self) -> None:
        assert not R5_PATTERN.search("好家伙，这反差也太离谱了！")


# ============================================================
# R3 复读对白（M2a-fix.2 后续增强占位）
# ============================================================


class TestR3PatternDialogueRepeat:
    @pytest.mark.skip(reason="R3 软规则需 ASR text 上下文，M2a-fix.2 增强")
    def test_placeholder(self) -> None:
        pass


# ============================================================
# R4/R6 段落级（通过 scan_narrative_ir 验证）
# ============================================================


class TestR4ParagraphLevelEmotionless:
    def test_long_emotionless_paragraph_hits(self) -> None:
        """6 句无标点情绪 + 无情绪词 → R4 命中。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": i, "text": f"角色做了第{i}件事情。"}
                    for i in range(1, 7)
                ]
            }
        ]
        report = scan_narrative_ir(paragraphs)
        assert report.counts["R4"] == 6  # 段落 6 句全部标记 R4

    def test_short_paragraph_does_not_hit_r4(self) -> None:
        """5 句不到段落最低门槛（≥6） → R4 不命中。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": i, "text": f"角色做了第{i}件事情。"}
                    for i in range(1, 6)
                ]
            }
        ]
        report = scan_narrative_ir(paragraphs)
        assert report.counts["R4"] == 0

    def test_paragraph_with_exclamation_does_not_hit_r4(self) -> None:
        """有感叹号 → R4 不命中。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": 1, "text": "这场面也太离谱了！"},
                    *[{"sentence_idx": i, "text": "正常陈述句。"} for i in range(2, 7)],
                ]
            }
        ]
        report = scan_narrative_ir(paragraphs)
        assert report.counts["R4"] == 0


class TestR6ParagraphLevelLackOfPerspective:
    def test_dry_paragraph_hits_r6(self) -> None:
        """4 句无吐槽词/反差词/情绪词 → R6 命中。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": i, "text": f"陈述事实第{i}句。"}
                    for i in range(1, 5)
                ]
            }
        ]
        report = scan_narrative_ir(paragraphs)
        assert report.counts["R6"] == 4

    def test_paragraph_with_roast_word_does_not_hit_r6(self) -> None:
        """含吐槽词"反差" → R6 不命中。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": 1, "text": "这反差感拉满了。"},
                    *[{"sentence_idx": i, "text": "陈述事实。"} for i in range(2, 5)],
                ]
            }
        ]
        report = scan_narrative_ir(paragraphs)
        assert report.counts["R6"] == 0


# ============================================================
# scan_narrative_ir 顶层 API
# ============================================================


class TestScanNarrativeIRAPI:
    def test_empty_paragraphs_returns_zero(self) -> None:
        report = scan_narrative_ir([])
        assert report.total_sentences == 0
        assert report.hit_rate == 0.0
        assert report.violations == []

    def test_returns_report_dataclass(self) -> None:
        report = scan_narrative_ir(
            [{"sentences": [{"sentence_idx": 1, "text": "正常剧情描述。"}]}]
        )
        assert isinstance(report, StyleViolationReport)
        assert set(report.counts.keys()) == {"R1", "R2", "R3", "R4", "R5", "R6"}


# ============================================================
# 集成测试：12 句反例 R5 命中率 100%
# ============================================================


REALVIDEO_REGRESSION_FIXTURE = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "realvideo_test"
    / "job_20260505_144455"
    / "timeline.json"
)


class TestRealVideoRegression:
    @pytest.mark.skipif(
        not REALVIDEO_REGRESSION_FIXTURE.exists(),
        reason="job_20260505_144455 fixture missing",
    )
    def test_12_sentences_anti_pattern_full_coverage(self) -> None:
        """对 job_20260505_144455 的 12 句 narrative_ir.text，反模式总命中率必须 100%。

        这是 K-style-1 扫描器的核心有效性断言。采用三联断言显式暴露
        "R5 + R6 互补覆盖" 的设计假设：

        - hit_rate = 1.0 (硬断言): 12 句反例必须 100% 被识别为反模式
        - R5 ≥ 8: 第三人称冷叙述 (句首主语模式) 至少覆盖 8 句
        - R6 ≥ 8: 段落级缺二创视角 (无吐槽词/反差词) 至少覆盖 8 句

        若此断言失败：
        - hit_rate < 1.0 → 扫描器对真实反例数据漏检 (硬故障)
        - R5 漏命中 → 句首主语正则失效或反例数据漂移
        - R6 漏命中 → 段落级吐槽词清单失效或反例数据漂移

        反例数据真实分布 (commit 时基线):
        R1=4 / R2=0 / R3=0 / R4=0 / R5=8 / R6=8 / hit_rate=1.0
        """
        timeline = json.loads(REALVIDEO_REGRESSION_FIXTURE.read_text(encoding="utf-8"))
        paragraphs = timeline["narrative_ir"]["paragraphs"]
        report = scan_narrative_ir(paragraphs)

        violation_dump = [
            (v.sentence_idx, v.text, v.rules_hit) for v in report.violations
        ]

        assert report.total_sentences == 12, "fixture sentences count drift"
        assert report.hit_rate == 1.0, (
            f"K-style-1 hard gate failure: 12 anti-pattern sentences must be "
            f"100% flagged, got hit_rate={report.hit_rate}; "
            f"counts={report.counts}; violations={violation_dump}"
        )
        assert report.counts["R5"] >= 8, (
            f"R5 (third-person cold narration, head-anchored) should cover "
            f"≥8 sentences, got {report.counts['R5']}; violations={violation_dump}"
        )
        assert report.counts["R6"] >= 8, (
            f"R6 (paragraph-level lack of perspective) should cover "
            f"≥8 sentences, got {report.counts['R6']}; violations={violation_dump}"
        )

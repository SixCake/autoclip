"""Stage1 Floor Check 单元测试（autoclip v0.8）。

锚点目标:
1. 每条 R1/R2/R5 各 ≥2 句级用例（正例 + 反例）
2. R4/R6 各 ≥2 段落级用例
3. R3 标记为 TODO（未来增强）
4. BANNED_WORDS 零容忍命中验证
5. 集成断言: data/realvideo_test/job_20260505_144455 的 12 句 v0.7 反例必须 100% 被识别
6. 集成断言: data/realvideo_test/job_20260505_201036 的 13 句 v0.8 输出 floor check 应 ≤1 violations（仅 R2 单条已知误报，记入 F3 backlog）

重命名自 test_style_violations.py（v0.7 → v0.8 改名 P0-2）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoclip.algo.stage1_floor_check import (
    BANNED_WORDS,
    R1_PATTERN,
    R2_PATTERN,
    R5_PATTERN,
    ROAST_WORDS,
    FloorCheckReport,
    check_stage1_output,
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
# R3 复读对白（未来增强占位）
# ============================================================


class TestR3PatternDialogueRepeat:
    @pytest.mark.skip(reason="R3 软规则需 ASR text 上下文，未来增强（v0.8 backlog）")
    def test_placeholder(self) -> None:
        pass


# ============================================================
# R4/R6 段落级
# ============================================================


class TestR4ParagraphLevelEmotionless:
    def test_long_emotionless_paragraph_hits(self) -> None:
        """6 句无标点情绪 + 无情绪词 → R4 命中。

        注：'角色做了第N件事情' 同时会触发 R5（"角色 + 做"句首正则），
        所以本断言只验证 R4=6（段落级），不约束 R5 是否命中。
        """
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": i, "text": f"角色做了第{i}件事情。"}
                    for i in range(1, 7)
                ]
            }
        ]
        report = check_stage1_output(paragraphs)
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
        report = check_stage1_output(paragraphs)
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
        report = check_stage1_output(paragraphs)
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
        report = check_stage1_output(paragraphs)
        assert report.counts["R6"] == 4

    def test_paragraph_with_roast_word_does_not_hit_r6(self) -> None:
        """含 v0.7 时代纯 ROAST 词"反差""操作"（未在 BANNED_WORDS 中）→ R6 不命中。

        注：原 v0.7 测试用的"拉满"既在 BANNED_WORDS 也在 ROAST_WORDS，
        新版会触发零容忍 BANNED 违规，不再适合作为 R6 escape 用例。
        """
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": 1, "text": "这反差也太离谱了。"},
                    *[{"sentence_idx": i, "text": "陈述事实。"} for i in range(2, 5)],
                ]
            }
        ]
        report = check_stage1_output(paragraphs)
        assert report.counts["R6"] == 0

    def test_paragraph_with_v08_roast_word_does_not_hit_r6(self) -> None:
        """含 v0.8 时代新 ROAST 词"糊弄""硬撑" → R6 不命中（验证词典扩充生效）。"""
        paragraphs = [
            {
                "sentences": [
                    {"sentence_idx": 1, "text": "这内容分明是糊弄观众，全靠配音硬撑。"},
                    *[{"sentence_idx": i, "text": "陈述事实。"} for i in range(2, 5)],
                ]
            }
        ]
        report = check_stage1_output(paragraphs)
        assert report.counts["R6"] == 0, (
            f"v0.8 时代 ROAST 词应让 R6 escape，实际 R6={report.counts['R6']}；"
            f"ROAST_WORDS 当前长度={len(ROAST_WORDS)}"
        )


# ============================================================
# BANNED_WORDS 零容忍（v0.8 新增）
# ============================================================


class TestBannedWordsZeroTolerance:
    def test_banned_word_triggers_violation(self) -> None:
        """禁用词 → BANNED:<word> 违规标签。"""
        paragraphs = [{"sentences": [{"sentence_idx": 1, "text": "这剧情绝了。"}]}]
        report = check_stage1_output(paragraphs)
        rules_hit = report.violations[0].rules_hit
        assert any(r.startswith("BANNED:") for r in rules_hit), (
            f"禁用词'绝了'应触发 BANNED 标签，实际命中: {rules_hit}"
        )
        assert report.is_passed is False

    def test_clean_text_does_not_trigger_banned(self) -> None:
        """非禁用词文本 → 无 BANNED 命中。"""
        paragraphs = [
            {"sentences": [{"sentence_idx": 1, "text": "这段镜头节奏紧凑，看得出是大制作。"}]}
        ]
        report = check_stage1_output(paragraphs)
        for v in report.violations:
            assert not any(r.startswith("BANNED:") for r in v.rules_hit), (
                f"clean text 不应触发 BANNED，实际命中: {v.rules_hit}"
            )

    def test_banned_words_list_size(self) -> None:
        """v0.8 BANNED_WORDS 当前 10 个词（防误删保护）。"""
        assert len(BANNED_WORDS) == 10, (
            f"BANNED_WORDS 长度变化需主动 review，"
            f"当前 {len(BANNED_WORDS)} 个: {BANNED_WORDS}"
        )


# ============================================================
# check_stage1_output 顶层 API
# ============================================================


class TestCheckStage1OutputAPI:
    def test_empty_paragraphs_returns_zero(self) -> None:
        report = check_stage1_output([])
        assert report.total_sentences == 0
        assert report.is_passed is True  # 零句数 = 无违规 = 通过
        assert report.violations == []

    def test_returns_floor_check_report_dataclass(self) -> None:
        report = check_stage1_output(
            [{"sentences": [{"sentence_idx": 1, "text": "正常剧情描述。"}]}]
        )
        assert isinstance(report, FloorCheckReport)
        assert set(report.counts.keys()) >= {"R1", "R2", "R3", "R4", "R5", "R6"}

    def test_is_passed_flag_zero_tolerance(self) -> None:
        """零容忍：任何 violations 即 is_passed=False。"""
        # 单条 R5 命中 → is_passed=False
        paragraphs = [{"sentences": [{"sentence_idx": 1, "text": "主持人介绍今天要学习四种动物。"}]}]
        report = check_stage1_output(paragraphs)
        assert report.is_passed is False
        assert len(report.violations) >= 1


# ============================================================
# 集成测试：v0.7 baseline 12 句反例必须全部被识别
# ============================================================


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
V07_BASELINE_FIXTURE = (
    REPO_ROOT / "data" / "realvideo_test" / "job_20260505_144455" / "timeline.json"
)
V08_BASELINE_FIXTURE = (
    REPO_ROOT / "data" / "realvideo_test" / "job_20260505_201036" / "timeline.json"
)


class TestRealVideoRegressionV07:
    """v0.7 baseline (job_20260505_144455) — 12 句反例必须被零容忍识别。"""

    @pytest.mark.skipif(
        not V07_BASELINE_FIXTURE.exists(),
        reason="v0.7 baseline fixture missing",
    )
    def test_v07_12_sentences_all_violate(self) -> None:
        """v0.7 12 句"百度百科"风格必须全部被识别为违规（零容忍 is_passed=False）。

        反例数据真实分布（baseline 报告 §2 锁定）:
        R1=4 / R2=0 / R3=0 / R4=0 / R5=8 / R6=8 / 12 句全 violate

        若失败 → 扫描器对真实反例数据漏检（硬故障）。
        """
        timeline = json.loads(V07_BASELINE_FIXTURE.read_text(encoding="utf-8"))
        paragraphs = timeline["narrative_ir"]["paragraphs"]
        report = check_stage1_output(paragraphs)

        violation_dump = [
            (v.sentence_idx, v.text[:40], v.rules_hit) for v in report.violations
        ]

        assert report.total_sentences == 12, "v0.7 baseline 句数漂移"
        assert report.is_passed is False, "v0.7 baseline 必须未通过零容忍门禁"
        assert len(report.violations) == 12, (
            f"v0.7 baseline 12 句应全部违规，实际 {len(report.violations)} 句；"
            f"violations={violation_dump}"
        )
        assert report.counts["R1"] == 4, f"R1 应=4，实际={report.counts['R1']}"
        assert report.counts["R5"] == 8, f"R5 应=8，实际={report.counts['R5']}"
        assert report.counts["R6"] == 8, f"R6 应=8，实际={report.counts['R6']}"


class TestRealVideoRegressionV08:
    """v0.8 prompt-only baseline (job_20260505_201036) — 验证 F1 修扫描器后 violations ≤ 1。"""

    @pytest.mark.skipif(
        not V08_BASELINE_FIXTURE.exists(),
        reason="v0.8 baseline fixture missing",
    )
    def test_v08_violations_bounded_after_f1_fix(self) -> None:
        """v0.8 baseline 在 F1 修扫描器后 violations 应 ≤1（仅剩 R2 时间副词误报）。

        F1 改动前：9 violations（R6 段落级误报 8 + R2 单条 1）
        F1 改动后：1 violations（R2 单条已知误报 → F3 backlog）

        若失败 → ROAST_WORDS 词典退化或新出现误报模式。
        """
        timeline = json.loads(V08_BASELINE_FIXTURE.read_text(encoding="utf-8"))
        paragraphs = timeline["narrative_ir"]["paragraphs"]
        report = check_stage1_output(paragraphs)

        violation_dump = [
            (v.sentence_idx, v.text[:40], v.rules_hit) for v in report.violations
        ]

        assert report.total_sentences == 13, "v0.8 baseline 句数漂移"
        # 不要求 is_passed=True（R2 误报暂未修），只要求 violations ≤ 1
        assert len(report.violations) <= 1, (
            f"v0.8 baseline F1 修复后 violations 应 ≤1（仅 R2 已知误报），"
            f"实际 {len(report.violations)} 句；violations={violation_dump}"
        )
        # R1/R5（v0.7 主要反模式）必须 0
        assert report.counts["R1"] == 0, (
            f"v0.8 R1 应=0（prompt 已解决），实际={report.counts['R1']}"
        )
        assert report.counts["R5"] == 0, (
            f"v0.8 R5 应=0（prompt 已解决），实际={report.counts['R5']}"
        )
        # R6 应 0（F1 词典扩充后误报清零）
        assert report.counts["R6"] == 0, (
            f"v0.8 R6 应=0（F1 修扫描器后），实际={report.counts['R6']}；"
            f"ROAST_WORDS 长度={len(ROAST_WORDS)}"
        )

"""Stage1 Floor Check: R1-R6 反模式零容忍扫描器（autoclip v0.8）。

零 LLM 成本、零外部依赖；作为 Stage1（钩子+骨架）输出的硬门禁：
**零容忍命中**（hit any anti-example → Stage1 FAILED）。

反模式定义来源: multi-role-debate U1/U8 共识（docs/plans/debates/2026-05-05-good-erchuang-debate.md）；
反例锚点: docs/anchors/anti_examples.md（U2 + U3：上帝视角 + 套话情绪 + 教学口气 + 陈述事实零钩子）。

# SUNSET: v1.0 前用户使用率 < 30% 时废止
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ============================================================
# R1-R6 正则规则（句级）
# SUNSET: v1.0 前用户使用率 < 30% 时废止
# ============================================================

# R1 画面描述：「X 展示了 Y 图片/画面/镜头」
# SUNSET: v1.0 前用户使用率 < 30% 时废止
R1_PATTERN = re.compile(r"(展示|呈现|出现|播放|播出|画面中)[^，。！？]{0,8}(图片|画面|镜头|图像|场景)")

# R2 流水账动作衔接词
# SUNSET: v1.0 前用户使用率 < 30% 时废止
R2_PATTERN = re.compile(r"(然后|接着|随后|之后|首先|其次|最后)")

# R5 第三人称冷叙述：「主持人/角色/男主/女主/反派 X + 陈述动词」开头
# SUNSET: v1.0 前用户使用率 < 30% 时废止
R5_PATTERN = re.compile(
    r"^(主持人|男主|女主|反派|角色|演员)[A-Za-z0-9]?[^，。]{0,15}(说|做|介绍|展示|表扬|回顾|欢迎|宣布|告诉|讲述|提到|呈现)"
)

# R3/R4/R6 用关键词列表（段落级或软规则更准）
# SUNSET: v1.0 前用户使用率 < 30% 时废止
EMOTION_PUNCT = re.compile(r"[！？]")
EMOTION_WORDS = ("离谱", "绝了", "笑死", "震惊", "不愧是", "这就是", "好家伙", "服了", "破防", "炸裂")
ROAST_WORDS = (
    # v0.7 时代（B 站黑话型）
    "反差", "操作", "属于是", "典中典", "整活", "翻车", "拉满", "尴尬到", "降智",
    # v0.8 时代（"具体观察 + 立场解读"风格中常见的判断/吐槽词，2026-05-05 由 baseline 报告统计加入）
    "糊弄", "硬撑", "拖沓", "粗糙", "摧毁", "简直", "误导", "纯粹", "欺骗",
    "偷懒", "差评", "无聊", "低成本", "缩水", "脱节", "急着", "哪是",
)

# 禁用词清单（绝不容忍）
BANNED_WORDS = ("绝了", "洗脑", "拉满", "良心", "顶得住", "爆棚", "有福了", "DNA 动了", "拿捏", "破防")


# ============================================================
# 数据结构
# ============================================================


@dataclass
class SentenceViolation:
    """单句的违规命中明细。"""

    sentence_idx: int
    text: str
    rules_hit: list[str] = field(default_factory=list)  # ['R1', 'R5', ...]


@dataclass
class FloorCheckReport:
    """Stage1 输出的扫描结果（零容忍命中）。"""

    total_sentences: int
    counts: dict[str, int]  # {'R1': 0, 'R2': 0, 'R3': 0, 'R4': 0, 'R5': 12, 'R6': 0}
    violations: list[SentenceViolation]  # 仅保留有命中的句子
    is_passed: bool  # 零容忍：有任何违规即为 False


# ============================================================
# 句级扫描函数
# ============================================================


def _check_sentence(text: str) -> list[str]:
    """对单句返回命中的规则 ID 列表（R1/R2/R5；R3/R4/R6 在段落级判定）。"""
    hits: list[str] = []
    if R1_PATTERN.search(text):
        hits.append("R1")
    if R2_PATTERN.search(text):
        hits.append("R2")
    if R5_PATTERN.search(text):
        hits.append("R5")
    # 检查禁用词
    for word in BANNED_WORDS:
        if word in text:
            hits.append(f"BANNED:{word}")
    return hits


def _check_paragraph(sentences: list[str]) -> list[str]:
    """对一组段落内的句子返回段落级反模式命中 ID（R4/R6）。

    R4 客观零情绪: 段落内 ≥6 句且无任何 [！？] 且无情绪词。
    R6 缺二创视角: 段落内 ≥4 句且无吐槽词/反差词。
    R3 复读对白: 当前版本占位，需 ASR text 上下文，留给后续增强。
    """
    para_hits: list[str] = []
    n = len(sentences)
    full_text = "".join(sentences)
    if n >= 6 and not EMOTION_PUNCT.search(full_text) and not any(w in full_text for w in EMOTION_WORDS):
        para_hits.append("R4")
    if n >= 4 and not any(w in full_text for w in (*EMOTION_WORDS, *ROAST_WORDS)):
        para_hits.append("R6")
    return para_hits


# ============================================================
# 主入口
# ============================================================


def check_stage1_output(paragraphs: list[dict]) -> FloorCheckReport:
    """扫描 Stage1 输出（钩子+骨架），返回 FloorCheckReport（零容忍命中）。

    Args:
        paragraphs: Stage1 输出的 paragraphs 列表，每项含 'sentences': [{'sentence_idx', 'text', ...}]。

    Returns:
        FloorCheckReport: 含 6 条规则各自命中数、违规明细、是否通过（零容忍）。
    """
    counts = {f"R{i}": 0 for i in range(1, 7)}
    violations: list[SentenceViolation] = []
    total_sentences = 0

    for para in paragraphs:
        sents = para.get("sentences", [])
        sent_texts = [s.get("text", "") for s in sents]

        # 段落级判定：R4 / R6 命中时，段落内每句都标记
        para_level_hits = _check_paragraph(sent_texts)

        for s in sents:
            total_sentences += 1
            text = s.get("text", "")
            sent_level_hits = _check_sentence(text)
            all_hits = sent_level_hits + para_level_hits
            for rule_id in all_hits:
                if rule_id.startswith("R"):
                    counts[rule_id] += 1
                else:
                    counts["BANNED"] = counts.get("BANNED", 0) + 1
            if all_hits:
                violations.append(
                    SentenceViolation(
                        sentence_idx=s.get("sentence_idx", -1),
                        text=text,
                        rules_hit=all_hits,
                    )
                )

    # 零容忍：有任何违规即为 False
    is_passed = len(violations) == 0

    return FloorCheckReport(
        total_sentences=total_sentences,
        counts=counts,
        violations=violations,
        is_passed=is_passed,
    )

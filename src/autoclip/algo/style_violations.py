"""R1-R6 反模式正则扫描器（M2a-fix.1 / K-style-1 hard gate）。

零 LLM 成本、零外部依赖；M2a-fix.2 起作为 narrative_ir 生成后的硬门禁：
hit_rate = 命中反模式句数 / 总句数 ≤ 10%。

反模式定义来源: brainstorming Session 20 Q4 决议（.context/changes.md L1526-1535）；
反例锚点: data/realvideo_test/job_20260505_144455 的 12 句 narrative_ir.text，
对 R5 应 100% 命中（验证扫描器有效性）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ============================================================
# R1-R6 正则规则（句级）
# ============================================================

# R1 画面描述：「X 展示了 Y 图片/画面/镜头」
R1_PATTERN = re.compile(r"(展示|呈现|出现|播放|播出|画面中)[^，。！？]{0,8}(图片|画面|镜头|图像|场景)")

# R2 流水账动作衔接词
R2_PATTERN = re.compile(r"(然后|接着|随后|之后|首先|其次|最后)")

# R5 第三人称冷叙述：「主持人/角色/男主/女主/反派 X + 陈述动词」开头
R5_PATTERN = re.compile(
    r"^(主持人|男主|女主|反派|角色|演员)[A-Za-z0-9]?[^，。]{0,15}(说|做|介绍|展示|表扬|回顾|欢迎|宣布|告诉|讲述|提到|呈现)"
)

# R3/R4/R6 用关键词列表（段落级或软规则更准）
EMOTION_PUNCT = re.compile(r"[！？]")
EMOTION_WORDS = ("离谱", "绝了", "笑死", "震惊", "不愧是", "这就是", "好家伙", "服了", "破防", "炸裂")
ROAST_WORDS = ("反差", "操作", "属于是", "典中典", "整活", "翻车", "拉满", "尴尬到", "降智")


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
class StyleViolationReport:
    """整段 narrative_ir 的扫描结果。"""

    total_sentences: int
    counts: dict[str, int]  # {'R1': 0, 'R2': 0, 'R3': 0, 'R4': 0, 'R5': 12, 'R6': 0}
    hit_rate: float  # 命中至少一条规则的句数 / 总句数 ∈ [0, 1]
    violations: list[SentenceViolation]  # 仅保留有命中的句子


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
    return hits


def _check_paragraph(sentences: list[str]) -> list[str]:
    """对一组段落内的句子返回段落级反模式命中 ID（R4/R6）。

    R4 客观零情绪: 段落内 ≥6 句且无任何 [！？] 且无情绪词。
    R6 缺二创视角: 段落内 ≥4 句且无吐槽词/反差词。
    R3 复读对白: 当前版本占位，需 ASR text 上下文，留给 M2a-fix.2 后续增强。
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


def scan_narrative_ir(paragraphs: list[dict]) -> StyleViolationReport:
    """扫描 narrative_ir.paragraphs，返回 StyleViolationReport。

    Args:
        paragraphs: narrative_ir.paragraphs 列表，每项含 'sentences': [{'sentence_idx', 'text', ...}]。

    Returns:
        StyleViolationReport: 含 6 条规则各自命中数、整体命中率、违规明细。
    """
    counts = {f"R{i}": 0 for i in range(1, 7)}
    violations: list[SentenceViolation] = []
    total_sentences = 0
    hit_sentence_count = 0

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
                counts[rule_id] += 1
            if all_hits:
                hit_sentence_count += 1
                violations.append(
                    SentenceViolation(
                        sentence_idx=s.get("sentence_idx", -1),
                        text=text,
                        rules_hit=all_hits,
                    )
                )

    hit_rate = hit_sentence_count / total_sentences if total_sentences > 0 else 0.0

    return StyleViolationReport(
        total_sentences=total_sentences,
        counts=counts,
        hit_rate=hit_rate,
        violations=violations,
    )

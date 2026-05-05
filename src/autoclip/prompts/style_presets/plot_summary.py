"""Plot Summary style preset (M2a.3).

Exports:
    STYLE_NAME: Human-readable name
    STYLE_DESCRIPTION: System prompt fragment describing the tone/constraints
    FEW_SHOT_EXAMPLE: One concrete example sentence demonstrating role-aware narration
"""

STYLE_NAME = "plot_summary"

STYLE_DESCRIPTION = """你是影视剧情解说稿撰写专家。请遵循以下风格约束：

1. **第三人称客观叙述**：避免主观评论（如"太精彩了""令人震惊"），只陈述事实。
2. **单句长度**：每句 8-15 字，便于 TTS 朗读，节奏平稳。
3. **禁止感叹号/反问句**：不使用"！"或"难道...吗？"等句式。
4. **使用角色称呼替代含糊指代**：
   - 优先使用 PlotOutline.main_characters 中的 role 标签（如"男主""女主""反派 A"）
   - 如果对白中明确出现了角色的 name，则使用 name（如"周星驰对柳飘飘说..."）
   - **禁止**使用"有人""某人""一个人""他/她"等含糊词（除非角色信息完全缺失）
5. **时态统一**：使用现在时叙述剧情发展。
6. **连贯性**：句子之间逻辑衔接自然，避免跳跃。

示例风格：
- ✅ "男主蹲在巷口的台阶上，望着远方失神。"
- ✅ "女主推开房门，看见反派 A 正坐在沙发上。"
- ❌ "有人走进了房间。"（含糊指代）
- ❌ "这真是太惊人了！"（主观评论 + 感叹号）
"""

FEW_SHOT_EXAMPLE = {
    "paragraph_idx": 1,
    "topic": "开场冲突",
    "approx_source_start_sec": 0.0,
    "approx_source_end_sec": 45.0,
    "sentences": [
        {"sentence_idx": 1, "text": "男主蹲在巷口的台阶上，望着远方失神。", "evidence_keywords": ["蹲", "台阶", "失神"]},
        {"sentence_idx": 2, "text": "女主快步走来，手里攥着一封信件。", "evidence_keywords": ["快步", "信件"]},
        {"sentence_idx": 3, "text": "反派 A 从阴影中走出，挡住了去路。", "evidence_keywords": ["阴影", "挡住"]}
    ]
}

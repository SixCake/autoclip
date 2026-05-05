# M2a-fix v0.8 — 二创风格修正（B0+B1 渐进路径）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §17.6（v0.8 两阶段 LLM v2 架构）
> **Baseline**: [`../baselines/2026-05-05-v0.8-baseline.md`](../baselines/2026-05-05-v0.8-baseline.md)
> **Debate**: [`../debates/2026-05-05-good-erchuang-debate.md`](../debates/2026-05-05-good-erchuang-debate.md)
> **历史归档**: [`./_archived_2026-05-05_M2a-fix-v0.7.md`](./_archived_2026-05-05_M2a-fix-v0.7.md)（v0.7 三层枚举方案，374 行）

---

## v0.7 → v0.8 演进总结

| 维度 | v0.7（已归档） | v0.8（本文档） |
|---|---|---|
| 任务数 | 5 子任务（M2a-fix.1~.5）| 8 子任务（v0.8.1~.8） |
| 工时 | 6.6d | **3.4d**（-3.2d，砍 48%） |
| 核心架构 | 三层封闭枚举（10×7×5）+ 两阶段 LLM Inference | "判断句基因"prompt 改造 + 人格驱动单 LLM call |
| 触发推翻 | Session 22-23 multi-role-debate（5 角色 / 11 项 corrections）+ baseline 报告（C 阶段 2026-05-05） |

**为什么砍这么多**：baseline 验证发现 prompt-only 改动已让 R1/R5 命中率从 100%/67% 降到 0，达到 75 分档（"素人怕丢人"），原 6.6d 中的"三层枚举推断 / 两阶段 LLM 拆分 / fallback 矩阵"几个大头**ROI 极低**——属于在 prompt 已解决的问题上做架构防御。详见 baseline 报告 §5。

---

## OQ 决策（2026-05-05 用户拍板）

| OQ | 选项 | 决议 |
|---|---|---|
| **OQ-C** | Stage1 LLM 是否输出 3 个钩子候选？UI 是否露出？ | **C：API 层就绪 + UI 层延后**——LLM 输出 3 个钩子候选写到 timeline.json，UI 层在 M3.7 一并露出 |

---

## Milestone 目标

让 narrative_ir.text 从"百度百科"升级为"B 站二创"：

1. **Stage1 floor check 全过**：`stage1_floor_check.is_passed=True`（零容忍命中）
2. **人格自适应**：单一"毒舌中年"在治愈/儿歌题材自动切换到"治愈大姐"（避免冒犯）
3. **钩子前置**：前 3 句必有 1 条判断式钩子（人工 review checklist 1）
4. **覆盖面**：5 部不同题材视频（电影/动漫/短剧/儿歌/Vlog）人工评分均 ≥75 分

---

## Milestone 验收

- [ ] 5 部测试视频的 floor check is_passed=True
- [ ] 5 部视频中 ≥4 部由人工评分 ≥75 分（"愿意发布"门槛）
- [ ] timeline.json 含 `recommended_persona` + `hook_candidates: list[str]` 字段
- [ ] 单 LLM call 端到端耗时仍 ≤25s（无新增 LLM 调用）
- [ ] 不引入新依赖，不改 schema 现有字段（仅 add，不 modify）

---

## 任务清单（8 个，3.4d）

| ID | 任务 | 工时 | 状态 |
|---|---|---|---|
| **v0.8.1** | F1 修 stage1_floor_check.py R6 词典（已完成）| 0.2d | ✅ done |
| **v0.8.2** | F3 R2 时间副词误报上下文区分（backlog，可延后）| 0.3d | ⚪ deferred |
| **v0.8.3** | persona_inferer.py 改为轻量 persona_id 推断（去掉钩子+骨架的复杂输出）| 0.5d | ⏳ pending |
| **v0.8.4** | scripting handler 注入 persona_id，按人格加载 reference 台词 | 0.3d | ⏳ pending |
| **v0.8.5** | LLM 输出 3 个钩子候选，写入 timeline.json（OQ-C 决议）| 0.3d | ⏳ pending |
| **v0.8.6** | timeline.json schema 加 2 字段（recommended_persona / hook_candidates，仅 add）| 0.2d | ⏳ pending |
| **v0.8.7** | 5 部不同题材视频端到端跑批 + 人工评分表 | 1.0d | ⏳ pending |
| **v0.8.8** | 验收报告 + state.json 收尾 + 决定是否进 M3 | 0.6d | ⏳ pending |

> 子任务详情见 §详细任务（首版仅含目标+验收两个字段，实施前补具体步骤）。

---

## 详细任务（首版精简）

### v0.8.1 ✅ F1 修 R6 词典

- **目标**：扫描器跟上 v0.8 prompt 进化
- **产出**：`src/autoclip/algo/stage1_floor_check.py` ROAST_WORDS +17 词
- **验收**：v0.8 baseline job_20260505_201036 floor check violations 9 → 1
- **状态**：已完成（commit 待 push）

### v0.8.2 ⚪ F3 R2 误报上下文区分（deferred）

- **目标**：让 R2 不再把"最后旁白说"中的"最后"作为流水账衔接词误抓
- **思路**：检测"最后"是否后接"然后/接着/之后"或位于段落开头才命中
- **延后理由**：单条命中不影响 75 分档判断；优先级低于人格集成
- **触发条件**：v0.8.7 跑批后若新视频中 R2 误报率 >10% 才启动

### v0.8.3 persona_inferer 轻量化

- **目标**：把当前的"输出 persona + hook_candidates ≥3 + paragraph_skeleton"复杂结构砍成"仅输出 persona_id"
- **理由**：钩子候选改由主 LLM call 输出（v0.8.5），骨架在 v0.7 时代验证已无价值
- **验收**：函数返回签名 `infer_persona(asr_text, kf_desc) -> str`（直接返回 persona_id）
- **保留接口**：返回 dataclass 含 `persona_id` + `reasoning`（50 字解释，可观测）

### v0.8.4 scripting handler 集成

- **目标**：在 scripting handler 里加 persona_inferer 调用，把 persona reference 台词注入 plot_summary.py 的 user 段落
- **不做**：不拆 Stage1/Stage2 两次 LLM call（依然单 call）
- **验收**：测试视频跑出来人格随题材切换（毒舌→治愈/考古等）

### v0.8.5 钩子候选 3 个

- **目标**：在 plot_summary.py 的输出 schema 中要求 LLM 额外输出 `hook_candidates: list[str] (len=3)`，写到 timeline.json 但不替换 paragraph[0].sentences[0]
- **实现方式**：扩展现有 narrative_ir JSON schema，单 LLM call 内完成
- **验收**：timeline.json 含 hook_candidates 字段且 len=3，每条人工 review 为"判断式"

### v0.8.6 schema 扩展

- **目标**：timeline.json 顶层加 `recommended_persona: str` + `hook_candidates: list[str]` 两字段
- **约束**：仅 add 不 modify；旧 timeline.json 加载时这两字段为 None 不报错（Optional + default=None）
- **验收**：旧 baseline timeline.json (job_20260505_144455) 仍能被 Pydantic 加载

### v0.8.7 5 部跑批 + 人工评分

- **目标**：覆盖 5 种题材验证 75 分覆盖面
- **题材列表**：电影 / 动漫 / 短剧 / 儿歌（毒舌冒犯风险测试）/ Vlog
- **评分表**：每段产出由我自评 + 用户复评（5 维度：钩子前置 / 判断句占比 / 人格契合 / 套路反例零命中 / 整体可发布性）
- **验收**：≥4/5 视频得 75 分以上

### v0.8.8 验收报告 + 决策

- **目标**：写 `docs/plans/baselines/2026-05-XX-v0.8-final.md` + 决策是否启动 B2 完整两阶段
- **B2 启动触发条件**（基于 v0.8.7 数据）：
  - 触发 1：人格不适配率 >30%
  - 触发 2：用户明确要求 UI 露钩子选择器
  - 触发 3：单 LLM call 输出钩子质量明显劣于段落质量

---

## 工时汇总

| 子任务 | 工时 | 累计 |
|---|---|---|
| v0.8.1 ✅ | 0.2d | 0.2d |
| v0.8.2 ⚪ | 0.3d | (不计入主路径) |
| v0.8.3 | 0.5d | 0.7d |
| v0.8.4 | 0.3d | 1.0d |
| v0.8.5 | 0.3d | 1.3d |
| v0.8.6 | 0.2d | 1.5d |
| v0.8.7 | 1.0d | 2.5d |
| v0.8.8 | 0.6d | 3.1d |
| **小计** | **3.1d**（含 buffer 0.3d → 3.4d） |

---

## 与 M2b 的关系（v0.8 修订）

| 项 | v0.7 设计 | v0.8 修订 |
|---|---|---|
| M2b-light | 已并入 M2a-fix.5 | **删除**（v0.8 已完成 narrative_intent 等价能力 — 通过 persona_inferer 推断） |
| M2b-full | 0d 或 4d 数据驱动 | **大概率跳过**（v0.8.7 跑批数据驱动决定）|

**M2b 完全跳过的 trigger**：v0.8.7 验收 ≥4/5 视频达 75 分 → 直接进 M3。

---

## 与 P0/P1 corrections 的追溯（debate 11 项 corrections）

| Correction | v0.8 落入 | 状态 |
|---|---|---|
| P0-1 重写 design.md §17.6 为两阶段 LLM v2 | design.md §17.6 | ✅ 已完成（Session 23）|
| P0-2 删除 K-style-1 / R1-R6 改名 stage1_floor_check.py | src/autoclip/algo/stage1_floor_check.py | ✅ 已完成 |
| P0-3 docs/personas/ 5-8 人格库 | docs/personas/ 6 个 .md | ✅ 已完成 |
| P0-4 docs/anchors/ good_examples + anti_examples | docs/anchors/ 3 个 .md | ✅ 已完成 |
| P0-5 工程隔离条款 | design.md §17.6 (2) + docs/anchors/README.md | ✅ 已完成 |
| P0-6 sunset 注释 + CI 检查 | stage1_floor_check.py 文件头 + 每条规则 | ✅ 已完成 |
| P1-1 persona_inferer.py | src/autoclip/algo/persona_inferer.py（v0.8.3 轻量化）| 🟡 待轻量化 |
| P1-2 docs/anchors/README.md review checklist | docs/anchors/README.md | ✅ 已完成 |
| P1-3 目标分三档 | design.md §17.6 (4) | ✅ 已完成 |
| P2-1 pivot 成本评估 | 延后到 v1.0 前 | ⏳ deferred |
| P2-2 季度 sunset review 机制 | 延后到 v0.8.7 后 | ⏳ deferred |

---

## 附录：与 baseline 报告的追溯关系

baseline 报告 §6 列出的 F1-F5 follow-up 在本文档的对应：

| baseline 报告 | 本文档 |
|---|---|
| F1 修 R6 词典 | v0.8.1 ✅ |
| F2 验证扫描 | v0.8.1 验收（已完成）|
| F3 重写任务文档 | 本文档（A 阶段）|
| F4 persona_inferer 轻量化 + 注入 | v0.8.3 + v0.8.4 |
| F5 跑 5 部题材 | v0.8.7 |

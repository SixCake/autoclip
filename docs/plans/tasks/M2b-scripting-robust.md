# M2b — Scripting 鲁棒性 + narrative IR + KPI 评估（Week 3）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §16.3（核心算法升级） / §17.1 / §18.2

## 🎯 Milestone 目标
将 M2a 的 baseline 绑定（按 paragraph hint 均分）升级为 **narrative IR + post-validation 两阶段算法**：用 `evidence_keywords` 反向检索 ASR 定位精确时间窗口，并补齐绑定约束（最小镜头时长、单句最多镜头数、跨段不复用）。建立 KPI 评估脚本，跑通 3 部不同类型作品的人工打标，量化绑定准确率。

## ✅ Milestone 验收
- [ ] 3 部不同类型作品（实拍剧情 / 实拍动作 / 动漫）各跑一次完整 Scripting
- [ ] 每部各 50 句人工打标后，绑定准确率 **K1 ≥ 70%**
- [ ] evidence 召回率 **K2 ≥ 80%**（LLM 输出非空 evidence_keywords 的比例）
- [ ] fallback 触发率 **K3 ≤ 30%**（resolve 返回 None 的比例）
- [ ] 单元测试覆盖 time_resolver / 升级版 binder / 约束逻辑共 ≥ 15 个用例

## 📊 关联 KPI
- **K1**（绑定准确率 ≥ 70%）— P0 KPI，本里程碑核心目标
- **K2**（evidence 召回率 ≥ 80%）— P0 KPI
- **K3**（fallback 触发率 ≤ 30%）— P0 KPI
- **K8**（单元测试覆盖率）

## 🔗 依赖
- **前置**: M2a 全部（需要 NarrativeIR 数据结构 + 简化版 Binder + Scripting handler）
- **阻塞下游**: M3.4（Render 期望高质量 timeline.json）

---

## 任务清单（5 个）

### M2b.1 — evidence_keywords 反向检索算法

**目标**: 实现"给定 evidence_keywords + ASR sentences → 计算每个 ASR 句子的匹配得分"的算法，作为 time_resolver 的底层能力。

**关键设计决策**（**core, design.md §16.3**）:
- **算法选择**: MVP 用**字符级 Jaccard + IDF 加权**（不上 BM25，避免引入 sklearn / rank_bm25 依赖）
  - 备选：如果效果差，升级到 rank_bm25（可在 P1 风险出现时切换）
- **接口签名**:
  ```
  keyword_match_score(asr_text: str, keywords: list[str], idf_table: dict[str, float] | None = None) -> float
  ```
  - 返回 [0.0, 1.0] 归一化得分
  - keywords 全部命中 → 接近 1.0；零命中 → 0.0
- **IDF 表**: 由整段 ASR 构建（每个 ASR 句子作为一篇"文档"），降低高频虚词（"的"/"了"/"啊"等）权重
  - 缓存到 `data/{job_id}/asr_idf.json` 避免重复计算
- **关键词归一化**: 全部转小写 + 去除标点 + Unicode 兼容（`unicodedata.normalize('NFKC')`）
- **匹配模式**: 子串匹配（不做分词，避免 jieba 等额外依赖；中文场景子串足够）
- **阈值常量**: `THRESHOLD_MATCH_SCORE = 0.3`（M2b.4 调优）

**涉及文件**:
- Create: `src/autoclip/algo/keyword_match.py`
- Create: `tests/unit/test_keyword_match.py`

**测试策略**:
- 单元: 全命中得分接近 1.0 / 零命中 = 0.0 / IDF 加权降低虚词权重 / 大小写不敏感 / 标点不敏感

**验收标准**:
- [ ] 5+ 用例覆盖核心场景
- [ ] 对 100 个真实 ASR 样本，function 调用 < 100ms

**关联 KPI**: K2（评分函数是召回的基础） / K8
**依赖**: M2a.3（NarrativeSentence.evidence_keywords） → **阻塞**: M2b.2
**预估工时**: 1d

---

### M2b.2 — time_resolver：post-validation 反向定位算法

**目标**: 实现 design.md §16.3 的核心函数 `resolve_time_for_sentence()`，把 LLM 给的"段落级粗时间窗口 + 句级 evidence_keywords"精校为段级精确时间区间。

**关键设计决策**（**core, design.md §16.3 算法**）:
- **接口签名**:
  ```
  resolve_time_for_sentence(
      ir_sentence: NarrativeSentence,
      paragraph_hint: tuple[float, float],  # 段落粗时间窗口（来自 NarrativeIR）
      asr_sentences: list[ASRSentence],
      shots: list[Shot],
      *,
      threshold: float = 0.3,
      top_k: int = 3,
  ) -> ResolvedTime | None
  ```
  - 返回 `ResolvedTime(start_sec, end_sec, evidence_asr_ids: list[int], confidence: float, method: BindingMethod)`
  - 返回 None 表示需 fallback 到段落均分
- **算法步骤**:
  1. **窗口缩小**: 仅在 `paragraph_hint` 范围内的 asr_sentences 里检索（避免跨段误匹配）
  2. **评分**: 对窗口内每个 asr_sentence 调用 `keyword_match_score()`
  3. **过滤**: 保留得分 ≥ threshold 的候选
  4. **取 top-k**: 取得分最高的 top_k 个 asr_sentences
  5. **时间合并**: `start = min(c.start_sec for c in top)` / `end = max(c.end_sec for c in top)`
  6. **置信度**: `confidence = sum(top_k_scores) / k`（用于后续 self_evaluate）
- **fallback 决策**: top 为空 → 返回 None（让上层走段落均分兜底）
- **数据结构**:
  - `ResolvedTime`（dataclass，含 method 标记 EVIDENCE/EVIDENCE_LOWCONFIDENCE）
  - 复用 M2a.5 的 `BindingMethod` enum

**涉及文件**:
- Create: `src/autoclip/algo/time_resolver.py`
- Create: `tests/unit/test_time_resolver.py`

**测试策略**:
- 单元（用合成数据，无需真 LLM）:
  - 命中场景：keywords=["电话","喂"]，ASR 在 [10,12]s 出现"喂你好" → 返回 [10,12] +/- shot 边界
  - 跨段误匹配防护：keywords 在段外有命中，但段内无 → 仅取段内
  - 全无命中 → 返回 None
  - 多个候选合并：top_3 时间区间正确取 min/max
  - 置信度计算正确

**验收标准**:
- [ ] 5+ 算法用例通过
- [ ] 对合成场景，命中率 100%（人工设计的命中样本必须 resolve 出非 None）

**关联 KPI**: K1, K2, K3（核心算法 KPI 全部依赖此函数） / K8
**依赖**: M2b.1 → **阻塞**: M2b.3
**预估工时**: 1.5d

---

### M2b.3 — 绑定算法约束补齐 + 升级版 Binder

**目标**: 把 M2a.5 的 `bind_naively()` 升级为 `bind_with_evidence()`，集成 time_resolver，并加上约束逻辑。

**关键设计决策**（design.md §16.3 约束）:
- **新接口**:
  ```
  bind_with_evidence(
      ir: NarrativeIR,
      asr: ASRResult,
      shots: list[Shot],
      *,
      min_segment_sec: float = 0.8,
      max_shots_per_sentence: int = 5,
      allow_cross_paragraph_reuse: bool = False,
  ) -> BindingResult
  ```
- **绑定流程（每个 NarrativeSentence）**:
  1. 提取 paragraph_hint = (paragraph.approx_source_start_sec, .end_sec)
  2. 调 `resolve_time_for_sentence()` → 拿 ResolvedTime 或 None
  3. 若 None → fallback 到段落均分（method = FALLBACK_UNIFORM，统计 fallback_count++）
  4. 应用约束:
     - **最小镜头时长 0.8s**：duration < 0.8 → 向后扩展到 ≥ 0.8（不超出 paragraph_hint）
     - **单句最多 5 镜头**：source_shot_ids 超过 5 → 截断保留中间连续 5 个
     - **跨段不复用**：维护 `used_shot_ids: set[int]`，跨 paragraph 时检查冲突，冲突就跳过该 shot（除非 allow_cross_paragraph_reuse=True，作为 escape valve）
- **升级 BindingResult 字段**:
  - `fallback_count` 真实统计（M2a 里恒为 0）
  - 新增 `evidence_recall_count`（evidence_keywords 非空且 resolve 成功的句子数）→ K2 计算依据
  - 新增 `cross_paragraph_skip_count`（用于诊断）
- **保留 bind_naively** 作为 baseline，便于 A/B 对比

**涉及文件**:
- Modify: `src/autoclip/algo/greedy_binder.py`（新增 bind_with_evidence；保留 bind_naively）
- Modify: `tests/unit/test_greedy_binder.py`（增加约束逻辑用例）

**测试策略**:
- 单元: 单句 < 0.8s 自动扩展 / 超过 5 镜头自动截断 / 跨段冲突时跳过 shot / fallback_count 正确累计 / evidence_recall_count 正确

**验收标准**:
- [ ] 6+ 新用例通过
- [ ] M2a.5 原有用例仍然全部通过（兼容性）

**关联 KPI**: K1, K3 / K8
**依赖**: M2b.2 → **阻塞**: M2b.4 / M2b.5
**预估工时**: 1d

---

### M2b.4 — KPI 评估脚本：人工打标 + 自动统计

**目标**: 建立可重复使用的 KPI 评估管线，为 M2b/M3/M4 验收提供数据依据。

**关键设计决策**:
- **`scripts/manual_label.py`**:
  - CLI: `python -m scripts.manual_label --job-id 1 --sample-size 50`
  - 流程：随机抽 50 个 segment → 在终端依次显示 `sentence_text` + 原片该时间段的关键帧路径 → 人工输入 `y/n/maybe`（合理/不合理/拿不准）
  - 输出: `data/jobs/{id}/kpi_labels.json`
- **`scripts/benchmark.py`**:
  - 输入: `kpi_labels.json` + `timeline.json`
  - 自动计算并输出（写 stdout + 落盘 `kpi_report.json`）:
    - **K1 绑定准确率** = `count(label=='y') / total_labeled`
    - **K2 evidence 召回率** = `binding.evidence_recall_count / binding.total_count`（M2b.3 字段）
    - **K3 fallback 触发率** = `binding.fallback_count / binding.total_count`
    - 分布: 各 BindingMethod 的占比
- **关键帧采样**：依赖 PySceneDetect 的 `save_images()`，仅在评估期间生成（M3 之后清理，零知识架构）
- **退出码**: K1 < 0.7 或 K2 < 0.8 或 K3 > 0.3 → 退出码 1（CI 可拦截）

**涉及文件**:
- Create: `scripts/__init__.py`
- Create: `scripts/manual_label.py`
- Create: `scripts/benchmark.py`
- Create: `tests/unit/test_benchmark.py`（仅测纯函数，不测交互式打标）

**测试策略**:
- 单元（benchmark.py 纯函数）:
  - 给定固定 labels.json + binding_stats，验证 K1/K2/K3 计算正确
  - 退出码逻辑：阈值上下 +/- 0.01 边界

**验收标准**:
- [ ] benchmark 单元测试通过
- [ ] 在 1 部短片上手动跑完整流程（label → benchmark → 输出 K1/K2/K3 数字），数字合理

**关联 KPI**: K1, K2, K3 评估能力本身（决定 milestone 是否可验收） / K8
**依赖**: M2b.3 → **阻塞**: M2b.5（依赖评估反馈做 prompt 调优）
**预估工时**: 1d

---

### M2b.5 — Prompt v2 调优 + Scripting handler 切换 + Milestone 验收

**目标**: 基于 M2b.4 的 KPI 反馈，对 narrative IR prompt 做 v2 调优；把 Scripting handler 从 `bind_naively` 切到 `bind_with_evidence`；跑通 3 部作品的端到端验收。

**关键设计决策**:
- **Prompt v2 调优方向**（design.md §16.3 关键约束）:
  - 强化 evidence_keywords 要求：必须 2-4 个，必须是 ASR 中可能出现的具体词语（不接受抽象概念）
  - few-shot 扩展到 3 个例子覆盖 3 类作品：电影 / 电视剧 / 动漫
  - 段落 approx_source_*_sec 必须严格落在视频范围内（增加约束语句）
- **Few-shot 例子文件结构**:
  - `prompts/style_presets/plot_summary.py` 新增 `FEW_SHOT_EXAMPLES: list[dict]`
  - 每个例子含 `genre / asr_excerpt / expected_ir_json`
  - prompt builder 根据 plot_outline.genre 优先选同类型 few-shot（fallback 到全部 3 个）
- **Scripting handler 切换**:
  - `pipeline/scripting.py` 中替换 `bind_naively` 为 `bind_with_evidence`
  - 通过环境变量 `AUTOCLIP_BINDER=naive` 可回退（debug 用）
  - 在 timeline.json 里追加 `binder_version: "v2-evidence"` 字段
- **Milestone 验收流程**:
  1. 准备 3 部不同类型短片（5min 各，避免 LLM cost 过高）
  2. 跑完整 Scripting → 各产出 timeline.json
  3. `manual_label.py` 各打标 50 句
  4. `benchmark.py` 输出 K1/K2/K3
  5. 不达标 → 调 prompt 或 threshold（M2b.1 的 `THRESHOLD_MATCH_SCORE`）→ 重跑

**涉及文件**:
- Modify: `src/autoclip/prompts/style_presets/plot_summary.py`（few-shot 扩展为 3 个）
- Modify: `src/autoclip/prompts/narrative_ir.py`（few-shot 选择逻辑）
- Modify: `src/autoclip/pipeline/scripting.py`（切换 binder）
- Create: `tests/integration/test_binder_switch.py`（验证两种 binder 都能跑通）
- Modify: 总控文档 `2026-05-04-autoclip-plan.md` 第 4 节 KPI 跟踪表（填入 K1/K2/K3 实测值）

**测试策略**:
- 集成: AUTOCLIP_BINDER 环境变量切换两种 binder 都能产出合法 timeline.json
- E2E 手跑: 3 部短片完整 KPI 评估

**验收标准**:
- [ ] 3 部短片的 K1 平均 ≥ 70%
- [ ] 3 部短片的 K2 平均 ≥ 80%
- [ ] 3 部短片的 K3 平均 ≤ 30%
- [ ] 总控文档 KPI 表已更新
- [ ] timeline.json 含 `binder_version` 字段

**关联 KPI**: K1, K2, K3 全部目标值达成 — **本 milestone 的核心验收门禁**
**依赖**: M2b.4 → **阻塞**: M3 全部
**预估工时**: 1.5d（含调优迭代时间）

---

## M2b 总工时估算
| 任务 | 工时 |
|---|---|
| M2b.1 keyword_match | 1.0d |
| M2b.2 time_resolver | 1.5d |
| M2b.3 升级版 Binder | 1.0d |
| M2b.4 KPI 评估脚本 | 1.0d |
| M2b.5 Prompt v2 + 验收 | 1.5d |
| **总计** | **6.0d**（控制在 W3 内，含调优迭代）|

## M2b 完成时的 PR 描述模板
```
✨feat: M2b - Scripting robustness with narrative IR + post-validation
    - T2b.1 keyword_match algorithm (Jaccard + IDF, no extra deps)
    - T2b.2 time_resolver: post-validation reverse lookup
    - T2b.3 bind_with_evidence: constraints + fallback tracking
    - T2b.4 manual_label.py + benchmark.py KPI tooling
    - T2b.5 Prompt v2 (3 few-shots per genre) + binder switch
    - KPI achieved: K1=XX% K2=XX% K3=XX% (filled at acceptance)
```

## ⚠️ M2b 失败兜底
若 M2b.5 验收 K1 < 70%：
1. **路径 A**（推荐）：占用 W6 buffer 继续调 prompt + threshold
2. **路径 B**：临时降低 K1 目标到 60%（需用户决策；MVP 接受度边界）
3. **路径 C**：升级 keyword_match 到 BM25（引入 rank_bm25 依赖，工作量 +0.5d）

不可接受的方案：跳过 KPI 评估（K1-K3 是 P0，必须达标才能进入 M3）

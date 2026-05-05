# M2b — Scripting 鲁棒性 + narrative IR + KPI 评估（Week 3）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §16.3（核心算法升级） / §17.1 / §18.2

---

## ⚠️ v0.7 修订提示（2026-05-05, Session 20 brainstorming Q6=E 决议）

**M2b 已被拆分**，本文件原始范围（5 任务 / 6.2d）按以下方式重新分配：

| 原 M2b 范围 | v0.7 后归属 | 说明 |
|---|---|---|
| **M2b-light**（narrative_intent 字段路由 binder + KPI 框架 + 3-5 部评估） | ✅ **已并入 [M2a-fix.5](./M2a-fix-narrative-style.md)** | 2.1d，与 M2a 二创风格修正合并交付 |
| **M2b-full**（BM25 反向检索 + time_resolver + bind_with_evidence + post-validation + Prompt v2） | ⏳ **保留在本文件**（M2b.1-M2b.5），但改为**条件启动** | 4d；仅当 M2a-fix.5 末尾决策报告建议启动时执行；否则整个 M2b 跳过 |

**判定路径**:
```
M2a-fix.5 末尾决策报告
    ├── 建议启动 M2b-full → 执行本文件 M2b.1-M2b.5（4d 实施）
    └── 建议不启动      → 跳过本文件，直接进 M3
```

**启动条件**（design.md §17.5 显式定义，待 M2a-fix.1 落地）:
- ✅ 启动: K1 < 50% **且** 业务方明确要求精确绑定（如 M3 Render 阶段反馈"画面对不上严重影响产品"）
- ❌ 不启动: K1 ≥ 50% **或** narrative_intent 路由（M2a-fix.5 已实现）已能覆盖 80%+ 用例

**v0.7 修订后本文件状态**: 5 任务定义保留作为 M2b-full 实施时的技术参考，但**进度计数归 0/1**（plan.md 主控视角下 M2b 整体仅算 1 个待决策任务）；M2b.1 BM25 / M2b.2 time_resolver / M2b.3 bind_with_evidence / M2b.4 Prompt v2 evidence_keywords 加回 / M2b.5 KPI 评估，5 项内容描述本身**不变**，仅启动时机改为条件触发。

---

## 🎯 Milestone 目标
将 M2a 的 baseline 绑定（按 paragraph hint 均分）升级为 **narrative IR + post-validation 两阶段算法**：用 `evidence_keywords` 反向检索 ASR 定位精确时间窗口，并补齐绑定约束（最小镜头时长、单句最多镜头数、跨段不复用）。建立 KPI 评估脚本，跑通 3 部不同类型作品的人工打标，量化绑定准确率。

## ✅ Milestone 验收
- [ ] 3 部不同类型作品（实拍剧情 / 实拍动作 / 动漫）各跑一次完整 Scripting
- [ ] 每部各 50 句人工打标后，绑定准确率 **K1 ≥ 70%**
- [ ] evidence 召回率 **K2 ≥ 80%**（LLM 输出非空 evidence_keywords 的比例）
- [ ] fallback 触发率 **K3 ≤ 30%**（resolve 返回 None 的比例）
- [ ] 单元测试覆盖 time_resolver / 升级版 binder / 约束逻辑共 ≥ 15 个用例
- [ ] **v0.6 修订承接（responsibility passthrough）**：M2a v0.6 引入的 timeline.json `target_duration_sec_estimate` 字段在 M2b 阶段**继续保留为预估**（M2b 不动 estimate→真值的回填），真正回填责任在 **M3.2 TTS 实跑**——本 milestone 仅需保证 binder_with_evidence 升级**不破坏** estimate 字段的字数加权计算（即 M2b.3 binder 升级时同步在序列化层保留 estimate 计算逻辑，不要回归到只有 source_*_sec 的 timeline.json）

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

**关键设计决策**（**core, design.md §16.3；adhoc plan-3 选型修订 2026-05-04**）:
- **算法选择**：MVP 直接采用 **rank_bm25**（`rank_bm25.BM25Okapi`），不再走原 plan 的字符级 Jaccard + IDF 简化路径
  - **决策依据**：原 plan 评估 K2 ≥ 80% 风险时，子串匹配在"电话/手机"、"喂/你好"等近义词召回上偏弱；rank_bm25 是纯 Python 单文件实现（无 C 扩展依赖、无 sklearn），引入成本极低，但比手撸 Jaccard 在短查询多关键词场景上稳定性高一个量级
  - **依赖声明**：`pyproject.toml` 追加 `rank-bm25 = "^0.2.2"`（与 M2a.1 dashscope/tenacity/pydantic 同 commit 提交，避免分散）
  - 兜底：如 BM25 在中文短查询（2-4 字 keywords）上效果反而退化，可加 `unicodedata` 归一化 + 字符 n-gram tokenizer 二次包装（不切换算法本身）
- **接口签名**:
  ```
  keyword_match_score(
      asr_text: str,
      keywords: list[str],
      bm25_index: BM25Okapi | None = None,  # None 表示一次性 ad-hoc 计算
  ) -> float
  ```
  - 返回 [0.0, 1.0] 归一化得分（BM25 raw score 经 `min(score / max_score_in_corpus, 1.0)` 归一）
  - keywords 全部命中 → 接近 1.0；零命中 → 0.0
- **BM25 语料构建**：把整段 ASR 的每个句子作为一篇"文档"，预先 build `BM25Okapi(tokenized_corpus)` 一次复用
  - tokenizer：中文场景用**字符级 split**（不引 jieba，与 BM25 配合即可达到 evidence_keywords 召回需求）
  - 缓存到 `data/{job_id}/asr_bm25_index.pkl`（pickle 序列化 BM25Okapi 实例）避免重复计算
- **关键词归一化**：全部转小写 + 去除标点 + Unicode 兼容（`unicodedata.normalize('NFKC')`）
- **阈值常量**: `THRESHOLD_MATCH_SCORE = 0.3`（M2b.4 调优；BM25 归一化后阈值意义与 Jaccard 一致）

**涉及文件**:
- Modify: `pyproject.toml`（追加 `rank-bm25 = "^0.2.2"`，可与 M2a.1 同 commit 一起 install）
- Create: `src/autoclip/algo/keyword_match.py`
- Create: `tests/unit/test_keyword_match.py`

**测试策略**:
- 单元: 全命中得分接近 1.0 / 零命中 = 0.0 / BM25 长文档惩罚降低虚词权重 / 大小写不敏感 / 标点不敏感 / pickle 缓存往返一致

**验收标准**:
- [ ] 5+ 用例覆盖核心场景（含 1 个 pickle 缓存往返用例）
- [ ] 对 100 个真实 ASR 样本，function 调用 < 100ms（含 BM25 index 命中缓存路径）

**关联 KPI**: K2（评分函数是召回的基础） / K8
**依赖**: M2a.3（NarrativeSentence.evidence_keywords） → **阻塞**: M2b.2
**预估工时**: 1.2d（原 1.0d；adhoc plan-3 选型升级 +0.2d 用于 BM25 集成 + pickle 缓存测试）

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
  - **v0.6 修订（adhoc self-review, 2026-05-05）— 加回 evidence_keywords prompt 输出要求**：
    - **背景**：M2a v0.6 修订把 evidence_keywords 从 narrative_ir prompt 删除（因 M2a baseline 不消费、是 dead data）；M2b.5 prompt v2 必须**重新加回** schema + 指令，作为 M2b.1 (BM25) + M2b.2 (time_resolver) 的输入
    - **prompt 改动点**：`prompts/narrative_ir.py` 的 `SYSTEM_PROMPT_TEMPLATE` schema 块加回 `"evidence_keywords": [string]` 字段；"关键约束" 加回第 2 条 "evidence_keywords 是从 ASR 文本中提取的关键词，用于反向校验镜头"；强化措辞同上述"必须 2-4 个 / 必须是 ASR 中可能出现的具体词语"
    - **代码改动量**：~5 行 prompt 文本（恰好 v0.6 在 M2a 删除的那部分），无新增模块；NarrativeSentence dataclass / parse 逻辑 / Pydantic raw model 全部不动（M2a v0.6 已保留 default_factory=list，本次只是从 LLM 端开始填值）
    - **测试影响**：M2b.1 / M2b.2 单元测试用例的 `NarrativeSentence(evidence_keywords=[...])` mock 数据可以不再用 placeholder 空列表
    - **token 预算回升**：v0.6 修订 1 删除 evidence 后输出系数从 120 → 80；M2b.5 加回后系数应回升至 ~120；`narrative_ir_max_tokens` 计算公式同步更新（`target_sentences * 120 + 1000`，新增 v0.6 修订项写在 M2b.5 实现 task 备注）
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
- [ ] **v0.6 新增**：narrative_ir prompt 加回 evidence_keywords schema + 指令；`narrative_ir_max_tokens` 计算公式系数从 80 回升至 120（与 M2a v0.6 修订 1 的双闸门公式同步）

**v0.6 修订附注（adhoc self-review, 2026-05-05）— evidence_keywords 责任承接**：
- M2a v0.6 修订 3 把 evidence_keywords 从 M2a prompt 删除（dead data 治理），本 task 是配套的"加回点"——M2b.5 实现时必须先恢复 prompt 输出要求，否则 M2b.1 / M2b.2 拿到的 `NarrativeSentence.evidence_keywords` 全是空列表，BM25 + time_resolver 整链路失效
- 实施顺序约束：M2b.5 prompt v2 改写**必须早于** M2b.1 / M2b.2 的集成测试（否则集成测试用 v1 prompt 跑出空 evidence，KPI 永远拿不到目标）
- 代码改动点收敛：`prompts/narrative_ir.py` SYSTEM_PROMPT_TEMPLATE schema 块加回 1 行 `"evidence_keywords": [string]` + 关键约束区加回 1 行说明 + `_invoke_llm_with_repair` 的 max_tokens 系数从 80 → 120（与 M2a `scripting.py` 双闸门公式同处更新）

**关联 KPI**: K1, K2, K3 全部目标值达成 — **本 milestone 的核心验收门禁**
**依赖**: M2b.4 → **阻塞**: M3 全部
**预估工时**: 1.5d（含调优迭代时间）

---

## M2b 总工时估算
| 任务 | 工时 |
|---|---|
| M2b.1 keyword_match (BM25) | 1.2d（adhoc 升级 +0.2d）|
| M2b.2 time_resolver | 1.5d |
| M2b.3 升级版 Binder | 1.0d |
| M2b.4 KPI 评估脚本 | 1.0d |
| M2b.5 Prompt v2 + 验收 | 1.5d |
| **总计** | **6.2d**（W3 5 工作日 + 0.8d buffer 占用 0.2d；剩余 0.6d 用于 prompt 调优迭代）|

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

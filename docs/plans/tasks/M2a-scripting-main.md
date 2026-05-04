# M2a — Scripting 主链路（Week 2）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §8 / §16.3 / §17.1

## 🎯 Milestone 目标
搭建 LLM Provider 抽象 + 通义千问 qwen-plus 实现；端到端跑通"读 shots.json + asr.json → 输出 timeline.json"的 Scripting 流程。本里程碑只做**最简版本**——不做 evidence_keywords 反向校验，仅按 paragraph_hint 时间区间贪心分配镜头。后续 M2b 升级。

## ✅ Milestone 验收
- [ ] 对 M1 跑通的 1 部短片，触发 Scripting stage 后产出 `timeline.json`
- [ ] timeline.json 结构正确（plot_outline + narrative_ir + binding_stats + segments）
- [ ] 每个 segment 都关联到至少 1 个 shot id
- [ ] 肉眼检查：50% 以上句子的镜头匹配是合理的
- [ ] LLM 调用失败时有 retry 3 次 + JSON repair 兜底
- [ ] Scripting stage 端到端 ≤ 4min（90min 视频）

## 📊 关联 KPI
- **K1, K2, K3**（绑定准确率/召回率/fallback）：M2a 不做严格量化，留给 M2b 升级
- **K6**（端到端耗时）：本 milestone Scripting 部分应 ≤ 4min/90min
- **K8**（单元测试覆盖率）：narrative IR 解析 / 简化绑定 / JSON repair 共 ≥ 10 个用例

## 🔗 依赖
- **前置**: M1 全部（需要 shots.json + asr.json）
- **阻塞下游**: M2b 全部 / M3.4（Render 需要 timeline.json）

---

## 任务清单（6 个）

### M2a.1 — LLMProvider 抽象 + QwenProvider 实现

**目标**: 定义 LLM 接口契约，实现通义千问 qwen-plus Provider（design.md ADR-001）。

**关键设计决策**:
- **LLMProvider 抽象**: 单方法 `chat(messages, *, temperature, max_tokens, response_format) -> LLMResponse`
- **数据结构**:
  - `LLMMessage(role: Literal['system','user','assistant'], content: str)` — `__post_init__` 校验 role
  - `LLMResponse(content, input_tokens, output_tokens, model, raw?)` + `total_tokens` 属性
- **QwenProvider**:
  - 默认 model = `qwen-plus`
  - 通过 dashscope SDK 调用，`result_format="message"`
  - 支持 JSON mode：`response_format={"type":"json_object"}`
  - tenacity retry 3 次（指数退避，min=2s max=20s），仅对 RuntimeError 重试
  - 失败抛 `RuntimeError(f"Qwen API failed: code={code} msg={msg}")`
- **依赖声明**（**G1, 2026-05-04 adhoc 补充**）：M2a 启动第一步必须先在 `pyproject.toml` 的 `[tool.poetry.dependencies]` 段追加：
  - `dashscope = "^1.20"`（通义千问 SDK，QwenProvider 直接依赖）
  - `tenacity = "^9.0"`（HTTP 层 retry 装饰器，QwenProvider + M2a.4 retry_with_repair 共用）
  - `pydantic = "^2.0"`（M2a.2 `_PlotOutlineRaw` Pydantic 校验层，与 pydantic-settings 1.x 共存）
  - 完成后跑 `poetry lock --no-update && poetry install` 锁版本，并提交 `pyproject.toml` + `poetry.lock` 一起 commit（避免后续 task 因依赖缺失返工）

**涉及文件**:
- Modify: `pyproject.toml`（依赖声明 + `poetry.lock` 同步）
- Create: `src/autoclip/providers/llm/{__init__,base,qwen}.py`
- Create: `tests/unit/test_llm_base.py`
- Create: `tests/integration/test_qwen_provider.py`（默认 skip，需 `RUN_INTEGRATION=1`）

**测试策略**:
- 单元: role 校验 / dataclass 字段 / mock provider 实现接口可继承
- 集成（手动）: 真实调用 qwen-plus 问 "1+1=?"，验证返回包含 "2" + token 计数 > 0

**验收标准**:
- [ ] mock provider 测试 ≥ 3 个用例通过
- [ ] 集成测试本地手跑通过
- [ ] JSON mode 在 M2a.3 实测能稳定返回合法 JSON（≥ 80% 不需 repair）

**关联 KPI**: K8
**依赖**: M1.1 → **阻塞**: M2a.2 / M2a.3
**预估工时**: 0.5d

---

### M2a.2 — Plot Outline 提取（Prompt v1，v0.4 含角色推断）

**目标**: 设计并实现"剧情大纲提取" prompt，把整段 ASR + 视频时长 → 标题猜测 / 类型 / **角色卡（路径2 LLM 推断）** / 3-5 个关键幕。

> **v0.4 变更说明**：design.md §22 ADR-009 决定 MVP 角色信息走 LLM 文本推断（路径 2），不做声纹。本任务把 `main_characters` 从 v0.3 的 `list[str]` 升级为结构化角色卡 `list[Character]`，并在 `KeyAct` 增加 `involved_characters` 字段，为 M2a.3 narrative IR 生成提供"哪些角色出现在哪一幕"的上下文。

**关键设计决策**:
- **数据结构**（v0.4 升级）:
  - `Character(role: str, name: str | None, description: str)` —— `role` 是稳定标签（"男主"/"女主"/"反派 A"/"导师"），`name` 仅在对白明确出现时填，`description` 一句话画像
  - `KeyAct(act_idx, name, approx_start_sec, approx_end_sec, summary, involved_characters: list[str])` —— `involved_characters` 引用 Character.role 列表
  - `PlotOutline(title_guess, genre, main_characters: list[Character], plot_summary, key_acts)` + `to_dict()`
- **Pydantic 校验层**: `_CharacterRaw` / `_KeyActRaw` / `_PlotOutlineRaw` 用于严格校验 LLM 输出 schema，再转 dataclass 给业务层
- **Prompt 结构**:
  - System: "影视剧情分析专家 + 角色识别专家"，强调 JSON-only 输出，禁止 markdown fence
  - User: 注入 `asr_text`（截断 30k 字符）+ `duration_sec` + JSON Schema 模板（含 Character schema）
  - **角色推断指令**（关键）：
    - "请基于对白中的称呼（如「爸」「师父」「陛下」「X老师」「队长」）和上下文逻辑，推断主要角色的功能性身份（男主/女主/反派/导师/...）"
    - "如果对白中明确出现了某个角色的姓名（被他人喊出），请填入 name 字段；否则 name 留 null，仅填 role"
    - "main_characters 数量限定 2-6 个，仅列对剧情推动有作用的角色"
    - "key_acts[].involved_characters 必须是 main_characters[].role 中已定义的值"
- **关键约束**:
  - key_acts 数量限定 3-5 个
  - approx_*_sec 必须基于对白时间戳推算，不能超出视频总时长
  - main_characters 2-6 个，involved_characters 引用一致性校验
- **解析层**: `parse_plot_outline_response(raw)` 必须支持 markdown fence 包裹（LLM 经常这样输出）
- **fence 正则**: `^```(?:json)?\s*(.*?)\s*```$` (DOTALL)
- **降级策略**：若 LLM 未输出 `main_characters` 或为空，degrade 为 `[]`（不抛错），下游 narrative IR prompt 会回退到不含角色的旧逻辑

**涉及文件**:
- Create: `src/autoclip/prompts/{__init__,plot_outline}.py`
- Create: `tests/unit/test_plot_outline_prompt.py`
- Create: `tests/integration/test_plot_outline_e2e.py`

**测试策略**:
- 单元: build_messages 包含 ASR 文本和时长 / 解析 valid JSON / 解析带 markdown fence 的 JSON / 解析 schema mismatch 抛 ValueError / **Character 字段往返序列化** / **involved_characters 引用一致性校验**（不在 main_characters 中应抛 ValueError） / **main_characters 为空时 degrade 不抛错**
- 集成（手动）: 真实 LLM 跑短片 ASR，肉眼检查输出合理性 + 角色卡是否符合直觉（如《喜剧之王》应识别出男主/女主/反派老板等）

**验收标准**:
- [ ] 6+ 解析用例通过（含 v0.4 新增的 3 个角色相关用例）
- [ ] 真实 LLM 调用 5 次成功率 ≥ 80%（剩余 20% 由 retry 兜底）
- [ ] 真实样片输出的 main_characters 角色 role 字段命中率 ≥ 80%（人工评估）

**关联 KPI**: K8（解析层覆盖）+ ADR-009 路径 2 验证基线
**依赖**: M2a.1 → **阻塞**: M2a.3 / M2a.6
**预估工时**: 1d（v0.4 prompt 增强不增工时，仅微调 schema + few-shot）

---

### M2a.3 — Narrative IR 数据模型 + plot_summary 风格 prompt

**目标**: 定义 v0.3 §16.3 核心数据结构 NarrativeIR，并实现"剧情速览"风格的解说稿生成 prompt。

**关键设计决策**（**core，design.md §16.3**）:
- **NarrativeIR 三层结构**:
  - `NarrativeSentence(sentence_idx, text, evidence_keywords: list[str])`
  - `NarrativeParagraph(paragraph_idx, topic, approx_source_start_sec, approx_source_end_sec, sentences: list)`
  - `NarrativeIR(paragraphs: list)` + `iter_sentences()` / `total_sentences()` / `to_dict()`
- **为什么不让 LLM 直接输出绝对时间区间**:
  - LLM 容易幻觉具体时间数字（实测错误率 30-50%）
  - 改让 LLM 输出"段落级粗时间窗口 + 句级 evidence_keywords"，由 M2b 的 time_resolver 反向校验
- **plot_summary 风格预设**:
  - 第三人称客观叙述，避免主观评论
  - 单句 8-15 字（便于 TTS 朗读）
  - 不用感叹号 / 反问句
  - **使用角色称呼替代含糊指代**（v0.4 新增，配合 ADR-009 路径 2）：
    - 优先使用 PlotOutline.main_characters 中的 role 标签（"男主"/"女主"/"反派"）
    - 对白中明确出现 name 时使用 name（如"周星驰对柳飘飘说..."）
    - **禁止**使用"有人"、"某人"、"一个人"等含糊词（除非角色信息缺失）
  - 文件位置: `prompts/style_presets/plot_summary.py`，导出 `STYLE_NAME / STYLE_DESCRIPTION / FEW_SHOT_EXAMPLE`
- **Prompt 结构**:
  - System: 注入 STYLE_DESCRIPTION + 总句数约束（target_duration_sec ÷ 6 ≈ N±5 句）+ 角色使用规约
  - User: 注入 plot_outline（**含 main_characters 角色卡**） + asr_with_timestamps + few-shot example（**含角色称呼示范**） + 严格 JSON schema
  - **few-shot example 强化**（v0.4）：至少包含 1 个示范角色称呼的句子，如"男主蹲在巷口的台阶上，望着远方失神。"
- **截断保护**: asr_with_timestamps 上限 40k 字符
- **角色信息缺失 fallback**：若 PlotOutline.main_characters 为空（M2a.2 degrade 路径），prompt 中省略角色规约段落，回退到 v0.3 行为

**涉及文件**:
- Create: `src/autoclip/algo/{__init__,narrative_ir}.py`
- Create: `src/autoclip/prompts/{narrative_ir}.py`
- Create: `src/autoclip/prompts/style_presets/{__init__,plot_summary}.py`
- Create: `tests/unit/test_narrative_ir_parse.py`

**测试策略**:
- 单元: parse 合法 IR / parse schema 错误抛 ValueError / iter_sentences 遍历正确 / fence 包裹 / Pydantic 校验
- M2b/M4 阶段补集成测试

**验收标准**:
- [ ] 3+ parse 用例通过
- [ ] NarrativeIR.to_dict() 序列化往返一致

**关联 KPI**: K8（建立解析层基线）
**依赖**: M2a.1 + M2a.2 → **阻塞**: M2a.5 / M2b.1
**预估工时**: 1d

---

### M2a.4 — JSON repair + retry 机制（LLM 输出鲁棒性）

**目标**: 提供通用 JSON 修复函数 + LLM 调用 retry 装饰器，处理 LLM 输出的常见失误。

**关键设计决策**:
- **`try_repair_json(raw) -> Any`**: 失败抛 `RepairFailedError`，处理：
  1. Markdown fence 剥离（```json ... ``` / ``` ... ```）
  2. 抽取首个 `{...}` 或 `[...]` 块（处理 LLM 在 JSON 前后加解释文字）
  3. 修复 trailing comma（`,}` 或 `,]`）
  4. 单引号转双引号（仅简单场景）
  5. 多策略候选解析，命中即返回
- **`retry_with_repair(max_attempts=3, initial_delay=1, max_delay=10)`**:
  - 指数退避
  - 捕获所有 Exception 并记录 warning
  - 与 tenacity 互补：tenacity 用于 HTTP 层，本装饰器用于 LLM 输出解析层
- **不引入新依赖**: 仅用 stdlib + loguru

**涉及文件**:
- Create: `src/autoclip/utils/{json_repair,retry}.py`
- Create: `tests/unit/test_json_repair.py`
- Create: `tests/unit/test_retry_decorator.py`

**测试策略**:
- 单元（json_repair）: fence with/without lang / trailing comma / 单引号 / 前后多余文字 / 不可救则抛
- 单元（retry）: 第一次成功 / 第二次成功 / 三次都失败抛原异常

**验收标准**:
- [ ] 7+ json_repair 用例通过
- [ ] 3+ retry 用例通过

**关联 KPI**: K8
**依赖**: M1.1 → **阻塞**: M2a.6
**预估工时**: 0.5d

---

### M2a.5 — 简化版绑定算法（按 paragraph_hint 时间区间贪心）

**目标**: 实现 M2a baseline 绑定算法 — 仅按 NarrativeIR.paragraphs 的时间窗口均分句子，匹配落入窗口的 shot。

**关键设计决策**（**baseline，M2b 会替换**）:
- **数据结构**:
  - `BindingMethod` enum: `HINT_UNIFORM` (M2a) / `EVIDENCE` (M2b) / `FALLBACK_UNIFORM`
  - `BoundSegment(paragraph_idx, sentence_idx, sentence_text, source_start_sec, source_end_sec, source_shot_ids: list[int], binding_method)` + `duration_sec` 属性
  - `BindingResult(segments, fallback_count, total_count)` + `fallback_ratio` 属性（K3 直接关联）
- **`bind_naively(ir, shots, min_segment_sec=0.8) -> BindingResult`**:
  1. 视频总时长 = `shots[-1].end_sec`
  2. 对每个 paragraph: clamp 边界到 [0, video_end]
  3. 段内句子均分时间窗口（per = (p_end - p_start) / n_sentences）
  4. 单段最小时长保障：< min_segment_sec 时扩展（不超出段落边界）
  5. shot 匹配：与 [seg_start, seg_end] 重叠的 shot ids 全部纳入
  6. 极端 fallback：找不到重叠 shot → 取 start_sec 最近的 shot
- **`BindingMethod` enum 完整成员**（**adhoc plan-1 补充**）:
  - `HINT_UNIFORM` — M2a baseline，按 paragraph_hint 均分，本 task 唯一会写入的值
  - `EVIDENCE` — M2b post-validation 命中且 confidence 高（M2b.2 写入）
  - `EVIDENCE_LOWCONFIDENCE` — M2b post-validation 命中但 top_k 平均得分 < 0.5（M2b.2 写入；本枚举值在 M2a.5 预留是为了 M2b.2 升级时不需要二次扩 enum，避免 timeline.json 跨版本兼容性踩坑）
  - `FALLBACK_UNIFORM` — M2b resolve 返回 None 时回退到 paragraph 均分（M2b.3 写入）
- **不做的事**（留给 M2b）:
  - 不用 evidence_keywords 反向检索
  - 不做 BM25 / 字符级匹配
  - 不区分 fallback 和正常 binding（fallback_count = 0）

**涉及文件**:
- Create: `src/autoclip/algo/greedy_binder.py`
- Create: `tests/unit/test_greedy_binder.py`

**测试策略**:
- 单元: 段落 [10,40] 3 句 → 每句 10s 区间正确 / paragraph 越界 clamp / 单段 < 0.8s 时扩展逻辑

**验收标准**:
- [ ] 3+ 算法用例通过
- [ ] BindingResult.fallback_ratio 字段存在（M2b 升级时填充）

**关联 KPI**: K8（baseline）
**依赖**: M1.7 + M2a.3 → **阻塞**: M2a.6
**预估工时**: 1d

---

### M2a.6 — Scripting Stage handler — 串联 LLM + 绑定 + Timeline 序列化

**目标**: 实现 Scripting stage handler，把前 5 个 task 的产物组装成端到端流程，并注册到 PipelineRunner。

**关键设计决策**:
- **handler 流程**（design.md §8）:
  1. 加载 shots.json + asr.json
  2. 计算 full_text 和 timestamped_text
  3. LLM 调用 1: plot outline（temperature=0.3, max=2000, JSON mode）
  4. LLM 调用 2: narrative IR（temperature=0.7, max=8000, JSON mode）
  5. 简化绑定（M2a.5）
  6. 序列化 timeline.json
- **timeline.json schema**:
  ```
  {
    "plot_outline": {...},
    "narrative_ir": {...},
    "binding_stats": {total_segments, fallback_count, fallback_ratio},
    "segments": [{order_idx, paragraph_idx, sentence_idx, sentence_text,
                  source_start_sec, source_end_sec, duration_sec,
                  source_shot_ids, binding_method}]
  }
  ```
- **LLM 调用容错链**:
  1. tenacity 处理 HTTP 层失败（M2a.1 已实现）
  2. retry_with_repair 处理 JSON 解析失败（M2a.4）
  3. parse 失败 → try_repair_json → 重 parse；仍失败抛 ValueError → retry_with_repair 再试
- **进度上报**: 0.05 / 0.3 (plot done) / 0.7 (IR done) / 0.9 (bind done) / 1.0
- **Cancel 检查点**: 在每次 LLM 调用前
- **style_preset 注入方式**（**adhoc plan-4 决策**）：M2a.6 **不改 `JobStateFile.init` schema**（避免 M1 baseline 漂移）。改用环境变量 `AUTOCLIP_STYLE_PRESET=plot_summary`（默认值）由 scripting handler 启动时直接 `os.environ.get(...)` 读取。state.json schema 改造推迟到 **M2b.5**（届时已经有 binder_version 字段升级，可一并做 schema bump，集中迁移成本）。
  - **设计 rationale**：M1 e2e 验收完成前任何 state schema 变动都会让"M1 收工"成为浮动目标；环境变量是零侵入的兜底通道，M2b.5 schema 升级时 M2a 的 env 入口可保留作为 debug fallback。
- **LIM#10 提醒**（**adhoc G2 补充, 2026-05-04 .context tech_debt**）：实现 scripting handler 后若**单跑** `pytest tests/unit/test_runner.py` 出现 `IngestError: raw directory missing` 是已知问题（LIM#10：`_stage_entrypoint` 内部调 `_load_stage_modules()` 重新 import 真 handler 覆盖 lambda），跑全量 `pytest tests/` 即 pass。本 task 不修 LIM#10，遗留到 M2a 收尾或首位踩坑开发者修复。

**涉及文件**:
- Create: `src/autoclip/pipeline/scripting.py`
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import scripting`）
- ~~Modify: `src/autoclip/pipeline/state.py`（init 增加 style_preset 字段）~~ **删除（推迟 M2b.5）**
- ~~Modify: `src/autoclip/api/jobs.py`（POST /api/jobs 把 style_preset 传给 state.init）~~ **删除（推迟 M2b.5）**
- Create: `tests/integration/test_scripting_e2e.py`（mock LLMProvider + monkeypatch `AUTOCLIP_STYLE_PRESET`）

**测试策略**:
- 集成（mock LLM）: patch QwenProvider 返回固定 JSON，验证 timeline.json 结构正确 + state DONE
- 集成（真实 LLM，手动）: 跑 5min 短片，肉眼检查 timeline.json 合理度

**验收标准**:
- [ ] mock 集成测试通过
- [ ] **Milestone 端到端验收**: 短片完整流水线 ingest+index+script 跑通，肉眼检查匹配 ≥ 50%
- [ ] Scripting stage ≤ 2.5min/90min 视频（K6 部分目标 — 详见下方 K6 预算说明）

> **K6 总预算占比说明**（**adhoc plan-2 修正**）：design.md §7.2 K6 总预算 ≤ **16min/90min**（5 个 stage 合计）。M1 实测 large-v3 在 90min 视频上的 ASR ≈ **9-10min**（Index 段大头），ingest 双轨 normalize ≈ **1.5min**，留给 Scripting 实际只有 **2.5-3min**。原 plan 写"≤ 4min/90min"是对总预算结构未消化的过乐观估计，本次 adhoc 据实修正为 **≤ 2.5min/90min**。Assembly + Render 余下 ~3min（M3.4 验收）。

**关联 KPI**: K6（端到端耗时） / K8
**依赖**: M2a.1 + M2a.2 + M2a.3 + M2a.4 + M2a.5 → **阻塞**: M2b 全部
**预估工时**: 1.5d

---

## M2a 总工时估算
| 任务 | 工时 |
|---|---|
| M2a.1 LLMProvider | 0.5d |
| M2a.2 Plot Outline | 1.0d |
| M2a.3 Narrative IR | 1.0d |
| M2a.4 JSON repair + retry | 0.5d |
| M2a.5 简化绑定 | 1.0d |
| M2a.6 Scripting handler | 1.5d |
| **总计** | **5.5d**（控制在 W2 内） |

## M2a 完成时的 PR 描述模板
```
✨feat: M2a - Scripting main loop (LLM + naive binding)
    - T2a.1 LLMProvider abstraction + Qwen impl
    - T2a.2 Plot outline extraction prompt
    - T2a.3 Narrative IR data model + plot_summary style preset
    - T2a.4 JSON repair + retry decorator
    - T2a.5 Naive greedy binder (paragraph hint based)
    - T2a.6 Scripting stage handler (E2E pipeline integrated)
```

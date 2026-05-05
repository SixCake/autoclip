# M2a — Scripting 主链路（Week 2）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §8 / §16.3 / §17.1 / ADR-001（v0.5 修订）

## M2a Brainstorming 决策矩阵（v0.5, 2026-05-05）

> **本节由 brainstorming skill 在 M2a kickoff 时收敛产出，是 M2a.1-M2a.6 所有任务的最高约束源**；任何 task 与本节冲突时以本节为准。
> 触发本次 brainstorming 的契机：M2a 启动前，从 v0.4 plan 沉淀的 5 个未决议题（Provider 选型 / 双引擎 / 可观测性 / 降级路径 / 进度颗粒度）。
> 收敛过程见 chat.md「Session 10 Brainstorming Q1-Q8」段，实施约束 D1-D4 见本节末尾。

| # | 议题 | 决策 | 关键约束 |
|---|---|---|---|
| Q1 | LLM Provider | **DeepSeek 替代 Qwen** | OpenAI 兼容协议；128k context；JSON mode |
| Q2 | Provider 架构 | **双引擎并存** | 通过 LangChain `BaseChatModel` 抽象；DeepSeek 主用，dashscope 兜底 |
| Q3 | API 命名 | **OpenAI 标准命名** | LangChain `ChatOpenAI`（DeepSeek base_url 注入）；不自造 wrapper |
| Q4 | LLM 调用可观测性 | **`{job_dir}/llm_calls/` 落盘** | 每次 call 落 `{stage}_{seq}.json`（含 prompt / response / usage / cost）；用 LangChain `BaseCallbackHandler` 实现，K9 cleanup 一并删除 |
| Q5 | target_duration / style_preset 注入 | **A+C：state.json 直读 + UI 层 fallback** | M1.4 已实现 `_JobMeta.target_duration_sec` + `style_preset`；handler 直读，**不动 state schema**；UI fallback `clamp(video_duration/10, 30, 600)` 见 M3.7 |
| Q6 | plot_outline 失败处理 | **A：硬失败** | LLM 失败 / JSON 不可修复时 raise `PlotOutlineError`，stage→FAILED；本地无 key 走 M2b mock provider，**不引入降级路径** |
| Q7 | narrative IR token 预算 | **A：不分片单次 call** | 入口 K7 检查：输入 token 预估 >32k 时 raise `NarrativeIRTooLargeError`；>2h 视频留给 M2b/M3 优化 |
| Q8 | handler 进度上报颗粒度 | **B：8 个细里程碑** | 每个 LLM 阶段拆 `start (sending)` + `done (received)`；复用 M1.4 `progress` 字段，不动 schema |

**深度选项**（B1-B3 = 实施深度边界）：
- **B1=A**：LangChain 用最小化深度——只用 `BaseChatModel` + `BaseCallbackHandler`，prompt 仍用 f-string，输出仍走 M2a.4 自写 JSON repair；**故意不用** `ChatPromptTemplate` / `PydanticOutputParser` / `OutputFixingParser`，避免把"修复策略"权交给 LangChain 黑盒
- **B2=B**：dashscope 做完整双引擎实跑验证（不只是接口预留）；M2a.1 unit test 用 `FakeListChatModel` mock 两条路径都跑通，dashscope 跑一次冒烟测试
- **B3=A**：M2a.1 标题改写为 "LangChain 集成 + LLMFactory"，工时 1.5d→1.0d（少写自抽象层 -0.5d，实测两个 provider +0.0d 因为 LangChain 接入成本极低）

**落盘约束**（D1-D4 = 文档与依赖落盘细节）：
- **D1=B**：pyproject.toml 同时显式声明 `langchain-community` + `dashscope^1.20`（既然 B2-B 要实跑就显式锁版本，避免 langchain-community 升级时意外断开 dashscope 接入）
- **D2=A**：LangChain 紧锁 `langchain-core>=0.3,<0.4 + langchain-openai>=0.2,<0.3 + langchain-community>=0.3,<0.4`（0.x 大版本破坏性改动多）
- **D3=A**：本决策矩阵原地嵌入主 plan（避免文档碎片化，不新建独立 brainstorming 记录文件）
- **D4=Y**：4 批次执行（doc-only file_replace → 验证 → commit → worktree-save 结束门禁），不跑 poetry install（留给 M2a.1 实现时跑），不跑 pytest（本批次 doc-only）

**工时净变化**：5.5d → **5.3d**（M2a.1 -0.5d + B2-B dashscope 实跑 +0.3d）

---

## 🎯 Milestone 目标
集成 LangChain `BaseChatModel` 抽象 + DeepSeek-V3 主 provider + dashscope 兜底；端到端跑通"读 shots.json + asr.json → 输出 timeline.json"的 Scripting 流程。本里程碑只做**最简版本**——不做 evidence_keywords 反向校验，仅按 paragraph_hint 时间区间贪心分配镜头。后续 M2b 升级。

## ✅ Milestone 验收
- [ ] 对 M1 跑通的 1 部短片，触发 Scripting stage 后产出 `timeline.json`
- [ ] timeline.json 结构正确（plot_outline + narrative_ir + binding_stats + segments）
- [ ] 每个 segment 都关联到至少 1 个 shot id
- [ ] 肉眼检查：50% 以上句子的**段落级 source_shot 匹配方向**是合理的（**v0.6 措辞收紧**：M2a baseline 仅做 paragraph 均分；句级精确匹配由 M2b evidence 反向校验交付，K1/K2/K3 产品 KPI 由 M2b 验收）
- [ ] **v0.6 新增**：timeline.json 每个 segment 含 `target_duration_sec_estimate` 字段（按字数加权预估），**总和与 `state.target_duration_sec` 误差 ≤ 5%**；真实 target 时长由 M3.2 TTS 实跑后回填，**M2a 不验出片时长准确性**
- [ ] LLM 调用失败时有 retry 3 次 + JSON repair 兜底
- [ ] **DeepSeek 主路径 + dashscope 兜底路径**双引擎冒烟测试均通过（B2-B 决策）
- [ ] **每次 LLM 调用落盘到 `{job_dir}/llm_calls/{stage}_{seq}.json`**（Q4 决策，K3 验收点）
- [ ] Scripting stage 端到端 ≤ 2.5min（90min 视频，K6 部分预算）

## 📊 关联 KPI
- **K1, K2, K3**（绑定准确率/召回率/fallback）：M2a 不做严格量化，留给 M2b 升级
- **K6**（端到端耗时）：本 milestone Scripting 部分应 ≤ 2.5min/90min（详见 M2a.6 K6 总预算说明）
- **K8**（单元测试覆盖率）：narrative IR 解析 / 简化绑定 / JSON repair 共 ≥ 10 个用例

## 🔗 依赖
- **前置**: M1 全部（需要 shots.json + asr.json）
- **阻塞下游**: M2b 全部 / M3.4（Render 需要 timeline.json）

---

## 任务清单（6 个）

### M2a.1 — LangChain 集成 + LLMFactory + LlmCallsRecorder（**v0.5 重写**）

**目标**: 通过 LangChain `BaseChatModel` 抽象层接入 DeepSeek-V3 主 provider + qwen-plus 兜底 provider，并实现 `LlmCallsRecorder` callback 把每次 LLM 调用落盘到 `{job_dir}/llm_calls/`（design.md ADR-001 v0.5 修订 + 本 plan 头部决策矩阵 Q1/Q2/Q3/Q4 + B1/B2/B3）。

> **v0.5 变更说明**：v0.4 旧版"自抽象 LLMProvider ABC + QwenProvider 直连 dashscope SDK + tenacity retry"被 brainstorming Q1-Q4 决策替换。新版用 LangChain 原生 `BaseChatModel` 替代自造 ABC（约 -150 行抽象代码），DeepSeek 替代 qwen 作主 provider（成本更低 + 128k context），通过 `BaseCallbackHandler` 而非 handler 层手写实现 LLM 调用可观测性（M2a.6 因此减重 -0.7d）。本任务**故意不引入** `ChatPromptTemplate` / `PydanticOutputParser` / `OutputFixingParser`（B1=A 最小化深度决策，详见 M2a.4 备注）。

**关键设计决策**:
- **LangChain 抽象层**: 直接用 `langchain_core.language_models.BaseChatModel.invoke(messages: list[BaseMessage]) -> AIMessage`；**不自造 LLMProvider ABC**，不自造 LLMMessage / LLMResponse dataclass
- **数据结构**（全部用 LangChain 原生类型）:
  - 输入: `list[BaseMessage]` —— `SystemMessage(content=...)` + `HumanMessage(content=...)`（来自 `langchain_core.messages`）
  - 输出: `AIMessage` —— `aimsg.content` 取文本，`aimsg.usage_metadata` 取 `{input_tokens, output_tokens, total_tokens}`（LangChain 0.3+ 标准化字段）
- **`get_llm()` factory**（`src/autoclip/providers/llm/factory.py`）:
  - 签名: `get_llm(provider: Literal["deepseek","dashscope"] | None = None, *, json_mode: bool = False, callbacks: list[BaseCallbackHandler] | None = None, temperature: float = 0.3, max_tokens: int = 2000, **model_kwargs) -> BaseChatModel`
  - `provider` 默认从 env var `AUTOCLIP_LLM_PROVIDER`（值 `deepseek` 或 `dashscope`）读取，缺省为 `deepseek`
  - **DeepSeek 分支**（`provider="deepseek"`）: 返回 `ChatOpenAI(model="deepseek-chat", base_url="https://api.deepseek.com/v1", api_key=os.environ["DEEPSEEK_API_KEY"], temperature=temperature, max_tokens=max_tokens, max_retries=2, callbacks=callbacks, model_kwargs={"response_format": {"type": "json_object"}} if json_mode else {})`
  - **dashscope 分支**（`provider="dashscope"`）: 返回 `ChatTongyi(model="qwen-plus", api_key=os.environ["DASHSCOPE_API_KEY"], temperature=temperature, max_retries=2, callbacks=callbacks, model_kwargs={"response_format": {"type": "json_object"}} if json_mode else {})`（`langchain_community.chat_models.ChatTongyi`）
  - **缺 api_key 时**: 抛 `RuntimeError(f"{ENV_VAR} not set; cannot init {provider} provider")`，**不自动 fallback**（避免静默降级隐藏配置错误，K8 硬失败精神）
- **`LlmCallsRecorder` callback**（`src/autoclip/providers/llm/callback.py`）:
  - 继承 `langchain_core.callbacks.BaseCallbackHandler`
  - 构造: `LlmCallsRecorder(job_dir: Path, stage: str)` —— `stage` 作为文件名前缀（M2a.6 传 `"scripting"`）
  - 实现 `on_chat_model_start(serialized, messages, run_id, **kw)` + `on_llm_end(response: LLMResult, run_id, **kw)`：成对捕获请求 / 响应，按 `run_id` 配对
  - 落盘路径: `{job_dir}/llm_calls/{stage}_{seq:03d}.json`（`seq` 是 instance 内自增计数器，从 1 起）
  - 落盘 schema: `{"seq": int, "stage": str, "model": str, "messages": [{"role": str, "content": str}], "response": str, "usage": {"input_tokens": int, "output_tokens": int, "total_tokens": int}, "started_at": "ISO8601", "ended_at": "ISO8601", "duration_sec": float}`
  - 目录不存在时自动 `mkdir(parents=True, exist_ok=True)`
  - 写盘失败（磁盘满 / 权限错）只 `loguru.warning(...)`，**不抛**（避免可观测性逻辑反向阻塞业务调用）
- **依赖声明**（**D1=B + D2=A 决策**）：M2a.1 实现第一步必须在 `pyproject.toml` 的 `[tool.poetry.dependencies]` 段追加：
  - `langchain-core = ">=0.3,<0.4"`（`BaseChatModel` / `BaseMessage` / `BaseCallbackHandler` 来源）
  - `langchain-openai = ">=0.2,<0.3"`（`ChatOpenAI`，DeepSeek 通过它接入）
  - `langchain-community = ">=0.3,<0.4"`（`ChatTongyi`，dashscope 通过它接入；显式锁版本以防 community 升级断 dashscope 接入）
  - `dashscope = "^1.20"`（**保留**，`ChatTongyi` 实际依赖此 SDK，D1=B 显式锁定避免传递依赖隐式升级）
  - `pydantic = "^2.0"`（M2a.2 `_PlotOutlineRaw` 校验层使用）
  - **删除**: `tenacity` 不再需要（HTTP 层重试由 `ChatOpenAI(max_retries=2)` 接管；M2a.4 `retry_with_repair` 是应用层 JSON 修复重试，自实现 for 循环即可，不需要 tenacity 装饰器）
  - 完成后跑 `poetry lock --no-update && poetry install` 锁版本，并把 `pyproject.toml` + `poetry.lock` 一起 commit

**涉及文件**:
- Modify: `pyproject.toml`（依赖增减如上 + `poetry.lock` 同步）
- Create: `src/autoclip/providers/llm/__init__.py`（re-export `get_llm` + `LlmCallsRecorder`）
- Create: `src/autoclip/providers/llm/factory.py`（`get_llm()` 实现）
- Create: `src/autoclip/providers/llm/callback.py`（`LlmCallsRecorder` 实现）
- Create: `tests/unit/test_llm_factory.py`（FakeListChatModel 注入 + 双 provider 路径 + env var 缺失抛错）
- Create: `tests/unit/test_llm_callback.py`（落盘 schema / 文件命名 / mkdir 自动创建 / 写盘失败不抛）
- Create: `tests/integration/test_dual_provider_smoke.py`（默认 skip，需 `RUN_INTEGRATION=1` + `DEEPSEEK_API_KEY` + `DASHSCOPE_API_KEY`，问 "1+1=?" 验证返回含 "2" 且 `usage_metadata.total_tokens > 0`）

**测试策略**:
- 单元（factory，≥ 5 用例）:
  - `test_get_llm_default_provider_is_deepseek`：不传 provider 且无 env var 时返回 `ChatOpenAI` 实例且 `model_name == "deepseek-chat"`
  - `test_get_llm_dashscope_explicit`：`provider="dashscope"` 返回 `ChatTongyi` 实例且 `model == "qwen-plus"`
  - `test_get_llm_json_mode_passes_response_format`：`json_mode=True` 时 `model_kwargs["response_format"] == {"type": "json_object"}`
  - `test_get_llm_missing_api_key_raises`：monkeypatch `delenv("DEEPSEEK_API_KEY")` 后 `provider="deepseek"` 抛 `RuntimeError` 且 message 含 "DEEPSEEK_API_KEY not set"
  - `test_get_llm_with_callbacks_attaches`：传 `callbacks=[LlmCallsRecorder(tmp_path, "test")]` 后回返实例的 `.callbacks` 包含该 recorder
- 单元（callback，≥ 4 用例）:
  - `test_recorder_writes_file_on_llm_end`：用 `FakeListChatModel(responses=["hello"])` 跑一次 invoke，断言 `{tmp_path}/llm_calls/test_001.json` 存在 + JSON parse 成功 + schema 字段齐全
  - `test_recorder_seq_increments_across_calls`：连跑 3 次 invoke，断言文件 `test_001.json` / `test_002.json` / `test_003.json` 都存在且 `seq` 字段 1/2/3
  - `test_recorder_creates_dir_if_missing`：传不存在的 `job_dir / "deeply" / "nested"`，断言目录被自动创建
  - `test_recorder_disk_failure_does_not_raise`：monkeypatch `Path.write_text` 抛 `OSError`，断言 invoke 仍成功且无异常上抛（仅 loguru warn）
- 集成（手动，≥ 2 用例）: `test_deepseek_smoke` + `test_dashscope_smoke` 各问 "1+1=?"，断言响应文本含 "2" + `usage_metadata.total_tokens > 0` + `{job_dir}/llm_calls/smoke_001.json` 落盘成功

**验收标准**:
- [ ] 单元测试 ≥ 9 个用例全部通过（factory 5 + callback 4）
- [ ] 双 provider 集成冒烟测试（DeepSeek + dashscope）本地手跑均通过（B2=B 决策硬要求）
- [ ] `{job_dir}/llm_calls/scripting_001.json` 在集成测试后实际存在且 schema 合法（K3 验证）
- [ ] JSON mode 在 M2a.3 实测 DeepSeek 主路径稳定返回合法 JSON（≥ 80% 不需 repair）

**关联 KPI**: K3（llm_calls/ 落盘）+ K8（单测覆盖率）
**依赖**: M1.1 → **阻塞**: M2a.2 / M2a.3 / M2a.6
**预估工时**: **1.0d**（v0.5 +0.5d：B3=A 工时净值 = -0.5d 少写 ABC + Callback 实现 +0.5d + B2=B dashscope 实跑冒烟 +0.3d + LangChain 学习曲线 +0.2d = 净 +0.5d）

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
- **v0.6 修订（adhoc self-review, 2026-05-05）— evidence_keywords 在 M2a 是 dead data，prompt 删除**:
  - **症状**：M2a baseline `bind_naively` 完全不消费 evidence_keywords（plan §M2a.5 "不做的事" 第 1 条已说明），但 v0.5 prompt 仍要求 LLM 输出每句 2-5 个关键词
  - **判定**：按 "Minimum code that solves the problem. Nothing speculative." 规则，让 LLM 生成谁都不读的字段属于典型 speculative work，浪费 ~15-25% 输出 tokens（每句 ~120 token → ~80 token）
  - **决策**：M2a 的 narrative_ir prompt **删除 evidence_keywords schema + 指令**；`NarrativeSentence.evidence_keywords` 字段保留 `default_factory=list` 不动（schema 稳定，M2b 切换零迁移）；解析层填充空列表
  - **回填责任**：M2b.4 prompt v2 重新加回 evidence_keywords 输出要求（详见 M2b-scripting-robust.md §M2b.4 v0.6 修订）
  - **关联**：本修订与 §M2a.6 v0.6 修订（双闸门 + 动态 max_tokens）配套；删 evidence 后输出 token 预估系数从 120 → 80，narrative_ir_max_tokens 公式同步收紧
  - **不变**：dataclass 字段 / Pydantic raw model / parse 逻辑 / timeline.json schema 全部不动；唯一改动点是 `prompts/narrative_ir.py` 的 SYSTEM_PROMPT_TEMPLATE schema 块和 "关键约束" 第 2 条
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
- **不使用 LangChain `OutputFixingParser`**（**B1=A 最小化决策**）：LangChain 的 `OutputFixingParser` 把"修复策略"权交给框架黑盒——失败时再调一次 LLM 让它修自己输出，调试成本极高且不可控。本 task 自写 `try_repair_json` 的 5 步策略（fence 剥离 / `{...}` 抽取 / trailing comma / 单引号 / 多策略候选）是确定性算法，每一步都可单元测试，且不引入额外 LLM 调用。M2b 阶段如证明此处是质量瓶颈再升级，**M2a 阶段刻意不升级**

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
- **v0.6 修订（adhoc self-review, 2026-05-05）— BoundSegment target-side 时长占位**:
  - **症状**：当前 BoundSegment 只有 source-side 时间（`source_start_sec` / `source_end_sec` = 原片素材范围），但 MVP 出片时长由 target_duration_sec 决定；timeline.json 没有 target-side 占位会让 M3.2/M3.3 拿到"96s 原片素材"却不知该裁成几秒
  - **决策**：M2a.6 序列化 timeline.json 时给每个 segment 增加 `target_duration_sec_estimate: float` 字段（**仅在序列化层加，不污染 BoundSegment dataclass**）
  - **估算公式**（按字数加权）：`target_duration_sec_estimate = (len(sentence_text) / sum(len(s.sentence_text) for s in segments)) × state.target_duration_sec`
  - **不变量**：`sum(segment.target_duration_sec_estimate for all segments) == state.target_duration_sec`（浮点累加误差 < 0.01s）
  - **回填责任**：M3.2 TTS 实跑后，把每个 segment 的 `target_duration_sec_estimate` 替换成 `target_duration_sec`（实测值），estimate 字段保留为 audit；详见 M2b/M3 plan 对应 task v0.6 修订
  - **为什么不进 BoundSegment dataclass**：`bind_naively` 是纯算法层，不该感知"目标时长"这个产品概念；用 `_estimate` 后缀明示"占位、会被改写"，避免和 M3 修正后的真实值混淆
  - **关联**：本修订与 §M2a.6 v0.6 修订（timeline.json schema 加 estimate 字段）配套；M2a.5 算法层零改动

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
- **handler 流程**（design.md §8，**v0.5 LangChain 改写**）:
  1. 加载 shots.json + asr.json + state.json（取 `_JobMeta.target_duration_sec` + `style_preset`）
  2. 计算 full_text 和 timestamped_text；**入口 K7 检查**：`estimate_tokens(timestamped_text) > 32000` 时 raise `NarrativeIRTooLargeError`
  3. 实例化 `LlmCallsRecorder(job_dir, stage="scripting")` callback
  4. 通过 `get_llm(json_mode=True, callbacks=[recorder], temperature=0.3, max_tokens=2000)` 拿到 plot_outline LLM；调用 `llm.invoke(plot_outline_messages)`；解析失败抛 `PlotOutlineError`（**Q6=A 硬失败**，不降级）
  5. 通过 `get_llm(json_mode=True, callbacks=[recorder], temperature=0.7, max_tokens=8000)` 拿到 narrative_ir LLM；调用 `llm.invoke(narrative_ir_messages)`
  6. 简化绑定（M2a.5）
  7. 序列化 timeline.json
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
  1. LangChain `ChatOpenAI(max_retries=2)` 处理 HTTP 层失败（M2a.1 已实现）
  2. M2a.4 `retry_with_repair` 装饰器处理 JSON 解析层失败（与 LangChain HTTP 重试互补）
  3. parse 失败 → `try_repair_json` → 重 parse；仍失败抛 `ValueError` → `retry_with_repair` 再试
  4. plot_outline 链路最终失败 → raise `PlotOutlineError`，stage→FAILED（**Q6=A 硬失败决策，不引入降级 outline**）
  5. narrative_ir 链路最终失败 → raise `NarrativeIRError`（同样硬失败）
- **进度上报**（**Q8=B 8 个细里程碑决策**，复用 M1.4 `progress` 字段，不动 schema）:
  - `0.05` — handler 入口、文件加载完成
  - `0.10` — plot_outline LLM call **start (sending request)**
  - `0.25` — plot_outline LLM call **done (response received + parsed)**
  - `0.30` — narrative_ir LLM call **start (sending request)**
  - `0.60` — narrative_ir LLM call **done (response received + parsed)**
  - `0.65` — JSON repair 链路完成（如触发 repair 则记录，未触发跳过）
  - `0.80` — simple binding **start**
  - `0.95` — binding **done**
  - `1.00` — timeline.json 序列化完成（DONE 由 entrypoint 兜底，handler 不重复 mark）
  - **K10 关联**：8 个里程碑 = M2a.6 验收硬要求，需 unit test 验证调用顺序
- **Cancel 检查点**: 在每次 LLM 调用前 + binding 前；从 `state.cancel_requested` 读，命中则 raise `CancelledError`
- **style_preset / target_duration_sec 注入方式**（**adhoc plan-4-rollback 校正, 2026-05-05**）：**直接从 `state.json` 读取**，无需 schema 改造。M1.4 已经实现完整链路：
  - `src/autoclip/pipeline/state.py:91-98` `_JobMeta` dataclass 已有 `target_duration_sec: int` + `style_preset: str` 字段
  - `src/autoclip/pipeline/state.py:122-128` `JobStateFile.init_state()` 签名已接受这两个参数
  - `src/autoclip/api/jobs.py:103-107` `POST /api/jobs` Form 已接受 `target_duration_sec: Annotated[int, Form(ge=10, le=600)]`（必填）+ `style_preset: Annotated[str, Form()] = "plot_summary"`（可选默认值）
  - M2a.6 handler 直接 `JobStateFile(job_dir).load()` 读 `_JobMeta` 字段即可，零改动
  - 前端默认值规约（**adhoc Q5-corr C 文档化**）：M3.7 Web UI 表单的 `target_duration_sec` 输入框默认值 = `clamp(video_duration_sec / 10, 30, 600)`。这是用户体验默认值（在 UI 层 fallback），不是 API 层 fallback——API 层保持必填以防止"什么时候用 fallback"的隐式规则
  - **回滚原因**：本 task 原 plan-4（commit 416bf55）写"M2a.6 用环境变量 AUTOCLIP_STYLE_PRESET 注入避免 schema 漂移"是基于错误假设——当时未 read state.py / api/jobs.py 真实代码，假设 M1.4 没实现这两个字段。Q5-corr 用 read_file 校正后发现 M1.4 已完整实现，env var 路径不仅多余还引入了"配置源歧义"（state.json vs env var 两个事实源）问题。本次回滚同时是 user_rules 第 7 条"严禁假设实现"的反面教材记录
- **LIM#10 提醒**（**adhoc G2 补充, 2026-05-04 .context tech_debt**）：实现 scripting handler 后若**单跑** `pytest tests/unit/test_runner.py` 出现 `IngestError: raw directory missing` 是已知问题（LIM#10：`_stage_entrypoint` 内部调 `_load_stage_modules()` 重新 import 真 handler 覆盖 lambda），跑全量 `pytest tests/` 即 pass。本 task 不修 LIM#10，遗留到 M2a 收尾或首位踩坑开发者修复。

- **K-clause 契约**（**v0.5 brainstorming Q4+Q6+Q7+Q8 落地，handler 入口必须满足以下 K 条款**）:
  - **K3** — 每次 LLM call 必须经过 `LlmCallsRecorder` callback 落盘到 `{job_dir}/llm_calls/{stage}_{seq:03d}.json`（**Q4 决策**）；handler 不允许直接 `llm.invoke()` 而不传 callback
  - **K7** — handler 入口处 `estimate_tokens(timestamped_text) > 32000` 时 raise `NarrativeIRTooLargeError("input exceeds 32k token budget; >2h video not supported in M2a")`（**Q7=A 决策**，>2h 视频留给 M2b/M3）
  - **K8** — plot_outline 解析失败（含 LLM 网络失败 / JSON 不可修复 / Pydantic 校验失败）时 raise `PlotOutlineError`，stage→FAILED；**禁止**降级到 fallback outline（**Q6=A 决策**）
  - **K9** — `{job_dir}/llm_calls/` 在 M3.6 cleanup 阶段整目录删除（与 `*.tmp` / `*.bak` 同批），不进入 final tarball；本 task 仅写入，cleanup 路径在 M3.6 task 实现
  - **K10** — handler 必须按 8 个细里程碑顺序上报进度（0.05 / 0.10 / 0.25 / 0.30 / 0.60 / 0.65 / 0.80 / 0.95 / 1.00），**Q8=B 决策**；unit test 用 `MockJobStateFile` 验证调用顺序与时机

- **v0.6 修订（adhoc self-review, 2026-05-05）— 三处算法/契约缺陷收敛**：

  ### 修订 1：K7 双闸门 — 输入阈值 + 输出动态 max_tokens（修复"600s 档位 100% 失败"P0 bug）
  - **症状**：当前 K7 阈值 `> 32000` 在 M2a 是死分支（DeepSeek 128k context + ASR 截 40k 字符 ≈ 18k tokens 总输入，永远到不了）；真正会炸的是输出——`narrative_ir` 的 `max_tokens=8000` 硬编码，用户选 600s 档位（≈100 句）极可能截断 → JSON 不完整 → repair 失败 → stage FAILED；**用户选系统支持的最大档位反而 100% 失败**
  - **决策**：K7 从单闸门（仅卡输入）升级为**双闸门**：
    - **输入闸门**：`INPUT_TOKEN_BUDGET_K7 = 90000`（DeepSeek 128k 留 30k 给输出的安全水位），常量改名 `TOKEN_BUDGET_K7 → INPUT_TOKEN_BUDGET_K7`；阈值从 32000 → 90000
    - **输出闸门**：`narrative_ir_max_tokens` 从硬编码 8000 改为按 target_sentences 动态算：
      ```
      target_sentences = int(target_duration_sec / 6)  # 已有逻辑
      narrative_ir_max_tokens = clamp(target_sentences * 80 + 1000, 2000, 16000)
      # 系数 80 配合 v0.6 修订 3（删 evidence_keywords，每句 token 从 ~120 降到 ~80）
      # +1000 是 system overhead（paragraph 包裹 / topic 字段 / JSON 结构本身）
      # clamp [2000, 16000] 防止极端档位（10s 档算出 800 tokens 不够 / 千秒级档位算出 50k 超 DeepSeek 输出上限）
      ```
  - **影响代码**：`scripting.py` 的 `TOKEN_BUDGET_K7` 常量改名 + 数值改 90000；`NARRATIVE_IR_MAX_TOKENS` 常量删除，改在 `_invoke_llm_with_repair` 调用前按 target_sentences 动态算；`get_llm(max_tokens=...)` 传动态值
  - **不变**：plot_outline 的 `max_tokens=2000` 不动（输出固定 schema，不随档位变化）
  - **测试用例补充**：原 K7 测试"构造 >32k token input 抛 NarrativeIRTooLargeError"改为"构造 >90k token input 抛错"；新增"600s 档位 narrative_ir_max_tokens 应为 8000+"和"60s 档位应为 2000"两个边界用例

  ### 修订 2：timeline.json schema 加 `target_duration_sec_estimate` 字段（修复 BoundSegment target-side 时长缺失）
  - **症状**：见 §M2a.5 v0.6 修订（timeline.json 没有目标时长占位，下游 M3.2/M3.3 拿到"96s 原片素材"却不知该裁成几秒）
  - **决策**：M2a.6 handler 序列化 timeline.json 时每个 segment 加 `target_duration_sec_estimate: float`，按字数加权估算（公式见 §M2a.5）
  - **timeline.json schema 变更**（segments 数组每个对象新增字段）：
    ```
    "segments": [{
      ...原有字段不变...,
      "target_duration_sec_estimate": 6.2  // 新增，按字数加权预估，M3.2 回填真值时改名 target_duration_sec
    }]
    ```
  - **影响代码**：`scripting.py` 序列化层 `timeline_payload["segments"]` 列表推导式增加 1 行字段；handler 计算 `total_chars = sum(len(s.sentence_text) for s in binding_result.segments)` 后按比例算每个 segment 的 estimate
  - **回填责任**：M3.2 TTS 实跑后改名为 `target_duration_sec`（详见 M3 plan v0.6 修订）

  ### 修订 3：进度上报里程碑 8 → 4 收敛（YAGNI / 删 dead milestone）
  - **症状**：当前 K10 契约硬编码 8 个进度数值（0.05 / 0.10 / 0.25 / 0.30 / 0.60 / 0.65 / 0.80 / 0.95 / 1.00）；其中 0.65 是"JSON repair chain done (recorded as separate milestone whether or not triggered)"——**它根本不对应任何实际工作**，只是为了凑数让"8 个里程碑"的契约成立；start/done 拆分对前端体验几乎无差别（90min 视频 Scripting 阶段 2.5min，每节点平均 18 秒）
  - **决策**：里程碑收敛到 **4 个**：
    - `0.05` — handler 入口、文件加载完成
    - `0.30` — plot_outline DONE（response received + parsed）
    - `0.65` — narrative_ir DONE（response received + parsed）
    - `0.95` — binding DONE
    - DONE 由 entrypoint 兜底（progress=1.0 自动写入），handler 不重复 mark
  - **K10 契约弱化**：从"按 8 个特定数值顺序触发"改为"progress 值单调递增 + 至少包含上述 4 个数值 + DONE 时 progress=1.0"；不锁具体中间数值（未来调整颗粒度无需改契约）
  - **删 start 拆分**：plot_outline / narrative_ir / binding 的 `start (sending)` 节点全部删除（用户感知不到 18 秒级颗粒度）
  - **测试用例简化**：`test_scripting_handler_progress.py` 断言从"8 个特定数值顺序"改为"progress 单调递增 + 至少 4 次调用 + 末次 progress >= 0.95"；少 1 个测试文件意义上的复杂度，断言更稳

  ### 修订 4：Milestone 验收措辞收紧（区分工程验收 vs 产品 KPI）
  - **症状**：当前 Milestone 验收第 4 条"肉眼检查 50% 以上句子的镜头匹配是合理的"措辞会让人误以为 M2a 完了就达成产品 KPI K1（≥70%）；但 §M2a.5 baseline 算法明说"不做 evidence 反向校验"，K1/K2/K3 必须由 M2b 验收
  - **决策**：Milestone 验收第 4 条改写为：**"肉眼检查 50% 以上句子的段落级 source_shot 匹配方向是合理的（M2a baseline 仅做 paragraph 均分；句级精确匹配由 M2b evidence 反向校验交付，K1/K2/K3 等产品 KPI 由 M2b 验收）"**
  - **新增 Milestone 验收第 9 条**：**"timeline.json 每个 segment 含 `target_duration_sec_estimate` 字段，总和与 `state.target_duration_sec` 误差 ≤ 5%；真实 target 时长由 M3.2 TTS 实跑后回填，M2a 不验出片时长准确性"**

  ### 修订总览（v0.6 改动量预估）
  - 影响文件：`scripting.py`（+~15 行: K7 改名+阈值改+max_tokens 动态计算+estimate 序列化）/ `prompts/narrative_ir.py`（-~5 行: 删 evidence schema 和指令）/ `tests/unit/test_scripting_handler_progress.py`（断言简化）/ `tests/unit/test_tokens.py`（K7 阈值边界用例补充）
  - 净代码量：约 +10 行 / -10 行（基本持平）
  - 工时净影响：0d（属于 M2a.6 范围内的小幅微调，不延长 W2）
  - 实施顺序约束：本 v0.6 修订必须在 M2a.6 实现进入 commit 前完成；当前 git 状态显示 `scripting.py` 已 staged 未 commit，**正好可在同一 commit 内吸收 v0.6 改动**（避免独立 commit 引入 history 噪音）

**涉及文件**:
- Create: `src/autoclip/pipeline/scripting.py`
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import scripting`）
- ~~Modify: `src/autoclip/pipeline/state.py`（init 增加 style_preset 字段）~~ **本 task 不需要**（M1.4 已实现 `_JobMeta.style_preset` + `_JobMeta.target_duration_sec`）
- ~~Modify: `src/autoclip/api/jobs.py`（POST /api/jobs 把 style_preset 传给 state.init）~~ **本 task 不需要**（M1.4 已实现 `POST /api/jobs` Form 字段）
- Create: `tests/integration/test_scripting_e2e.py`（用 LangChain `FakeListChatModel` 注入预设 plot_outline + narrative_ir 响应，从 mock `state.json._JobMeta` 读取 target_duration_sec / style_preset；验证 8 个进度里程碑顺序）
- Create: `tests/unit/test_scripting_handler_progress.py`（K10 进度顺序验证，独立单元测试）

**测试策略**:
- **单元（K10 进度）**: 用 `FakeListChatModel` + `MockJobStateFile`，断言 8 个 progress 调用按 0.05→0.10→0.25→0.30→0.60→0.65→0.80→0.95→1.00 顺序触发
- **单元（K7 阈值）**: 构造 timestamped_text > 32k token 的 input，断言 raise `NarrativeIRTooLargeError`
- **单元（K8 硬失败）**: `FakeListChatModel` 返回不可修复 JSON（如 `"not json at all"`），断言 raise `PlotOutlineError` 且 stage→FAILED
- **集成（mock LLM, K3 落盘验证）**: patch `get_llm` 返回 `FakeListChatModel + LlmCallsRecorder`，验证：
  - timeline.json 结构正确（plot_outline + narrative_ir + binding_stats + segments）
  - state DONE
  - `{job_dir}/llm_calls/scripting_001.json` + `scripting_002.json` 文件存在且 schema 合法
- **集成（真实 LLM，手动）**: 跑 5min 短片，肉眼检查 timeline.json 合理度 + DeepSeek 主路径 + dashscope 兜底路径各跑一次（B2=B 验收）

**验收标准**:
- [ ] mock 集成测试通过
- [ ] **Milestone 端到端验收**: 短片完整流水线 ingest+index+script 跑通，肉眼检查匹配 ≥ 50%
- [ ] Scripting stage ≤ 2.5min/90min 视频（K6 部分目标 — 详见下方 K6 预算说明）

> **K6 总预算占比说明**（**adhoc plan-2 修正**）：design.md §7.2 K6 总预算 ≤ **16min/90min**（5 个 stage 合计）。M1 实测 large-v3 在 90min 视频上的 ASR ≈ **9-10min**（Index 段大头），ingest 双轨 normalize ≈ **1.5min**，留给 Scripting 实际只有 **2.5-3min**。原 plan 写"≤ 4min/90min"是对总预算结构未消化的过乐观估计，本次 adhoc 据实修正为 **≤ 2.5min/90min**。Assembly + Render 余下 ~3min（M3.4 验收）。

**关联 KPI**: K6（端到端耗时） / K8
**依赖**: M2a.1 + M2a.2 + M2a.3 + M2a.4 + M2a.5 → **阻塞**: M2b 全部
**预估工时**: 1.5d

---

## M2a 总工时估算（**v0.5 修订**）

| 任务 | v0.4 工时 | v0.5 工时 | 变化 |
|---|---|---|---|
| M2a.1 LangChain 集成 + LLMFactory + Callback | 0.5d | **1.0d** | +0.5d（B3=A 重写 + B2=B dashscope 实跑 + Callback 实现） |
| M2a.2 Plot Outline | 1.0d | 1.0d | — |
| M2a.3 Narrative IR | 1.0d | 1.0d | — |
| M2a.4 JSON repair + retry | 0.5d | 0.5d | — |
| M2a.5 简化绑定 | 1.0d | 1.0d | — |
| M2a.6 Scripting handler | 1.5d | **0.8d** | **-0.7d**（K3 可观测性逻辑下沉到 M2a.1 Callback；handler 仅负责调用编排 + K7/K8/K10 守护） |
| **总计** | **5.5d** | **5.3d** | **-0.2d**（控制在 W2 内） |

> **工时净变化推导**（v0.5）：M2a.1 +0.5d（多写 Callback + 多跑 dashscope），M2a.6 -0.7d（不再自实现 LLM 调用记录逻辑，仅消费 Callback），净 -0.2d。仍有 1d buffer 在 W2 内（W2 = 5d 工作日）。

## M2a 完成时的 PR 描述模板（**v0.5 修订**）
```
✨feat: M2a - Scripting main loop (LangChain + DeepSeek + naive binding)
    - T2a.1 LangChain BaseChatModel integration + LLMFactory (DeepSeek primary, dashscope fallback) + LlmCallsRecorder callback
    - T2a.2 Plot outline extraction prompt (with main_characters role inference, v0.4)
    - T2a.3 Narrative IR data model + plot_summary style preset
    - T2a.4 JSON repair + retry decorator (intentionally NOT using LangChain OutputFixingParser, B1=A)
    - T2a.5 Naive greedy binder (paragraph hint based; BindingMethod enum with EVIDENCE_LOWCONFIDENCE reserved for M2b)
    - T2a.6 Scripting stage handler (E2E pipeline + K3/K7/K8/K10 contracts + 8-milestone progress reporting)
```

# M2a-fix — 二创风格修正 + M2b-light kickoff（W2↔W3 衔接）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §8.3.2 / §17.1 / §17.4（待 v0.7 修订追加 §17.5 两阶段 LLM）
> **触发**: M2a v0.6 端到端真实视频验收 (job_20260505_141111 / job_20260505_144455) 暴露 `narrative_ir.text` 风格根本性偏离 design.md §8.3.2 — 实现的是"百度百科"，要的是"B 站 UP 主"。Session 20 brainstorming Q1-Q8 + 8 角度 critique 19 项 P0 修正全部 sign-off。

---

## M2a-fix Brainstorming 决策矩阵（v0.7, Session 20, 2026-05-05）

| # | 议题 | 决策 | 关键约束 |
|---|---|---|---|
| Q1 | 实施路径 | **D：先写设计规约** | 可观测/可验证/可决策；避免"直接动 prompt 拍脑袋" |
| Q2 | 风格库架构 | **E：混合架构** | MVP 1 维 N 种预设 + `PresetRegistry` class wrapper（内部 dict, 对外 register/get），v2.0 平滑迁 YAML |
| Q3 | MVP 品类预设 | **A：3 种品类化** | `shortdrama_推流` + `movie_summary` + `anime_情绪`（覆盖爽点放大/信息压缩/情绪共振 3 种二创灵魂） |
| Q4 | 反模式过滤层 | **F：B+E 组合** | 通用 R1-R6 注入 SYSTEM_PROMPT_TEMPLATE + 每预设 4-5 组 genre 分组 few-shot 正反例 |
| Q5 | 风格切换机制 | **F：CLI + state.json** | schema bump 提前到 M2a-fix（5 字段一并迁移：style_preset / binder_version / genre_inference / tone_recommendation / narrative_intent），废弃 commit 416bf55 的"环境变量"过渡方案 |
| Q6 | M2b 处置 | **E：M2b 拆分** | M2b-light（2d 出 narrative_intent 字段路由）已并入 M2a-fix.5；M2b-full（0/4d 视数据决定）保留在 M2b 自身 |
| Q7 | 交付节奏 | **D：1+3 渐进** | Day 1 movie_summary 单种端到端 → Day 2 扩 2 种 → Day 3 配置层 → Day 4-5 M2b-light + 评估 |
| Q8 | 内容自适应机制 | **E：两阶段 LLM** | 第 1 次推断 `{genre, tone, narrative_intent}` 写入 timeline.json（可观测/可干预/可优化）→ 第 2 次按推荐写文案 |

**用户关键反馈**（Session 20 中段，决定 Q8 从 D 升级到 E）：
> "风格要根据内容来，不是所有都需要吐槽"

---

## 8 角度圆桌辩论 → 19 项 P0 修正清单（8/8 sign-off）

> 完整辩论记录见 `.context/changes.md` Session 20 段。各角度（产品/工程/架构/成本/测试/用户/数据/运维）经过 3 轮相互讨论后达成共识，新增 19 项 P0 修正。本节是 M2a-fix.1-5 所有任务的最高约束源。

### 数据契约层（5 项）
| ID | 修正 | 落入任务 | 角度 |
|---|---|---|---|
| C1 | `genre` 封闭枚举（10 值含"其他"） | M2a-fix.1 | 数据 |
| C2 | `tone` 封闭枚举（7 值含"其他"） | M2a-fix.1 | 数据 |
| C3 | `narrative_intent` 封闭枚举（5 值含"其他"） | M2a-fix.1 | 数据/用户 |
| C4 | 每枚举值配 LLM 可识别描述符 + 1 个示例 | M2a-fix.1 | 数据/工程 |
| C5 | fallback 矩阵在 design.md §17.4 显式列出（如 Vlog→movie_summary 优先） | M2a-fix.1 | 数据/运维 |

### KPI 测量层（4 项）
| ID | 修正 | 落入任务 | 角度 |
|---|---|---|---|
| K-style-1 | R1-R6 反模式命中率 ≤ 10%（**正则扫描器**，Day 0 完成，Day 1 hard gate） | M2a-fix.1 / .2 | 测试/工程 |
| K-style-2 | 钩子句强度 ≥ 80%（batch LLM-as-judge，deepseek-reasoner，Day 5 跑） | M2a-fix.5 | 测试/数据 |
| K-style-3 | 二创视角句占比 ≥ 30%（同上 batch judge） | M2a-fix.5 | 测试/数据 |
| K-style-4 | 盲测胜率（**3-5 人 sanity check 非统计验证**，多数判定更好） | M2a-fix.2 / .5 | 产品/成本 |

### 成本/性能层（3 项）
| ID | 修正 | 落入任务 | 角度 |
|---|---|---|---|
| P1 | 每 preset prompt 硬上限 3000 tokens（utils/tokens.py K7 闸门统一管理） | M2a-fix.3 | 成本/工程 |
| P2 | K6 预算改 90s（明示二创风格修正版预算，含 2 次 LLM + 1 次重试链） | M2a-fix.4 | 运维 |
| P3 | 第 1 次调用按 hash 缓存（key = `plot_outline + style_preset + tone`，scope = job 生命周期） | M2a-fix.4 | 运维/工程 |

### 容错层（3 项）
| ID | 修正 | 落入任务 | 角度 |
|---|---|---|---|
| F1 | 失败兜底 = **静态默认三元组**（`{genre='其他', tone='温和讲解', narrative_intent='剧情速览'}`），不依赖 plot_outline 任何字段；design.md 显式列 50 字 justification | M2a-fix.1 / .2 | 工程/运维 |
| F2 | Day 1 必含 mock 第 1 次 LLM 失败模式测试（验证降级逻辑真的工作） | M2a-fix.2 | 工程/测试 |
| F3 | timeline.json 记录每次 LLM 调用 `{stage, provider, model, prompt_tokens, completion_tokens, wall_time_ms, cache_hit}` + `cost_summary` | M2a-fix.4 | 运维/成本 |

### UX/架构层（4 项）
| ID | 修正 | 落入任务 | 角度 |
|---|---|---|---|
| U1 | UX 露 4 意图按钮（`narrative_intent` 是否预填的开关），"自动选择"为默认且最显眼 | M2a-fix.1（设计） / M3.7（实现） | 用户/产品 |
| U2 | 按钮文案 emoji + 副文案 + hover 示例图（M3 阶段填真实图，本里程碑只规约） | M2a-fix.1（设计） / M3.7（实现） | 用户/产品 |
| A1 | `PresetRegistry` class wrapper（内部 dict, 对外 register/get）；当前约定式接口，design.md 明确标注"非契约式" | M2a-fix.2 | 架构 |
| A2 | timeline.json schema **一次性 bump 7 字段**（5 个 `narrative_ir.*` + 2 个顶层 `llm_call_log` / `cost_summary`），全部 Optional 向后兼容 | M2a-fix.4 | 架构/运维 |

---

## 🎯 Milestone 目标

把 M2a v0.6 已实现的"百度百科式 narrative_ir.text"修正为"B 站 UP 主二创解说"，建立 3 种品类化预设 + 两阶段 LLM 内容自适应机制 + 4 项二创质量 KPI 测量框架；同时启动 M2b-light（基于 `narrative_intent` 的绑定策略路由），用 3-5 部真实视频数据决定是否启动 M2b-full。

## ✅ Milestone 验收

- [ ] 3 种品类预设 (`shortdrama_推流` / `movie_summary` / `anime_情绪`) 全部实现，各含 STYLE_DESCRIPTION + 4-5 组 genre 分组 few-shot 正反例
- [ ] 两阶段 LLM 流程跑通：第 1 次输出 `{genre, tone, narrative_intent}` 落 timeline.json，第 2 次按推荐写文案
- [ ] CLI 加 `--style-preset` 入参 + state.json schema bump 5 字段（含数据迁移 backward-compatible 测试）
- [ ] timeline.json schema bump 7 字段（5 内 + 2 顶层），全 Optional
- [ ] **K-style-1 hard gate**：R1-R6 反模式命中率 ≤ 10%（正则扫描器，Day 1 已生效）
- [ ] **K-style-2/3** ≥ 80% / ≥ 30%（batch LLM-as-judge，Day 5 跑 3-5 部真实视频）
- [ ] **K-style-4 sanity check**：3-5 人盲测多数判定"修正版好过狗屎版"
- [ ] M2b-light 跑通：`narrative_intent` 字段成功路由 3 种绑定策略（summary→hint_uniform / comment→开放区间 / transition→镜头切点）
- [ ] M2b-full 决策报告：基于 Day 5 数据明确 "做" 或 "不做"
- [ ] 全套 pytest 全绿（净增预期 25-40 用例），E2E 真实视频验收通过

## 📊 关联 KPI

- **K-style-1/2/3/4**（新增 4 项二创质量 KPI）— 本里程碑核心目标
- **K1, K2, K3**（M2b 时代绑定 KPI）— **M2b-light 阶段重定义**：M2b-light 不追求精确绑定，但要求 `narrative_intent` 字段 100% 命中三类策略路由；K1/K2/K3 真正评估推迟到 M2b-full（如启动）
- **K6**（端到端耗时）— **预算改 90s**（M2a-fix 范畴内的 Scripting stage 部分）
- **K7**（单元测试覆盖率）— 净增 25-40 用例

## 🔗 依赖

- **前置**: M2a 全部（commit eecab0f + e883433；Session 19 端到端验收 PASS）
- **阻塞下游**:
  - M2b（仅 full 部分；light 部分已并入 M2a-fix.5）
  - M3.7（Web UI 需要 4 意图按钮设计 + state.json schema 完成 bump）
  - M3.4（Render 需要 timeline.json schema 完成 bump）

---

## 任务清单（5 个，6.7d）

### M2a-fix.1 — 设计规约 + 数据契约 + KPI 测量框架（Day 0, 1.1d）

**目标**: 在动任何 src/ 代码前，先把"二创风格修正"的所有契约 / 枚举 / KPI / fallback / UX 写进 design.md 和本文件，作为后续 Day 1-5 的最高约束源。

**关键设计决策**:
- **design.md 修订**: §17.1 升级为"5 种品类化预设矩阵"（含 `tv_追更` / `movie_roast` 等 M4 后做的预留）；§17.4 新增 fallback 矩阵；新增 **§17.5 两阶段 LLM 设计章节**（含流程图 + 缓存策略 + 失败兜底 + 成本分析）
- **三层封闭枚举集**（落入 design.md §17.5）:
  - `genre` (10 值): 电影 / 电视剧 / 动漫 / 短剧 / 综艺 / 电竞 / 教学 / Vlog / 纪录片 / 其他
  - `tone` (7 值): 温和讲解 / 俏皮幽默 / 紧张悬念 / 克制深沉 / 燃向激昂 / 冷静客观 / 其他
  - `narrative_intent` (5 值): 剧情速览 / 吐槽点评 / 情绪共鸣 / 信息盘点 / 其他
  - **每枚举值配 50 字描述符 + 1 个示例**（C4）
- **fallback 矩阵**（C5）: `(genre, narrative_intent) → preset` 映射表（如 `(电竞, 剧情速览) → movie_summary` / `(Vlog, 情绪共鸣) → anime_情绪`）
- **静态默认三元组**（F1）: `{genre='其他', tone='温和讲解', narrative_intent='剧情速览'}`，design.md 显式列 50 字 justification（"温和讲解最不易冒犯，适合作为失败兜底；剧情速览最常见使用场景"）
- **R1-R6 反模式正则扫描器**（K-style-1）: 实现 `src/autoclip/algo/style_violations.py`，纯正则零 LLM 成本；返回 `{R1: count, R2: count, ..., R6: count, hit_rate: float}`
- **UX 4 意图按钮规约**（U1/U2）: 落入 design.md §17.6 表格（按钮文案 + emoji + 副文案 + hover 示例图占位）；M3.7 Web UI 实现时直接读取此规约

**涉及文件**:
- Modify: `docs/plans/2026-05-04-autoclip-design.md`（§17.1 升级 + §17.4 加 fallback 矩阵 + §17.5 两阶段 LLM 章节 + §17.6 UX 规约）
- Create: `src/autoclip/algo/style_violations.py`（R1-R6 正则扫描器）
- Create: `tests/unit/test_style_violations.py`（每个 R1-R6 各 2 用例 = 12 用例 + 1 个集成用例）

**验收标准**:
- [ ] design.md 新增章节 §17.5 / §17.6，三层枚举集 + fallback 矩阵 + 默认三元组 + UX 规约全部就位
- [ ] `style_violations.py` 12+ 用例全绿，对 job_20260505_144455 timeline.json 的 12 句反例命中率 100%（验证扫描器有效）
- [ ] 本文件（M2a-fix-narrative-style.md）所有"待 v0.7 修订追加"的引用都已落地

**关联 KPI**: K-style-1 / K8
**依赖**: 无 → **阻塞**: M2a-fix.2-5
**预估工时**: **1.1d**（设计规约 0.5d + 三层枚举 0.1d + UX 规约 0.1d + 容错默认 0.1d + R1-R6 正则扫描器 0.3d）

---

### M2a-fix.2 — 架构骨架 + movie_summary 实现 + 两阶段 LLM 端到端（Day 1, 1.5d）

**目标**: Day 1 内拿到端到端可运行产物给用户 review——`movie_summary` 单种 preset + 两阶段 LLM 跑通真实动物视频，输出"温和讲解"风格而非"零情绪复读"。

**关键设计决策**:
- **PresetRegistry class wrapper**（A1）: 实现 `src/autoclip/prompts/style_presets/registry.py`：
  ```
  class PresetRegistry:
      def __init__(self): self._presets: dict[str, StylePreset] = {}
      def register(self, name: str, preset: StylePreset) -> None: ...
      def get(self, name: str) -> StylePreset: ...
      def list_all(self) -> list[str]: ...
  STYLE_PRESETS = PresetRegistry()
  ```
  - design.md §17.5 显式标注"约定式非契约式"（每加 preset 需手动 import + register；不做插件热加载）
- **StylePreset dataclass**: 每个 preset 导出 `{STYLE_DESCRIPTION: str, FEW_SHOT_EXAMPLES: list[FewShotPair], GENRE_TONE_MAP: dict[str, str], MAX_PROMPT_TOKENS: int=3000}`
- **重写 `src/autoclip/prompts/style_presets/plot_summary.py` → `movie_summary.py`**:
  - STYLE_DESCRIPTION 重写为"B 站头部影视解说 UP 主，谷阿莫流，信息压缩 24:1"
  - FEW_SHOT_EXAMPLES：4 组 genre 分组（电影/教育-儿童/纪录片/电竞）正反例（每组 1 正 1 反）
  - GENRE_TONE_MAP：{'教育': '温和讲解', '儿童': '温和讲解', '动作': '紧张悬念', ...}
- **两阶段 LLM 实现**:
  - 新建 `src/autoclip/prompts/genre_inference.py`（第 1 次调用 prompt：输入 plot_outline，输出 `{genre, tone, narrative_intent}` JSON）
  - 修改 `src/autoclip/pipeline/scripting.py`：在 narrative_ir 调用前插入第 1 次调用；用户已通过 CLI 预填 `narrative_intent` 时跳过推断（U1 决议）；失败走静态默认三元组（F1）
- **通用反模式 R1-R6 注入**: 修改 `src/autoclip/prompts/narrative_ir.py` SYSTEM_PROMPT_TEMPLATE 顶部插入 R1-R6 硬约束（约 800 token），下面注入 `{style_description}` + `{few_shot_examples}`
- **schema 字段先加 Optional**（A2 部分提前）: `NarrativeIR` 加 3 个字段（genre_inference / tone_recommendation / narrative_intent），全部 Optional[str] = None；正式 schema bump 在 M2a-fix.4
- **A/B 盲测准备**（K-style-4 部分）: Day 1 commit 前生成 `before.json` (狗屎版 timeline.json 复制) + `after.json` (修正版)，等用户找朋友盲测

**涉及文件**:
- Create: `src/autoclip/prompts/style_presets/registry.py` (PresetRegistry)
- Create: `src/autoclip/prompts/style_presets/movie_summary.py` (重写自 plot_summary.py)
- Delete (after migration): `src/autoclip/prompts/style_presets/plot_summary.py`（old）
- Create: `src/autoclip/prompts/genre_inference.py`（第 1 次调用 prompt）
- Modify: `src/autoclip/prompts/narrative_ir.py`（SYSTEM_PROMPT_TEMPLATE 加 R1-R6 + few-shot 注入点）
- Modify: `src/autoclip/pipeline/scripting.py`（加第 1 次 LLM 调用 + 失败兜底逻辑）
- Modify: `src/autoclip/models/timeline.py`（NarrativeIR 加 3 个 Optional 字段）
- Create: `tests/unit/test_preset_registry.py`（含"加 1 个新 preset 自动识别"测试）
- Create: `tests/unit/test_genre_inference.py`（含 mock 失败降级测试 F2）
- Modify: `tests/unit/test_narrative_ir_prompt.py`（验证 R1-R6 已注入）

**验收标准**:
- [ ] 端到端跑动物视频（job_20260505_144455 同条件），新 timeline.json 的 narrative_ir.text 不含 R1-R6 反模式（K-style-1 ≤ 10%，hard gate）
- [ ] 第 1 次调用输出的 `{genre, tone, narrative_intent}` 落入 timeline.json 可见（验证可观测性）
- [ ] mock 第 1 次失败 → 走静态默认三元组 → 第 2 次调用仍正常生成（F2）
- [ ] PresetRegistry 自动识别测试通过（加 1 个 stub preset 文件 → registry 自动 list 出来）
- [ ] 全套 pytest 净增 ≥ 8 用例全绿
- [ ] commit 后用户找 3-5 朋友盲测 before.json vs after.json，多数判定"after 更好"（K-style-4 sanity）

**关联 KPI**: K-style-1（hard gate）/ K-style-4（sanity） / K8
**依赖**: M2a-fix.1 → **阻塞**: M2a-fix.3-5
**预估工时**: **1.5d**（架构骨架 0.3d + movie_summary 重写 0.5d + 两阶段 LLM 实现 0.4d + 失败模式测试 0.1d + 端到端验证 + commit 0.2d）

---

### M2a-fix.3 — 扩展 shortdrama_推流 + anime_情绪 + 3 部对比测试（Day 2, 1d）

**目标**: 在 Day 1 验证架构 OK 的基础上，并行实现剩余 2 种品类预设；跑 3 部不同品类视频对比效果，验证"风格根据内容来"的设计落地。

**关键设计决策**:
- **`shortdrama_推流.py`**: STYLE_DESCRIPTION 锚定"小帅小美流，每 15-30s 反转，悬念断点 + 付费引导"；FEW_SHOT 4 组（霸总/战神/重生/赘婿）；GENRE_TONE_MAP 强制 tone='紧张悬念'
- **`anime_情绪.py`**: STYLE_DESCRIPTION 锚定"LexBurner / 阿斗归来了流，ACG 黑话 + 情绪放大 1:1"；FEW_SHOT 4 组（燃番/恋爱番/治愈/热血）；GENRE_TONE_MAP {'动漫': '燃向激昂', '番剧': '燃向激昂', ...}
- **每 preset prompt 硬上限 3000 tokens**（P1）: utils/tokens.py 加 `assert_preset_within_budget(preset_name, prompt_text)`，超限抛 `PresetTooLargeError`；CI 测试卡死
- **3 部对比测试视频**:
  - 短剧片段 (15s × 5 集 = 75s) → 用 shortdrama_推流
  - 电影预告 (90s) → 用 movie_summary
  - 动漫名场面 (60s) → 用 anime_情绪
- **横向对比报告**: 生成 `reports/M2a-fix-day2-comparison.md`，并排展示 3 部视频在 3 种 preset 下的 narrative_ir.text，肉眼对比"风格切换是否成功"

**涉及文件**:
- Create: `src/autoclip/prompts/style_presets/shortdrama_推流.py`
- Create: `src/autoclip/prompts/style_presets/anime_情绪.py`
- Modify: `src/autoclip/prompts/style_presets/__init__.py`（registry register 调用）
- Modify: `src/autoclip/utils/tokens.py`（加 `assert_preset_within_budget()`）
- Create: `tests/unit/test_preset_token_budget.py`
- Create: `reports/M2a-fix-day2-comparison.md`（人工对比报告）

**验收标准**:
- [ ] 2 个新 preset 实现，prompt token < 3000
- [ ] 3 部视频 × 3 种 preset = 9 次端到端跑通；K-style-1 全部 ≤ 10%
- [ ] 横向对比报告显示"切换 preset 后 narrative_ir.text 风格明显不同"（不是同一种语气换皮）
- [ ] 全套 pytest 净增 ≥ 6 用例

**关联 KPI**: K-style-1 / K8 / P1
**依赖**: M2a-fix.2 → **阻塞**: M2a-fix.4
**预估工时**: **1.0d**（shortdrama 0.3d + anime 0.4d + token budget 0.1d + 3 部对比 0.2d）

---

### M2a-fix.4 — CLI + state.json schema bump + timeline.json schema bump + 缓存（Day 3, 1d）

**目标**: 把 Day 1-2 的硬编码 / Optional 字段全部转成正式 schema；CLI 入参打通；plot_outline 缓存生效；K6 预算改 90s 落到 design.md 和测试。

**关键设计决策**:
- **CLI 入参**: 修改 `scripts/test_scripting_realvideo.sh` + 未来的 FastAPI POST /api/jobs：加 `--style-preset` 参数（可选，缺省走 LLM 自动推断 narrative_intent）+ `--narrative-intent` 参数（可选，对应 4 意图按钮预填）
- **state.json schema bump 5 字段**（Q5 决议）:
  - `style_preset: Literal['shortdrama_推流','movie_summary','anime_情绪']` (default='movie_summary')
  - `binder_version: Literal['hint_uniform','intent_routed']` (default='hint_uniform'，预留 M2b-light 用)
  - `genre_inference: Optional[str]` (LLM 输出后填)
  - `tone_recommendation: Optional[str]` (LLM 输出后填)
  - `narrative_intent: Optional[str]` (LLM 推断 OR CLI 预填)
- **timeline.json schema bump 7 字段**（A2，含 state.json 5 + 顶层 2）:
  - 顶层 `llm_call_log: list[LLMCallRecord]`（每次调用 1 条）
  - 顶层 `cost_summary: CostSummary{total_tokens, estimated_usd}`
- **migration 测试**: 旧 timeline.json / state.json (Session 19 之前) 加载时所有新字段填默认值/None，零数据迁移
- **第 1 次调用缓存**（P3）: 实现 `src/autoclip/utils/llm_cache.py`：key = SHA256(`plot_outline_json + style_preset + (cli_narrative_intent or '')`)，scope = `{job_dir}/.llm_cache/`，job 结束自动清理（K9 兼容）
- **K6 预算改 90s**（P2）: utils/tokens.py 顶部常量 `M2A_K6_BUDGET_SEC = 90`（原 60）；design.md K6 章节加 50 字 justification（"二创风格修正版含 2 次 LLM + 1 次重试链，最坏路径 65s + 25s buffer"）
- **LlmCallsRecorder 升级**: M2a.1 commit eecab0f 已实现的 callback handler，本 task 增强：每条 record 加 `cache_hit: bool` 字段；`cost_summary` 在 stage 结束时由 handler 汇总写入 timeline.json

**涉及文件**:
- Modify: `src/autoclip/models/state.py`（JobStateFile 加 5 字段 + migration default）
- Modify: `src/autoclip/models/timeline.py`（NarrativeIR 字段去 Optional 改 required；顶层加 LLMCallRecord + CostSummary）
- Create: `src/autoclip/utils/llm_cache.py`
- Modify: `src/autoclip/utils/tokens.py`（K6 常量改 90s + 加 5 字段 schema 验证）
- Modify: `src/autoclip/providers/llm/callback.py`（LlmCallsRecorder 加 cache_hit + cost_summary）
- Modify: `scripts/test_scripting_realvideo.sh`（加 --style-preset / --narrative-intent 入参）
- Modify: `scripts/_realvideo_dispatcher.py`（写 state.json 时填 5 字段）
- Create: `tests/unit/test_state_migration.py`（旧 state.json 加载零迁移）
- Create: `tests/unit/test_timeline_migration.py`（同上）
- Create: `tests/unit/test_llm_cache.py`（缓存命中/失效）
- Modify: `tests/integration/test_scripting_e2e.py`（schema 升级断言 + K6 改 90s）

**验收标准**:
- [ ] state.json + timeline.json 5+7 字段 schema bump 完成；migration 测试 100% 向后兼容
- [ ] CLI 入参跑 4 种组合: (a) 默认 / (b) 指定 preset / (c) 指定 intent / (d) 同时指定，全部正确
- [ ] 缓存命中场景（同 plot_outline 跑 2 次不同 tone）第 1 次调用时间 < 100ms（vs 首次 ~30s）
- [ ] K6 ≤ 90s 在 3 部测试视频上全部满足
- [ ] 全套 pytest 净增 ≥ 8 用例

**关联 KPI**: P1 / P2 / P3 / F3 / A2 / K8
**依赖**: M2a-fix.3 → **阻塞**: M2a-fix.5
**预估工时**: **1.0d**（CLI + dispatcher 0.2d + schema bump + migration 0.3d + 缓存 0.2d + K6 改预算 0.1d + 集成测试 0.2d）

---

### M2a-fix.5 — M2b-light（narrative_intent 路由绑定）+ Day 5 batch judge + M2b-full 决策（Day 4-5, 2.1d）

**目标**: 启动 M2b-light（基于 `narrative_intent` 字段路由 3 种绑定策略），跑 3-5 部真实视频，用 batch LLM-as-judge 评估 K-style-2/3，最终输出 M2b-full "做" 或 "不做" 的决策报告。

**关键设计决策**（**Day 4 上半 = M2b-light 实现，Day 4 下半 + Day 5 = 评估**）:

#### Day 4：M2b-light 实现
- **绑定策略路由**: 实现 `src/autoclip/algo/intent_routed_binder.py`：
  - `narrative_intent='剧情速览'` → 复用 M2a 已实现的 `bind_naively`（hint_uniform）
  - `narrative_intent='吐槽点评'` → 新算法 `bind_open_window`（在段落 hint 时间区间内随机选镜头，不强求精确）
  - `narrative_intent='情绪共鸣'` → 同 `bind_open_window`（语义上情绪句不强求与画面对齐）
  - `narrative_intent='信息盘点'` → 复用 `bind_naively`
  - `narrative_intent='其他'` → 默认 `bind_naively`
- **`binder_version='intent_routed'`** 通过 state.json 切换；`'hint_uniform'` 保留作 M2a 兼容路径

#### Day 5：batch LLM-as-judge + M2b-full 决策
- **judge prompt 设计**（K-style-2/3）:
  - LLM = deepseek-reasoner（评分类任务推理模型更准）
  - prompt 复用 STYLE_PRESETS 的 FEW_SHOT_EXAMPLES 作为锚点（避免重复造轮子）
  - 输出 schema: `{video_id: {K_style_2: int(0-100), K_style_3: int(0-100), reasoning: str}}`
  - **batch**: 3-5 个 video × 2 KPI = 6-10 次评估，1 次 LLM 调用搞定（输出 JSON 数组）
- **judge 落盘**: `{job_dir}/judge_reports/style_eval_{timestamp}.json`，与 timeline.json 同级，方便人工抽样核对
- **M2b-full 决策报告**: 生成 `reports/M2b-full-decision.md`，含:
  - K-style-2/3 在 3-5 部视频的统计结果
  - K1/K2/K3（如有数据）当前水平
  - 是否启动 M2b-full 的明确建议（含 4d 工时是否值得的 ROI 分析）
- **M2b-full 启动条件**（design.md §17.5 显式定义）:
  - 启动: K1 < 50% 且业务方明确要求精确绑定（如 M3 Render 阶段反馈"画面对不上严重影响产品"）
  - 不启动: K1 ≥ 50% 或 narrative_intent 路由已能覆盖 80%+ 用例

**涉及文件**:
- Create: `src/autoclip/algo/intent_routed_binder.py`
- Modify: `src/autoclip/algo/greedy_binder.py`（加 `bind_open_window()` 函数）
- Modify: `src/autoclip/pipeline/scripting.py`（根据 state.binder_version 选择 binder）
- Create: `src/autoclip/algo/style_judge.py`（LLM-as-judge prompt + 调用封装）
- Create: `tests/unit/test_intent_routed_binder.py`
- Create: `tests/unit/test_style_judge.py`（mock judge LLM）
- Create: `reports/M2b-full-decision.md`（Day 5 末尾人工生成）

**验收标准**:
- [ ] 3-5 部真实视频跑通 binder_version='intent_routed'，narrative_intent → 策略路由 100% 命中
- [ ] batch judge 跑通，K-style-2 ≥ 80% / K-style-3 ≥ 30%
- [ ] M2b-full 决策报告产出，含明确"做/不做"建议 + ROI 分析
- [ ] 全套 pytest 净增 ≥ 6 用例

**关联 KPI**: K-style-2 / K-style-3 / K1（部分） / K8
**依赖**: M2a-fix.4 → **阻塞**: M2b-full（如启动）/ M3 全部
**预估工时**: **2.1d**（M2b-light 实现 1.0d + batch judge 0.5d + 3-5 部跑通 + 评估 + 决策报告 0.6d）

---

## 工时汇总

| Task | 工时 | Day |
|---|---|---|
| M2a-fix.1 设计规约 + 数据契约 + KPI 框架 | 1.1d | Day 0 |
| M2a-fix.2 架构骨架 + movie_summary + 两阶段 LLM | 1.5d | Day 1 |
| M2a-fix.3 扩展 shortdrama_推流 + anime_情绪 + 对比 | 1.0d | Day 2 |
| M2a-fix.4 CLI + 双 schema bump + 缓存 + K6=90s | 1.0d | Day 3 |
| M2a-fix.5 M2b-light + batch judge + M2b-full 决策 | 2.1d | Day 4-5 |
| **合计** | **6.7d** | **5-6 工作日** |

vs 原 brainstorming 收敛后估算 5.7d，**+1.0d 来自 8 角度 critique 的 19 项 P0 修正**（详见上方 critique 表）。

---

## 风险与 mitigation

| ID | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| MR1 | Day 1 movie_summary 跑出来效果不达 K-style-1（≤10%） | 🟡 中 | 🔴 高 | 快速回滚到 Day 0 设计规约迭代；调整 R1-R6 正则规则 |
| MR2 | anime_情绪 ACG 黑话 LLM 写不好（最高难度预设） | 🟡 中 | 🟡 中 | M2a-fix.3 末期允许降级为 `anime_推荐`（盘点式更易写）；不影响 movie_summary / shortdrama 上线 |
| MR3 | schema bump 12 字段（5+7）触发数据迁移 bug | 🟢 低 | 🟡 中 | M2a-fix.4 strict migration 测试 + Optional 字段全部明确 default |
| MR4 | batch judge LLM 评分不一致（同一 video 跑 2 次分数差 > 20） | 🟡 中 | 🟡 中 | judge prompt 加 temperature=0 + 同 batch 跑 2 次取平均 |
| MR5 | 用户找不到 3-5 个朋友做盲测（K-style-4 sanity） | 🟢 低 | 🟢 低 | 退化为用户自评 + 1 个 LLM-as-judge"模拟用户偏好"作为补充 sanity |
| MR6 | M2b-full 启动条件无法明确达成或拒绝（数据模糊） | 🟡 中 | 🟢 低 | Day 5 决策报告允许结论是"M2c 阶段再决定"，不强迫二选一 |

---

## 与 M2b 的关系（v0.7 拆分说明）

**M2b 原始范围**（v0.6 及之前）: BM25 反向检索 + time_resolver + bind_with_evidence + KPI 评估 + Prompt v2，5 任务 6.2d

**v0.7 拆分后**:
- **M2b-light** (2d) → 已并入本里程碑 **M2a-fix.5**（narrative_intent 路由绑定 + batch judge + M2b-full 决策）
- **M2b-full** (4d) → 保留在 [M2b-scripting-robust.md](./M2b-scripting-robust.md)，**仅当 M2a-fix.5 决策报告建议启动时才执行**；否则整个 M2b 跳过
- **M2b 原 5 个 task**（M2b.1-M2b.5）→ 统一归入 M2b-full 范畴，5 个 task 合并描述但工时不变（仍 4-6.2d）

**判定路径**:
```
M2a-fix.5 末尾决策报告
    ├── 建议启动 M2b-full → 进入 M2b（4d 实施）
    └── 建议不启动     → 跳过 M2b，直接进 M3
```

---

## 附录：与 brainstorming Q1-Q8 + 19 项 P0 修正的追溯关系

每个任务关联的 brainstorming 决议和 P0 修正 ID 已在任务块的"关键设计决策"中显式标注（`Q1` / `Q2` / ... / `C1-C5` / `K-style-1-4` / `P1-P3` / `F1-F3` / `U1-U2` / `A1-A2`）。完整辩论过程见 `.context/changes.md` Session 20 段。

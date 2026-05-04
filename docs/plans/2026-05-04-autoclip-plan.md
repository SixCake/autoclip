# AutoClip MVP 实施总控文档

> **本文档定位**：进度把控 + 任务索引 + 执行导航规则。
> **关键设计与任务详情请按需读取 `tasks/` 子文档**，避免一次性加载全部内容。

**Goal**: 在 5-6 周内实现一个端到端可用的影视/电视剧/动漫二创解说视频生成器 MVP — 用户上传单部影片，系统输出可直接在剪映中打开的草稿包。

**权威设计文档**: [`./2026-05-04-autoclip-design.md`](./2026-05-04-autoclip-design.md)（v0.4，2282 行；冲突时以 Part IV §21-§23 为准）

**Tech Stack 速览**: Python 3.11 + FastAPI + SQLite + multiprocessing + **本地 faster-whisper（v0.4）** + 通义千问 + 火山豆包 TTS + pyJianYingDraft

---

## 1. 文档拓扑

```
docs/plans/
├── 2026-05-04-autoclip-design.md           ← 设计文档 v0.3（不可变）
├── 2026-05-04-autoclip-plan.md             ← 本文件（总控）
└── tasks/
    ├── M1-infrastructure.md                ← M1 详细任务（基础设施 + Ingest + Index）
    ├── M2a-scripting-main.md               ← M2a 详细任务（Scripting 主链路）
    ├── M2b-scripting-robust.md             ← M2b 详细任务（narrative IR + KPI）
    ├── M3-render-web-compliance.md         ← M3 详细任务（Render + Web + 合规）
    └── M4-e2e-validation.md                ← M4 详细任务（E2E + 风格扩展）
```

---

## 2. 进度总览

| Milestone | 周 | 任务数 | 详细文档 | 状态 | 完成 % |
|---|---|---|---|---|---|
| **M1** — 基础设施 + Ingest + Index | W1 | 8 | [`tasks/M1-infrastructure.md`](./tasks/M1-infrastructure.md) | ✅ 已完成 | 8/8 (M1.1-M1.8 ✅; 含 10 轮 self-check sealed via LIM#9 + LIM#8 FIXED in M2a-kickoff cleanup) |
| **M1-e2e** — M1 milestone 人工 e2e 验收 | W1↔W2 衔接 | 1 | [`tasks/M1-infrastructure.md`](./tasks/M1-infrastructure.md) §M1.8 验收标准 | ⚪ 已跳过（用户决策直接进 M2a） | 0.2d 人工任务（uvicorn + curl POST /api/jobs；M1 已 185 单元/集成测试覆盖足够） |
| **M2a** — Scripting 主链路 | W2 | 6 | [`tasks/M2a-scripting-main.md`](./tasks/M2a-scripting-main.md) | 🟡 brainstorming 中 | 0/6 |
| **M2b** — Scripting 鲁棒性 + narrative IR | W3 | 5 | [`tasks/M2b-scripting-robust.md`](./tasks/M2b-scripting-robust.md) | ⏳ 待开始 | 0/5（总工时 6.0d→6.2d，adhoc plan-3 BM25 升级）|
| **M3** — Render + Web + 零知识架构 | W4 | 9 | [`tasks/M3-render-web-compliance.md`](./tasks/M3-render-web-compliance.md) | ⏳ 待开始 | 0/9 |
| **M4** — E2E + 风格扩展 + 多片回归 | W5 | 5 | [`tasks/M4-e2e-validation.md`](./tasks/M4-e2e-validation.md) | ⏳ 待开始 | 0/5 |
| Week 6 — Buffer | W6 | — | — | ⏳ 待开始 | — |

**总任务数**：33 个 + buffer

---

## 3. 路线图与里程碑依赖

```
Week 1   Week 2     Week 3       Week 4         Week 5     Week 6 (buffer)
├── M1 ─┼── M2a ───┼── M2b ─────┼── M3 ────────┼── M4 ────┼─────────────┤
基础设施   Scripting   Scripting     Render+Web      E2E +     KPI 验收 +
+Ingest    主链路      鲁棒性          +合规           风格扩展   关键修复
+Index                (narrIR)                       +自评分
```

**关键路径**（不可并行）：
`M1.1 → M1.3 → M1.6 → M1.7 → M2a.1 → M2a.3 → M2b.1 → M2b.2 → M3.4 → M4.1`

**并行机会**：
- M3.7（Web 模板）可与 M2a 并行 — 前端不依赖 Scripting
- M3.6（JsonTimelineExporter）可与 M3.4（剪映 Exporter）并行 — 独立模块
- M3.1（TTSProvider）可在 M2a 末尾提前接入 — 可解锁 TTS 调试

---

## 4. 验收 KPI 跟踪表（来源：design.md §18.2）

| # | 维度 | 指标 | 目标值 | 关联 Milestone | 状态 |
|---|---|---|---|---|---|
| K1 | 算法 | 绑定准确率 | ≥ 70% | M2b | — |
| K2 | 算法 | evidence 召回率 | ≥ 80% | M2b | — |
| K3 | 算法 | fallback 触发率 | ≤ 30% | M2b | — |
| K4 | 体验 | 用户主观评分 | ≥ 4/5 | M4 | — |
| K5 | 体验 | 人工调优时间 | ≤ 1h/部 | M4 | — |
| K6 | 工程 | 端到端耗时 | ≤ 16min/90min | M4 | — |
| K7 | 工程 | 任务可恢复性 | resume 成功 | M1+M3 | — |
| K8 | 工程 | 单元测试覆盖率 | 核心算法 ≥ 70% | 全程 | — |
| K9 | 合规 | raw 文件已删除 | 100% | M3 | — |
| K10 | 合规 | 草稿不含原片路径 | 100% | M3 | — |
| K11 | 合规 | 协议勾选拦截 | 100% | M3 | — |

**P0 KPI**（不达标则 MVP 不发布）：K1, K2, K3, K9, K10, K11
**P1 KPI**（评估影响范围，必要时延长 W6 buffer 修复）：K4, K5, K6, K7, K8

---

## 5. 工程基线（所有 milestone 共享）

### 5.1 项目目录结构（Day 1 锁定，不可随意变更）

```
autoclip/
├── pyproject.toml                ← Poetry 依赖
├── Makefile                      ← 常用命令封装
├── .env.example
├── src/autoclip/
│   ├── config.py                 ← Settings (pydantic-settings)
│   ├── main.py                   ← FastAPI 入口
│   ├── db.py                     ← SQLAlchemy engine/session
│   ├── models/                   ← ORM (Video/Job/Timeline/Shot/...)
│   ├── providers/                ← 外部服务抽象
│   │   ├── asr/{base,aliyun}.py
│   │   ├── llm/{base,qwen}.py
│   │   └── tts/{base,volcengine}.py
│   ├── pipeline/                 ← 5 stage handlers
│   │   ├── runner.py             ← multiprocessing + 状态机调度
│   │   ├── state.py              ← state.json 原子读写
│   │   └── {ingest,index,scripting,assembly,render}.py
│   ├── algo/                     ← 核心算法（可独立测试）
│   │   ├── shot_detector.py
│   │   ├── narrative_ir.py
│   │   ├── time_resolver.py      ← M2b post-validation
│   │   └── greedy_binder.py
│   ├── exporters/                ← Render 输出层
│   │   ├── base.py
│   │   ├── jianying.py
│   │   └── json_timeline.py
│   ├── prompts/                  ← LLM Prompt 模板
│   │   ├── plot_outline.py
│   │   ├── narrative_ir.py
│   │   ├── style_presets/
│   │   └── self_evaluate.py
│   ├── compliance/               ← 零知识架构
│   ├── api/                      ← FastAPI 路由
│   ├── web/                      ← Jinja 模板
│   └── utils/                    ← ffmpeg / json_repair / retry
├── tests/{unit,integration,e2e,fixtures}/
├── data/                         ← 运行时数据，.gitignore
└── scripts/                      ← 开发辅助
```

### 5.2 通用约定

- **测试金字塔**：单元 30+ / 集成 5-8 / E2E 1
- **Provider 抽象**：所有外部服务（ASR/LLM/TTS/Exporter）必须先有 base 接口，再实现具体 Provider
- **Commit 规范**：遵守 [`.cursor/rules/250.md`](../../.cursor/rules/250.md) 图标规范（✨feat / 🐛fix / 📝docs / 🎨refactor / ⚡️perf / ✅test / 🔧build / 🚧chore）
- **TDD 优先**：每个 task 先写关键测试用例 → 再实现 → 再 commit（具体测试代码由执行阶段编写）
- **零知识架构**：raw 文件 24h 自动删除；草稿包不含原片绝对路径；数据库脱敏

### 5.3 环境变量

执行任何 task 前，先确保 `.env` 包含：`DASHSCOPE_API_KEY`, `VOLCENGINE_TTS_APP_ID`, `VOLCENGINE_TTS_TOKEN`, `DATA_DIR`。

**v0.4 变更**：原 v0.3 要求的 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` / `ALIYUN_ASR_APPKEY` / `ALIYUN_ASR_TOKEN` 已**全部移除**（本地 ASR 不需凭证）；新增可选项 `WHISPER_MODEL_SIZE` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE`（默认值 `large-v3` / `auto` / `default`）。模板见 `.env.example`（M1.1 创建，本次 adhoc 同步更新）。

---

## 6. 执行导航规则（重要）

### 6.1 何时读哪个文档

| 你要做的事 | 应读取的文档 |
|---|---|
| 了解任何技术决策的"为什么" | [`./2026-05-04-autoclip-design.md`](./2026-05-04-autoclip-design.md) Part III（v0.3） |
| 跟踪整体进度、查找 task 归属 | 本文件（`autoclip-plan.md`） |
| 执行 M1 任意 task | 仅读 [`tasks/M1-infrastructure.md`](./tasks/M1-infrastructure.md) |
| 执行 M2a 任意 task | 仅读 [`tasks/M2a-scripting-main.md`](./tasks/M2a-scripting-main.md) |
| 执行 M2b 任意 task | 仅读 [`tasks/M2b-scripting-robust.md`](./tasks/M2b-scripting-robust.md) |
| 执行 M3 任意 task | 仅读 [`tasks/M3-render-web-compliance.md`](./tasks/M3-render-web-compliance.md) |
| 执行 M4 任意 task | 仅读 [`tasks/M4-e2e-validation.md`](./tasks/M4-e2e-validation.md) |
| 处理用户协议/法律相关 | [`./../legal/user-agreement-v0.1.md`](../legal/user-agreement-v0.1.md) |

### 6.2 Task 详情文档的统一格式

每个 `tasks/Mx-*.md` 中的 task 块都包含：

| 字段 | 说明 |
|---|---|
| **Task ID + 标题** | 如 `M1.3 — 文件状态机` |
| **目标** | 1 句话说清楚要做什么 |
| **关键设计决策** | 接口签名 / 数据结构 / 算法选择 / 关键约束（不写实现代码） |
| **涉及文件** | Create / Modify / Test 路径清单 |
| **测试策略** | 核心用例描述（不写测试代码） |
| **验收标准** | 可量化、可勾选的 checklist |
| **关联 KPI** | 引用本文件第 4 节的 K1-K11 |
| **依赖** | 前置 task / 阻塞下游 task |
| **预估工时** | 0.5d / 1d / 2d 等 |

### 6.3 实施顺序约定

- **强制串行**：必须按 milestone 顺序执行（M1 → M2a → M2b → M3 → M4）
- **同 milestone 内**：默认按 task ID 顺序，但允许并行机会标记的任务并行
- **跨 milestone 提前**：M3.7（Web）和 M3.1（TTSProvider）可在 M2a 末尾启动

---

## 7. 进度更新规则

### 7.1 何时更新本文件

- 完成单个 task：在对应 milestone 的子文档里勾选 task checkbox，**本文件第 2 节"进度总览"的"完成 %"对应更新**
- 完成单个 milestone：第 2 节状态从 `🟡 进行中` → `✅ 已完成`
- 触发风险/阻塞：在第 8 节"风险登记"追加条目

### 7.2 KPI 验证时机

- M2b 结束时：跑 `scripts/manual_label.py` 验证 K1, K2, K3，写入第 4 节
- M3 结束时：跑集成测试验证 K7, K9, K10, K11
- M4 结束时：跑 E2E 验证 K4, K5, K6
- 全程：每个 task 完成后跑 `pytest --cov` 跟踪 K8

---

## 8. 风险登记（动态更新）

| ID | 风险 | 概率 | 影响 | 缓解策略 | 状态 |
|---|---|---|---|---|---|
| R1 | pyJianYingDraft 库不维护 / 与最新剪映版本不兼容 | 🟡 中 | 🔴 高 | M3.6 JsonTimelineExporter 防御实现 | 监控中 |
| R2 | ~~阿里云 ASR 长视频接口限速~~ | — | — | **v0.4 解除**（已切本地 faster-whisper） | ✅ 已解决 |
| R15 | faster-whisper 模型权重首次下载慢/失败（**2026-05-04 19:03 实例触发：huggingface.co 在国内网络不通**） | 🟡 中 | 🟡 中 | **三档联合方案**：① `scripts/preload_whisper.py` 自动 export `HF_ENDPOINT=https://hf-mirror.com`；② 镜像 SDK 仍超时则用 `huggingface-cli download` 命令行；③ 终极兜底：`curl -L` 手动下载 5 个文件到 `~/whisper_models/faster-whisper-<size>/`，用 `LocalWhisperProvider(model_size=本地路径)` 吃本地权重（faster-whisper 原生支持，零网络） | ⚠️ 部分缓解（实例触发后已加固脚本，待用户实测确认本地路径方案可用） |
| R16 | LLM 角色推断在多人混淆场景出错（ADR-009 路径 2） | 🟡 中 | 🟢 低 | M2a.2 prompt 加 few-shot；v1.1 加声纹兜底 | 待 M2a 验证 |
| R17 | 低配 Mac 跑 large-v3 内存爆 | 🟢 低 | 🟡 中 | Settings 暴露 model_size 配置项，文档建议降到 medium | 待 M1.5 验证 |
| R18 | 双轨 normalize 磁盘占用 2x（v0.5） | 🟡 中 | 🟢 低 | M3.8 cleanup 删除 low 保留 hd；Settings 可选 `INGEST_SINGLE_TRACK=1` 强制单轨降级（应急开关） | 待 M1.6 实现 |
| R3 | LLM 幻觉 evidence_keywords | 🟡 中 | 🔴 高 | M2b post-validation 反向校验兜底 | 待 M2b 验证 |
| R4 | macOS spawn 模式下子进程模型加载慢 | 🟡 中 | 🟢 低 | 子进程内独立加载；进程池复用 | 待 M1 验证 |
| R5 | KPI（K1-K3）不达标导致 MVP 延期 | 🟡 中 | 🟡 中 | Week 6 buffer 兜底；P0 KPI 严守 | 待 M2b 验证 |

> 详见 design.md §10 + §16.5 + §19.5 完整风险评估。

---

## 9. 变更日志

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-05-04 | v0.1 | 初始总控文档创建（替代旧的 3847 行实现代码版） |
| 2026-05-04 | v0.2 | adhoc：ASR 改本地 faster-whisper + large-v3（design.md Part IV §21）；MVP 加 LLM 推断角色（§22 ADR-009）；M1.5 工期 1d→0.5d；总工期 -0.5d；R2 解除，新增 R15/R16/R17 |
| 2026-05-04 | v0.3 | adhoc：M1.6 Ingest 改**双轨 normalize**（normalized_low.mp4 给检测 + normalized_hd.mp4 给出片，design.md Part IV §24 ADR-010）；M1.6 工期 1.0d→1.3d；M1 总工期 6.5d→6.8d，全工期 31.5d→31.8d；新增 R18（双轨磁盘成本 2x） |
| 2026-05-04 | v0.4 | M1 milestone 收尾 + M2a kickoff adhoc plan sync（commit b5af64e 起 8 处改动）：① M1.6 双轨 normalize 已实际落地（commit 7a74d10 主实现）；② M1.8 Index handler 完成（10 轮 self-check 通过 LIM#9 HARD STOP sealed at commit 41471ad；181→185 pytest passed）；③ tech_debt 新增 LIM#9（self-check 无限套娃防御）+ LIM#8 已 FIXED（commit b5af64e: runner.py StageHandler Protocol docstring 重写 + 4 反向断言测试）+ LIM#10 NEW（test_runner.py 单跑 isolation bug，pre-existing M1.4 问题，deferred）；④ M2a.5 BindingMethod enum 补 EVIDENCE_LOWCONFIDENCE 预留枚举值；⑤ M2a.6 Scripting 时长预算据 K6 总预算结构修正 4min/90min→2.5min/90min；⑥ M2a.6 style_preset 改用环境变量 AUTOCLIP_STYLE_PRESET 注入，state.json schema 改造推迟 M2b.5；⑦ M2a.1 加 pyproject.toml 依赖声明（dashscope^1.20 + tenacity^9.0 + pydantic^2.0）；⑧ M2b.1 keyword_match 算法选型 字符 Jaccard → rank_bm25，工时 1.0d→1.2d，M2b 总工时 6.0d→6.2d（W3 buffer 占用 0.2d，剩余 0.6d）|


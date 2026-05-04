# AutoClip 会话纪要 v0.2

> 会话时间：2026-05-04 10:34 ~ 11:25
> 阶段：brainstorming → design.md v0.1 → adhoc-revision → design.md v0.2
> 模型：claude4.7-opus

## 一、Brainstorming 决策路径（10 题收敛 → v0.1）

| # | 问题 | 用户最终选择 |
|---|---|---|
| 1 | 核心使用场景 | A 长视频→短解说 |
| 2 | 原始素材类型 | A1 影视/电视剧/动漫 |
| 3 | 产品定位 | B 创作助手 |
| 4 | 输入形态 | A 单视频输入 |
| 5 | 索引模态 | Z 混合策略（用户反问后修正） |
| 6 | 文稿粒度 | P3 双层结构 |
| 7 | 解说音轨 | V1 纯 TTS |
| 8 | 混音策略 | M3-c（AI 推荐+用户调整） |
| 9 | 时长档位 | T1 优先 |
| 10 | 验收级别 | S1 Demo 级 |

## 二、首轮开放问题回复（v0.1 → v0.2 触发）

用户回复：Q1=C 现代Web / Q2=B 无GPU / Q3=接受

→ AI 提示 Q1=C 与 S1 工期冲突，需选 A/B/C 三种处理方式

→ **用户神来一笔**："有没有办法将生成结果放入到剪映里进行剪辑"

## 三、Adhoc 决策路径（v0.1 → v0.2）

1. AI 调研发现 `pyJianYingDraft` 开源库（GuanYixuan/pyJianYingDraft）
2. AI 提出 4 种产品形态方案（A 维持原方案 / B 纯草稿+CLI / C 双模式 / D 草稿+极简Web）
3. 用户选 **D 剪映草稿模式 + 极简 Web 状态页**

## 四、关键交互回顾

1. **第 5 题用户反问** 修正了 AI 的过度推荐，确立了"二创不是流水线"的产品调性
2. **第 8/10 题范围冲突** AI 主动拆分 M3-c → MVP 实做 M2+M3-b
3. **剪映对接** 由用户主动发现，AI 调研后转化为 v0.1 → v0.2 的颠覆性升级
   - 编辑器工程量 1500-3000 行 → 0 行
   - MVP 工期 4 周 → 3 周
   - Render 阶段从 FFmpeg 拼接 → JSON 序列化（提速 6-10 倍）
   - 商业上从"和剪映竞争编辑器"升级为"为剪映创作者提供 AI 上游工具"

## 五、本次会话最终产出

| 产物 | 路径 | 行数 | 状态 |
|---|---|---|---|
| 技术设计文档 v0.2 | `docs/plans/2026-05-04-autoclip-design.md` | 1419 | ✅ |
| 项目脚手架 | git + `.context/` + `docs/plans/` + `.gitignore` | — | ✅ |
| 上下文索引 | `.context/state.json` + `design.md` + `changes.md` + `chat.md` + `plan.md`(占位) | — | ✅ |

## 六、design.md 章节速览（v0.2 完整）

**Part I（v0.1）**
1. 项目概述
2. 核心决策矩阵
3-4. 系统架构（C4 Level 1-2）
6. 数据模型（10+ 实体）
7. 端到端数据流（T0~T5）
8. 5 个核心模块详细设计
9. 7 个 ADR
10. 9 项风险评估
11. S1 演进路线图（4 周）
12. 待用户确认的 3 个开放问题（已解决）

**Part II（v0.2 adhoc 修订）**
13. ADR 修订与新增（ADR-004 修订 / ADR-007 修订 / ADR-008 新增）
14. Render 模块重写（替代原 §8.5）
15. 路线图修订（替代原 §11.1，4 周 → 3 周）

## 七、待办（下一会话）

- [ ] 用户 review design.md v0.2 Part II
- [ ] 进入 `writing-plans` skill，输出 `docs/plans/2026-05-04-autoclip-plan.md`
- [ ] plan.md 应按 3 周 3 milestones 拆解为可执行 task list（M3 已细化为 7 个子任务）

---

## 三轮多角度评审（v0.2 → v0.3）

### 评审角色
- 🧑‍💻 Eve（产品经理）：用户价值 / 商业模式
- 🧑‍🔬 Lin（算法工程师）：AI 可行性 / 文稿质量
- 🧑‍🔧 Rao（架构师）：工程复杂度 / 依赖风险
- 🧑‍⚖️ Wu（法律顾问）：版权 / 平台合规

### 关键洞察
1. **Lin 揭穿绑定算法的核心假设漏洞**：LLM 不会精准遵守 linked_plot_nodes，需要升级为 narrative IR + post-validation
2. **Rao 指出 3 周工期幻觉**：诚实估算应为 5-6 周，含 narrativeIR 升级 + 测试 + 合规
3. **Wu 提出零知识架构**：MVP 必须前置，否则商业化前必然返工
4. **Eve 提出量化 KPI**：用 11 项指标取代"看得过去"的模糊验收

### 用户决策
- 全盘接受 12 项修订（5 P0 + 5 P1 + 2 P2）
- design.md 进化到 v0.3，2107 行

### v0.3 最终交付
| 产物 | 路径 | 状态 |
|---|---|---|
| 设计文档 v0.3 | `docs/plans/2026-05-04-autoclip-design.md` (2107 行) | ✅ |
| 用户协议草稿 | `docs/legal/user-agreement-v0.1.md` | ✅ |
| 上下文索引 | `.context/state.json` + `design.md` + `changes.md` + `chat.md` | ✅ v0.3 |

## 待办（下一会话）
- [ ] 用户 review design.md v0.3 Part III
- [ ] 进入 `writing-plans` skill，输出 `docs/plans/2026-05-04-autoclip-plan.md`
- [ ] plan.md 应按 5-6 周 4 milestones 拆解（M1 / M2a / M2b / M3 / M4 + buffer）
- [ ] 每个 task 含：前置依赖 / 估时 / 涉及文件 / 验收标准 / KPI 关联

---

## plan.md 重构（v0.3 → v0.4）

### 用户反馈
"章节计划文档太大了，计划只需要做关键设计，别实现，交给后续代码开发来实现"

### 决策
全文档拆分 + 详尽度降级：
- 主控（progress + index + nav）+ 5 子文档（每 milestone 一个）
- 子文档只写「关键设计」，不写实现代码
- 旧 3847 行单文件直接删除（git 是天然留档）

### 流程纪律
按 892.md 应用 adhoc-changes 流程：
1. 分类变更（doc structure refactor，不影响 design）
2. 二次确认（提供 A/B/C 方案，用户选 A 直接删）
3. 重置 todo（8 项新计划）
4. 执行（删旧 → 写主控 → 写 5 子文档）
5. 同步 .context/（state + plan + changes + chat）
6. 向用户呈现

### v0.4 最终交付
| 产物 | 路径 | 行数 | 状态 |
|---|---|---|---|
| 主控文档 | `docs/plans/2026-05-04-autoclip-plan.md` | 220 | ✅ |
| M1 子文档 | `docs/plans/tasks/M1-infrastructure.md` | 336 | ✅ |
| M2a 子文档 | `docs/plans/tasks/M2a-scripting-main.md` | 292 | ✅ |
| M2b 子文档 | `docs/plans/tasks/M2b-scripting-robust.md` | 282 | ✅ |
| M3 子文档 | `docs/plans/tasks/M3-render-web-compliance.md` | 466 | ✅ |
| M4 子文档 | `docs/plans/tasks/M4-e2e-validation.md` | 320 | ✅ |
| 总计 | — | **1916** | ✅ |
| 上下文索引 | `.context/{state.json,plan.md,changes.md,chat.md}` | — | ✅ v0.4 |

## 待办（下一会话）
- [ ] 用户 review plan.md v0.4（主控 + 5 子文档）
- [ ] 用户确认后选择执行路径：
  - 路径 A: subagent-driven-development（同会话，每 task 派遣子 agent）
  - 路径 B: parallel session + executing-plans（新会话独立批量执行）
- [ ] 实际开发：从 M1.1（Poetry 脚手架）开始，逐 task 执行 + commit

---

## Session 2 — M1.1 Execution

### 流程纪律遵循
按 `executing-plans` skill：
1. Step 1 (Load and Review Plan) — 读 M1.1 设计 + 提出 3 个 critical questions（commit 策略 / 依赖补全 / batch size）
2. 用户回复 "Y Y Y" 确认
3. Step 2 (Execute Batch) — 单 task batch 执行 M1.1
4. Step 3 (Report) — 完成后向用户报告

### 执行节奏
| 子步骤 | 状态 | 备注 |
|---|---|---|
| Pre-task: 文档基线 commit | ✅ | f788ae5 (10 files, 4205 lines) |
| M1.1-a/b/c/d 并行创建 11 个文件 | ✅ | 单次 shell heredoc，322 行 |
| M1.1-e poetry install + test | ⚠️→✅ | 3 次自动失败后用户手动完成；4 测试 PASSED |
| M1.1-f ruff lint + commit + amend | ✅ | 2d5fcce (amend 后保持历史干净) |
| M1.1-g worktree-save 会话结束 | ✅ | state.json + changes.md + chat.md |

### 关键决策记录
- **Q1 commit 策略**: 用户选 Y → docs 单独基线 commit + M1.1 独立 commit（避免文档与代码混入大 commit）
- **Q2 依赖补全**: 用户选 Y → 一次装齐 19 个包（含 markdown / httpx / pytest-cov 等遗漏的）
- **Q3 batch size**: 用户选 Y → M1.1 单独验收（脚手架影响所有后续 task，需谨慎）
- **Python 版本约束**: ^3.11 → `>=3.11,<3.14`（适配 macOS Python 3.13.3，明确支持范围）
- **PyPI 源**: 国内网络问题 → 配置阿里云镜像（pyproject.toml 项目级配置）
- **Lint 修复策略**: amend 到 M1.1 commit 而非新建"修 lint"小 commit（保持 commit 历史干净）

### 重要风险/教训
1. **shell 60s 超时是硬限制** — `poetry install` 类长任务必须交给用户手动；后续 M3.4 剪映兼容性测试可能也会超时
2. **Python 3.13 + 较新依赖** — pydantic 2.13 / sqlalchemy 2.0.49 / fastapi 0.115 都 OK，未来 M2.4 dashscope SDK 调用要注意 3.13 兼容性
3. **ruff 严格性** — 默认开启 F401/F841/B 等规则，写测试时要避免 unused import/var

### 待办（Session 3 启动）
- worktree-context 加载（git log + .context 三件套）
- 进入 M1.2 SQLAlchemy ORM（推荐 batch = M1.2 + M1.3 一起，因为是 M1.4 的双前提）
- 关键设计已锁在 .context/state.json next_task.key_design_decisions

---

## Session 2 cont. — M1.2 + M1.3 Batch

### 流程纪律遵循
按 `executing-plans` skill Step 2: Execute Batch — 双 task 串行执行（ORM 在前因状态机不依赖 DB）

### 执行节奏
| 子步骤 | 状态 | 备注 |
|---|---|---|
| M1.2-a 6 个 ORM 模型并行创建 | ✅ | 326 行，单次 shell heredoc |
| M1.2-b db.py engine + session 工厂 | ✅ | 113 行 |
| M1.2-c test_models.py | ✅ | 7 cases PASSED in 0.48s |
| M1.3-a state.py JobStateFile | ✅ | 213 行 |
| M1.3-b test_state_machine.py | ✅ | 11 cases PASSED in 0.05s |
| Verify: ruff + 全量 test + coverage | ⚠️→✅ | ruff 8 errors (7 auto-fix + 1 manual F821) |
| 双 commit: 1c9bb0d + 5454bda | ✅ | 历史干净 |
| worktree-save 同步 .context/ | ✅ | state.json + changes.md + chat.md |

### 关键决策记录
- **TimelineSegment 字段完全实现 design.md §17.4**：source_*_sec + target_*_sec + duration_sec invariant + binding_method SAEnum + use_original_audio_volume default 0.15
- **零知识架构 schema 级强制（K10）**：Video.filename_hash unique 索引，无 abs path 字段
- **预留字段不偷懒**：agreement_accepted_at（M3.9）+ regenerate_count（M4.4）+ binder_version（M2b.5）现在就放好，避免后续 schema 迁移
- **TYPE_CHECKING import 处理 ruff F821**：SQLAlchemy 字符串 forward reference 的标准做法，零运行时开销
- **测试用例数 = acceptance × 1.75-2.75**：M1.2 要求 3+ 实写 7；M1.3 要求 4 实写 11；多覆盖边界场景
- **`os.replace` 替代 `os.rename`**：Windows 兼容（os.rename 在 Windows 上目标存在会抛异常）

### 重要发现
1. **ruff 严格度**（与 M1.1 教训一致）— 写 datetime.timezone.utc 会被 UP017 提示改 datetime.UTC（Python 3.11+ 推荐）
2. **覆盖率 93%** — 远超 K8 目标 70%，db.py 的 63% 主要是 contextmanager 异常分支未触发，可接受（M1.4 加集成测试时自然提升）
3. **0.27s 跑 22 测试** — in-memory SQLite + StaticPool 性能极佳，未来加 ORM 测试无 perf 压力

### 待办（Session 3 启动）
- worktree-context 加载（git log + .context 三件套自动加载）
- batch 决策：M1.4 单 task（1.5d 复杂）vs M1.4+M1.5 双 task（M1.5 ASR 独立可并行）— 推荐单 task
- 关键设计已锁在 .context/state.json next_task.key_design_decisions

---

## Session 3 — M1.4 Single-Task Batch (FastAPI + PipelineRunner)

### 流程纪律遵循
按 `executing-plans` skill Step 1 (review plan critically) → Step 2 (execute batch) → Step 3 (report)
- 在执行前 critical review 提出 3 个设计澄清点（Q1/Q2/Q3）并按推荐方案直接落地（用户已说"不需要询问，直接执行"）
- 5 个子步骤串行执行（a→b→c→d→e）
- Verify 阶段发现 spawn 跨进程 bug，调试后修复

### 执行节奏
| 子步骤 | 状态 | 备注 |
|---|---|---|
| M1.4-a runner.py PipelineRunner | ✅ | 239 行（首次）→ 260 行（含 env-var fix） |
| M1.4-b api/jobs.py 4 个 endpoint | ✅ | 276 行，POST/GET×2/cancel |
| M1.4-c main.py FastAPI app | ✅ | 81 行，lifespan 挂 engine 到 app.state |
| M1.4-d test_runner.py 单元测试 | ✅ | 360 行，11 cases，FakeProcess mock |
| M1.4-e 集成测试 + fixtures | ✅ | 297 行，10 cases（resume 3 + api 7） |
| Verify: 全测 + ruff + uvicorn 实启 | ⚠️→✅ | 3 集成测试失败（spawn cross-process bug）+ 2 lint，全部修复 |
| commit 71e5f07 | ✅ | 9 文件 1273 行 |
| worktree-save | ✅ | state.json + changes.md + chat.md |

### 关键决策记录
- **Q1 测试隔离**：单元 mock mp.Process（FakeProcess 类同步执行 target 收集 exitcode），集成才真起 spawn 子进程
- **Q2 零知识**：source.mp4 路径不入 state.json，按约定 `data/jobs/{job_id}/source.mp4` 推导（K10 精神延伸）
- **Q3 cancel 粒度**：PipelineRunner 仅 stage 间检测，handler 内由 handler 自己 poll（M1.6 ingest 已写在关键设计里）
- **Bootstrap Video pattern**：POST 上传时无法预先知道 hash，先建 placeholder Video → 流式写文件 + hash → 找到现存 Video 就替换 video_id 并删 placeholder（避免 FK 冲突 + 实现 dedup）
- **app factory pattern**：`create_app()` 工厂 + 模块顶层 `app = create_app()`，测试每次创建新 app 隔离 + 生产 uvicorn 直接用模块引用

### 关键 Bug 复盘（Lesson Locked）
**Bug**：integration test 3 个 case 全报 `Stage X failed`
**根因**：spawn 子进程是新解释器，re-import `runner.py` 后 `_STAGE_MODULES` 是模块原始定义的空 tuple，**完全看不到父进程的 monkeypatch**
**修复**：增加 `AUTOCLIP_EXTRA_STAGE_MODULES` 环境变量通道（spawn 默认继承 env），测试改用 `monkeypatch.setenv`
**教训**：任何需要跨 spawn 边界传递的状态，必须用 **env vars / 文件 / 进程 args**，模块级 monkeypatch 完全失效。这条规则锁进 state.json 的 `cross_process_channels` 字段

### 重要发现
1. **覆盖率从 93% 跳到 96%**：集成测试同时填了 db.py 的覆盖率（63% → 98%）
2. **46 测试 1.69s**：spawn 子进程开销不大（10 个真子进程仍秒级）
3. **POST upload 测试**：用 `httpx.TestClient` + `io.BytesIO` 模拟 multipart，无需起真 uvicorn

### 待办（Session 4 启动）
- worktree-context 加载（git log + .context 三件套）
- batch 决策：M1.5 单 task（ASR Provider，需 Aliyun token，集成测试默认 skip）
- 关键设计已锁在 .context/state.json next_task.key_design_decisions（5 步流水线 + tenacity 重试 + OSS 路径约定 + zero-knowledge 强制 finally 删除）

---

## Session 4 — 设计澄清问答（2026-05-04 15:04）

> 阶段：executing（M1.5 启动前）— 纯问答澄清，无代码/文档改动
> 模型：claude4.7-opus

### 用户问题
1. 视频音轨/文本/视频分离后，如何与角色关联？怎么知道谁说了什么话？
2. 阿里云 ASR 是干嘛的？

### Q1 答复要点：MVP 不做角色识别
- `ASRSentence.speaker_id: str | None` 字段存在但**MVP 永远是 None**（design.md §6.2 "Schema 一次到位"）
- 三模态产物（shots.json / asr.json / normalized.mp4）**唯一对齐键是时间戳**，无角色维度
- Scripting 阶段 LLM 通过对白文本**自行推断**剧情，不依赖 speaker label
- design.md §3 第 35 行明确：❌ 角色识别、说话人分离、情感标签 = MVP 不做
- v1.1+ 路径：speaker diarization (pyannote-audio) + 声纹聚类 → 用户/LLM 映射到角色名

### Q2 答复要点：阿里云 ASR = 音频→带时间戳对白 JSON
- 位置：Index 阶段三模态之一（镜头/对白/画面）的"对白"路
- 输入：`audio.wav` (16kHz mono) → 输出：`ASRSentence[]`（idx/start/end/text/confidence）
- 选型演进（ADR-004）：v0.1 Whisper-large 本地 → v0.2 OpenAI Whisper API → **v0.3 阿里云 ASR**（中文 WER 5-10%，¥0.5-2/次）
- M1.5 实现要点（已锁在 state.json）：5 步流水线（OSS upload → SubmitTask → poll → parse → finally DELETE，K9/K10 零知识）
- 抽象 `ASRProvider` 接口，可换 OpenAI/火山，业务代码不动

### 关键认知校准
- **LLM 不会看画面**，电影理解 100% 依赖 ASR 输出的对白时间轴
- 纯无对白电影兜底：ASR <30 句/10min → fallback VLM；纯无对白 → 警告用户改用 v1.1 强 VLM 模式

### 本轮无变更
- 代码：未改动
- 文档：未改动（design.md / plan.md / 子 task 文档均未触碰）
- state.json：next_task 仍为 M1.5，进度未变
- git：工作区干净（仅 .context/ 未跟踪，符合预期）

---

## Session 4 续 — v0.4 本地化 + 角色推断 adhoc 执行（2026-05-04 15:20-15:35）

> 阶段：brainstorming → adhoc-changes → executing
> 触发：用户两个需求 — (1) 阿里云 ASR 要上传 OSS 太麻烦，要本地方案 (2) MVP 要做角色识别

### Brainstorming 收敛（3 题）
| Q | A |
|---|---|
| Q1 角色识别核心目的 | A: 让 LLM 知道 A/B 角色对话以提升解说稿质量 |
| Q2 角色实现路径 | 路径2: LLM 文本推断（不做声纹，零工期成本） |
| Q3 本地 ASR 选型 | faster-whisper + large-v3（跨平台 + 未来可升 WhisperX） |

### Adhoc 执行（13 项 todo 全部完成）
**文档 (6)**：
- design.md +175 行（Part IV §21-§23: ADR-004 三度修订 + ADR-009 新增 + 工期/KPI 影响汇总）
- plan.md（env 段 + 风险表 R2→解除 / +R15/R16/R17 + changelog v0.2）
- M1-infrastructure.md（M1.5 整体重写：AliyunASR → LocalWhisperProvider；总工时 7d→6.5d）
- M2a-scripting-main.md（M2a.2 PlotOutline 角色卡 + M2a.3 prompt 强制角色称呼）
- .context/design.md（索引 v0.3→v0.4）
- .context/plan.md（executing 阶段标记）

**代码 (4)**：
- config.py：-aliyun_asr_app_key/-aliyun_asr_token；+whisper_model_size/device/compute_type
- .env.example：-ALIYUN_ASR_*；+WHISPER_*
- test_config.py：+test_whisper_defaults +test_no_legacy_aliyun_asr_fields（46→48 用例）
- pyproject.toml：-alibabacloud-nls-python-sdk；+faster-whisper "^1.0.0"

**Context (2)**：
- state.json v0.4.4→v0.4.5（next_task M1.5 完全改写 + v04_adhoc_summary 段落新增）
- changes.md +71 行（Session 4 完整变更记录）

### 验证结果
- pytest: **48 passed in 1.56s** ✅
- 模型 schema 不变：ASRSentence.speaker 仍 `Optional[str]=None`
- ASRProvider 抽象基类签名不变：`transcribe(audio_path, language) -> ASRResult`

### 关键认知锁定
- **ADR-009 路径 2 的本质**：LLM 推断角色这步无论如何跑不掉（即使做声纹也要 LLM 把 Speaker_00 映射成"男主"），所以先做路径 2 是 ROI 最高的选择
- **本地 ASR 强化零知识架构**：音频文件**从未离开本地**（vs 阿里云 OSS 短暂上传），K9 实质更彻底
- **M3 Pro 是关键资产**：large-v3 实时率 4-5x 让本地 ASR 在工程上完全可行（90min 电影 12-18min）

### 下一步（Session 5 启动）
- M1.5 实现 LocalWhisperProvider（已锁在 state.json next_task）
- 关键文件：providers/asr/{base.py,local_whisper.py} + tests/unit/test_asr_base.py
- 工期：0.5d
- 提醒：首次跑要下载 3.1GB 权重（HF mirror），考虑写 `scripts/preload_whisper.py`

---

## Session 5 — M1.5 LocalWhisperProvider 实现（2026-05-04 18:22-18:35）

> 阶段：executing → M1.5 单 task 闭环
> 模型：claude4.7-opus

### 流程
1. worktree-context: state.json next_task M1.5 已锁
2. 跳过 brainstorming (已在 Session 4 收敛，无新设计变更)
3. todo 11 项全部 completed
4. 流程: 装依赖 → 8 文件分两批创建 → ruff/pytest 修复 → 验证 → 同步 .context

### 关键技术决策
- WhisperModel 模块级 import (替代 lazy)，让 unittest.mock.patch 能定位 attribute
- 模型单例 _MODEL_SINGLETON 缓存键用 (model_size,)，spawn 子进程独立加载
- 后处理 3 大过滤: 空文本 / 低置信度 (avg_logprob<-1.0) / 短-glitch (<1s 且 <4 字符)
- 失败兜底: load 失败 → medium → RuntimeError (覆盖 R17)

### 验证结果
- pytest: 74 passed, 1 skipped in 1.87s (新增 26 单元 + 1 集成 skipped)
- ruff: All checks passed (修了 5 errors + 4 文件 format)
- coverage: providers/asr 99% (local_whisper.py 100% ✅)
- read_lints: clean

### Pitfall 记录（Session 5 教训）
- ❌ 错误尝试: TYPE_CHECKING 块 + 函数内 lazy import → patch 失败 5 用例
- ✅ 修复: 直接模块级 `from faster_whisper import WhisperModel` (faster-whisper 是必需依赖, 导入开销 <200ms 可忽略)
- 经验: **依赖 mock.patch 的模块, 被 mock 的目标必须出现在模块顶层 namespace**

### 下一步 (Session 6)
- M1.6 Ingest stage: FFmpeg 视频归一化 + 音频抽离; 1.0d
- 文件: utils/ffmpeg.py + pipeline/ingest.py + 2 测试
- 系统依赖: ffmpeg + ffprobe (需先 brew install ffmpeg 确认)

---

## Session 6 — M1.6 v0.5 adhoc 双轨 normalize 文档同步（2026-05-04 18:41-19:00）

> 阶段：adhoc-changes (按 892.md 第二阶段，计划外改动必须先 design.md + plan.md 同步再执行)
> 模型：claude4.7-opus

### 触发与流程纠错
- 用户先要求"测试脚本，并行往下走"
- 我误启动 brainstorming（错误：M1.6 在 plan 子文档已有完整定义，应走 executing-plans 而非 brainstorming）
- 用户纠正："不是新功能啊，文档在 docs/plans 下不是已经约定好执行计划了吗"
- 切换到 executing-plans skill: 读计划 → critical review → 提 3 个澄清问题
- 用户回答 3 问题: 1=job_dir 是用户上传磁盘目录 / 2=双轨 (low+hd) / 3=测试视频 ~/Downloads/英语启蒙误区与脑科学.mp4

### Critical review 决策链
- 双轨 normalize 是 plan 外的设计变更（plan 原写"720p 25fps 单轨"），按 892.md 必须先文档先行再代码
- 用户确认"完整同步：M1-infra + plan + design + state.json → 然后再写代码"

### Adhoc 同步执行
1. 读取 4 个文档当前内容（M1.6 L226-263 + plan.md 全文 + design.md §6.1 + Part IV §23 末尾 + state.json next_task）
2. 4 处 file_replace + 1 次 design.md heredoc 追加 §24 ADR-010
3. 1 次 commit (56cf8e4)
4. 测试命令补发用户

### 关键认知锁定
- **executing-plans vs brainstorming 边界**: plan 子文档已有"关键设计决策"+"涉及文件"+"测试策略" → executing-plans；只有 plan 完全空白或新增任务才 brainstorming
- **adhoc 流程**: 设计变更（哪怕用户拍板）也必须先同步 design.md → plan.md → state.json → commit → 再写代码（避免文档与代码漂移）
- **ADR-010 完整决策范本**: 决策/约束/进度方案/磁盘成本/为什么不选 A/B/C/回滚策略 — 5 个维度齐全才算合格 ADR

### Pitfall 记录
- ❌ 误启动 brainstorming → 用户纠正
- ❌ 测试视频路径写错 (~/Downloads/test.mpt 不存在) → ls 实测后用户改用真实路径
- ✅ 实测 fixture 是 1376×768 而非 1080p → ADR-010 已写入"原片向下兼容"规则避免无效 upscale

### 下一步 (Session 7)
- M1.6 实现 batch 1: utils/ffmpeg.py 4 个函数 + test_ffmpeg_utils.py 单元测试
- M1.6 实现 batch 2: pipeline/ingest.py handler + 单元测试 (mock subprocess)
- M1.6 实现 batch 3: integration test + 接到 PipelineRunner + commit
- 用户并行：跑 test_whisper_realvideo.sh 验证 M1.5 实测

---

## Session 7 (2026-05-04 19:03 ~ 21:31) — R15 实例处置 + M1.6 完整闭环

### 关键流程决策
- **R15 实例触发处置**: huggingface.co Connection reset → 不卡 brainstorming, 直接代码加固 (脚本智能识别 + 三档兜底), 风险登记升级为部分缓解状态
- **executing-plans skill 严格按 batch=3 推进**: Batch 1 (utils) → stop & report → 用户 GO → Batch 2 (handler) → stop & report → 用户 GO → Batch 3 (集成测试 + commit + worktree-save)
- **handler 签名冲突解决**: M1.6 plan 文档写 `(job_dir, stage_name)` 但 runner.py 实际契约是 `(job_dir) -> None` → 以代码为准, 文档过时不阻塞实施
- **测试隔离 bug 修复模式**: 模块级注册 + 后续测试 clear_stage_handlers() → 用 importlib.reload(ingest_mod) 在断言前重新触发注册 (避免改动 runner.py 现有契约)

### 流程亮点
- ✅ **batch=3 严格 stop & report**: 每批结束都用统一格式报告 (实施清单 + 验证全绿 + ADR 映射 + 下批预告 + 1 个待决策小问题)
- ✅ **lint-as-code-review**: 每批末尾 ruff + read_lints + pytest (本批 + 全量回归) 三件套, 不全绿不进 commit
- ✅ **用户授权"按你的方式"**: 默认决策 = loguru (与 local_whisper.py 一致) + skip-by-default 集成测试 (与 M1.5 一致), 强约定优于强讨论

### Pitfall 记录
- ❌ Batch 2 SIM117 4 处嵌套 with 没一次写对 → ruff --fix 没自动改完, 必须手动重写
- ❌ Batch 2 test_handler_registered_on_import 单测过、全测挂 → 经典 module-level 副作用 + 测试污染问题, 先 grep clear_stage_handlers 定位元凶 test_runner.py L38/40, 再用 importlib.reload 修复
- ❌ 多次 echo 中文导致 zsh `character not in range` → 后续 shell 命令一律 ASCII

### Verification (Session 7 累计)
- 3 个 commit: 433c8b4 (R15 缓解) + 7d15cc5 (M1.6 实现) + 待 commit (worktree-save 收尾)
- 测试总数: 74 → 133 passed + 4 skipped (净增 +59 测试)
- M1 进度: 5/8 → 6/8 (M1.6 ✅)

### 下一步 (Session 8)
- M1.7 PySceneDetect shot detector (0.5d, 依赖 M1.6 normalized_low.mp4) — algo/shot_detector.py + 单测
- M1.8 Index stage handler (1d) — 集成 M1.5 ASR + M1.7 shot + 删 audio.wav (兑现 K9)
- M1 milestone 端到端验收 (M1.8 完成后): curl POST /api/jobs 5min 短片 2min 内完成 ingest+index, shots.json + asr.json 产出

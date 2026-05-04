# M1 — 基础设施 + Ingest + Index（Week 1）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §6 / §16.1 / §16.2 / §16.5

## 🎯 Milestone 目标
搭建项目骨架、ORM、FastAPI + multiprocessing 任务执行框架、文件状态机；实现 Ingest（视频归一化 + 音频抽离）和 Index（镜头切分 + ASR 调度）两个 stage；端到端跑通"上传视频 → 拿到 shots.json + asr.json"。

## ✅ Milestone 验收
- [ ] 上传 90min 电影到 `POST /api/jobs`，10 分钟内 ingest+index 流水线全部 done
- [ ] `data/{job_id}/state.json` 状态正确流转
- [ ] `data/{job_id}/shots.json` + `asr.json` 完整产出
- [ ] 中途 kill 进程后重启能从 checkpoint 恢复
- [ ] `POST /api/jobs/{id}/cancel` 能停止任务
- [ ] 单元测试覆盖率 ≥ 70%（针对 state machine / models / ffmpeg utils）

## 📊 关联 KPI
- **K7**（任务可恢复性）：M1 必须达成 resume 验证
- **K8**（单元测试覆盖率 ≥70%）：本 milestone 起步建立基线
- **K9**（raw 文件已删除）：M1.8 完成后 audio.wav 应被自动清理

## 🔗 依赖
- **前置**: 无（首个 milestone）
- **阻塞下游**: M2a 全部任务（依赖 shots.json + asr.json）

---

## 任务清单（8 个）

### M1.1 — 项目脚手架 + Poetry 依赖

**目标**: 初始化 Python 3.11 项目结构，锁定依赖版本，搭建 Settings 配置层。

**关键设计决策**:
- **包管理**: Poetry（src layout）
- **配置**: `pydantic-settings.BaseSettings`，所有 secret 用 `SecretStr` 包装，环境变量优先于 `.env` 文件
- **必备依赖**: fastapi / uvicorn / sqlalchemy 2.0 / pydantic 2.x / dashscope / **faster-whisper**（v0.4 替换原 alibabacloud-nls SDK） / scenedetect / ffmpeg-python / pyjianyingdraft / loguru / tenacity / pytest 8.x
- **目录结构**: 严格遵循总控文档第 5.1 节锁定的 src/autoclip/ 树
- **Settings 字段**: data_dir 自动创建，max_concurrent_jobs 默认 1（MVP 单机串行）

**涉及文件**:
- Create: `pyproject.toml`, `Makefile`, `.env.example`
- Create: `src/autoclip/__init__.py`, `src/autoclip/config.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`
- Create: `tests/unit/test_config.py`
- Modify: `.gitignore`（追加 `data/`, `.venv/`, `.env`, `__pycache__/`）

**测试策略**:
- 测试 Settings 从 env 加载所有必填字段（用 monkeypatch.setenv）
- 测试 data_dir 嵌套路径自动创建

**验收标准**:
- [ ] `poetry install` 无错误
- [ ] `make test-unit` 通过 ≥ 2 个 config 用例
- [ ] `.env.example` 列出所有必填环境变量

**关联 KPI**: K8（建立测试基线）
**依赖**: 无 → **阻塞**: M1.2 起所有任务
**预估工时**: 0.5d

---

### M1.2 — SQLAlchemy ORM 模型 + 数据库初始化

**目标**: 定义 6 个核心 ORM 模型（Video / Job / Shot / ASRSentence / Timeline / NarrationSentence / TimelineSegment），建立 SQLite engine + session 工厂。

**关键设计决策**:
- **SQLAlchemy 2.0 typed mapping**（`Mapped[T]` + `mapped_column`）
- **Base 类**: 提供 `created_at` / `updated_at` 公共字段（server_default + onupdate）
- **JobStatus enum**: 覆盖 5 stage × {running, done} + pending / failed / cancelled，用 SAEnum 落库
- **TimelineSegment 是 v0.3 §17.4 统一中间层**:
  - 字段: timeline_id / order_idx / source_shot_ids(JSON list) / source_start_sec / source_end_sec / narration_sentence_id(nullable) / binding_method
  - Render 阶段直接消费此表，不再有"两套时间表示"歧义
- **Video 表零知识架构**: 仅存 `filename_hash`（不存原始绝对路径）
- **SQLite 配置**: `check_same_thread=False`（multiprocessing 需要）

**涉及文件**:
- Create: `src/autoclip/models/{__init__,base,video,job,shot,timeline}.py`
- Create: `src/autoclip/db.py`（engine + SessionLocal + init_db）
- Create: `tests/unit/test_models.py`

**测试策略**:
- 用 in-memory SQLite (`sqlite:///:memory:`) 跑所有 ORM 测试
- 测试 Video + Job 创建关联
- 测试 TimelineSegment 的 source_shot_ids JSON 序列化往返
- 测试 Shot.duration_sec 计算属性

**验收标准**:
- [ ] 6 个模型可建表 (`Base.metadata.create_all`)
- [ ] TimelineSegment 字段完全符合 design.md §17.4 设计
- [ ] 单元测试 ≥ 3 个用例通过

**关联 KPI**: K8
**依赖**: M1.1 → **阻塞**: M1.4（API 需要 ORM）
**预估工时**: 1d

---

### M1.3 — 文件状态机（state.json 原子读写）

**目标**: 实现 `JobStateFile` 类，作为 multiprocessing 子进程之间唯一的状态同步介质。

**关键设计决策**（**核心，design.md §16.2**）:
- **原子写**: 写 `state.json.tmp` → `os.rename` 到 `state.json`（POSIX 原子保证）
- **状态字段**: `{job_id, video_hash, target_duration_sec, style_preset, created_at, updated_at, stages: {ingest:{status, progress, error?}, ...}}`
- **Stage enum**: INGEST / INDEX / SCRIPT / ASSEMBLY / RENDER（顺序固定）
- **StageStatus enum**: PENDING / RUNNING / DONE / FAILED
- **Cancel 信号**: `.cancel` 空文件存在 ≡ 已请求取消（子进程 polling 检测）
- **`next_stage_to_run()`**: 跳过 DONE 状态的 stage，从最早 PENDING/RUNNING/FAILED 开始（resume 语义）

**涉及文件**:
- Create: `src/autoclip/pipeline/__init__.py`
- Create: `src/autoclip/pipeline/state.py`
- Create: `tests/unit/test_state_machine.py`

**测试策略**:
- 测试 init 后 5 stage 都是 PENDING
- 测试 mark_stage 后无 `.tmp` 残留（原子写完整性）
- 测试 resume 场景：ingest=DONE + index=RUNNING，next_stage_to_run() 返回 INDEX
- 测试 cancel 信号：request_cancel → is_cancelled True

**验收标准**:
- [ ] 4 个核心场景测试全部通过
- [ ] 多进程并发写无文件损坏（用 pytest-xdist 验证可选）

**关联 KPI**: K7（resume 能力的基础）
**依赖**: M1.1 → **阻塞**: M1.4 / M1.6 / M1.7 / M1.8
**预估工时**: 0.5d

---

### M1.4 — FastAPI 主应用 + multiprocessing 任务执行框架

**目标**: 搭建 FastAPI app + `PipelineRunner` + `/api/jobs` CRUD 路由；POST /api/jobs 能 dispatch 到子进程。

**关键设计决策**（**core, design.md §16.2**）:
- **PipelineRunner**: 串行调度 5 stage，每个 stage 在独立 `mp.Process(spawn)` 里执行
- **Stage handler 注册机制**: 全局 dict `_STAGE_HANDLERS: dict[Stage, Callable]`，各 stage 模块在 import 时调用 `register_stage_handler()` 注册
  - `pipeline/__init__.py` 显式 import 所有 stage 模块以触发副作用
- **Spawn 模式**（非 fork）: macOS / Windows 兼容
- **失败检测**: `p.exitcode != 0` → 标记 stage FAILED；`status != DONE` 但 exitcode=0 → 标记 FAILED（防止 handler 漏标）
- **API 端点**:
  - `POST /api/jobs` (multipart upload + form fields) → 返回 `{job_id, status}`
  - `GET /api/jobs/{id}` → 返回 state.json 内容
  - `POST /api/jobs/{id}/cancel` → 写 `.cancel` 文件
- **lifespan hook**: app 启动时调用 `init_db()` 自动建表

**涉及文件**:
- Create: `src/autoclip/main.py`
- Create: `src/autoclip/pipeline/runner.py`
- Create: `src/autoclip/api/{__init__,jobs}.py`
- Create: `tests/unit/test_runner.py`
- Create: `tests/integration/{__init__,test_pipeline_resume}.py`

**测试策略**:
- 单元: 用 monkeypatch 替换 `_STAGE_HANDLERS` 为 fake handler，验证 5 stage 顺序执行
- 集成: 模拟 ingest=DONE + index=RUNNING 中断，重启 PipelineRunner(resume=True) 应只执行 index 及后续

**验收标准**:
- [ ] `make run` 启动后 `GET /health` 返回 `{"status":"ok"}`
- [ ] 端到端 dispatch 测试：POST → 子进程跑 → state.json 更新
- [ ] resume 测试：跳过 DONE stage 验证通过

**关联 KPI**: K7（resume 主链路）
**依赖**: M1.2 + M1.3 → **阻塞**: M1.6 / M1.7 / M1.8（stage 注册接入点）
**预估工时**: 1.5d

---

### M1.5 — ASRProvider 抽象 + LocalWhisperProvider 实现（v0.4 修订）

**目标**: 定义 ASR 接口契约，实现本地 faster-whisper Provider（design.md Part IV §21.1 ADR-004 三度修订）。

> **v0.4 变更说明**: 原计划实现 `AliyunASRProvider`（5 步 OSS 流水线），用户在 brainstorming 阶段（chat.md Session 4）明确反对该方案，改为本地 `faster-whisper + large-v3`。理由：零网络依赖、零云服务凭证、零计费、零知识架构强化（音频从未离开本地）。开发机 M3 Pro 实测可行。

**关键设计决策**:
- **ASRProvider abstract base**: 单方法 `transcribe(audio_path: Path, language: str = "zh") -> ASRResult`（接口签名不变）
- **数据结构**（与 ORM `models.shot.ASRSentence` 字段对齐）:
  - `ASRSentence(idx, start_sec, end_sec, text, confidence, speaker=None)`
  - `ASRResult(sentences: list, language, provider)` + `to_dict()`
  - 注意: `speaker` 字段 MVP 永远为 `None`（design.md §22 ADR-009：路径 2 LLM 推断角色，不做声纹）
- **LocalWhisperProvider 实现**:
  - 构造参数: `model_size: str = "large-v3"`, `device: str = "auto"`, `compute_type: str = "default"`
  - **模型单例**: `_MODEL_SINGLETON: WhisperModel | None = None`，避免子进程内重复加载 3GB 权重
  - `transcribe()` 调用 `model.transcribe(audio, language="zh", beam_size=5, vad_filter=True, word_timestamps=False)`
  - VAD 默认开启 → 静音段（电影约 30-40%）跳过推理，实际耗时 ≈ 12-18min/90min
  - 后处理：合并 < 1s 段、过滤 `avg_logprob < -1.0` 段、跳过空文本段
- **失败兜底**: 模型加载失败（OOM/网络）→ 降级到 `medium`（1.5GB）；仍失败抛 RuntimeError
- **配置接入**: 从 `Settings.whisper_model_size / whisper_device / whisper_compute_type` 读取
- **不再需要**: tenacity 重试（无网络）、OSS 上传/删除、阿里云 token

**新依赖**:
- Add: `faster-whisper = "^1.0"`（pyproject.toml）
- **Remove**: `alibabacloud-nls-python-sdk`（v0.3 错误引入，本任务清理）

**涉及文件**:
- Create: `src/autoclip/providers/__init__.py`
- Create: `src/autoclip/providers/asr/__init__.py`
- Create: `src/autoclip/providers/asr/base.py`（ASRProvider 抽象 + ASRSentence + ASRResult dataclass）
- Create: `src/autoclip/providers/asr/local_whisper.py`（LocalWhisperProvider 实现）
- Create: `tests/unit/test_asr_base.py`（dataclass + mock provider 测试）
- Create: `tests/integration/test_local_whisper.py`（默认 skip，需 `RUN_INTEGRATION=1` + 5s 中文样本 fixture）
- Modify: `pyproject.toml`（删 `alibabacloud-nls-python-sdk`，加 `faster-whisper`）
- (Optional) Create: `scripts/preload_whisper.py`（首次运行前下载模型权重，规避 R15 风险）

**测试策略**:
- 单元: ASRSentence/ASRResult dataclass 字段验证 / `to_dict()` 序列化 / mock provider 继承验证 / `speaker` 字段默认 None 断言
- 集成（手动）: 5s 中文样本音频，验证 sentences 非空、时间戳单调递增、`provider == "local-whisper"`

**验收标准**:
- [ ] 单元测试 ≥ 4 个用例通过
- [ ] 集成测试在本地一次手跑通过（开发者私下验证，5s 短音频 < 30s 完成）
- [ ] `audio.wav` 处理过程中**从未上传到任何远程服务**（grep 代码确认无 oss/http upload 调用）
- [ ] 模型单例验证：连续调用 transcribe 两次，模型仅加载一次（log 验证）

**关联 KPI**: K9（音频零知识——本地化后由 M1.8 删除 audio.wav 实现，本任务保证 ASR 不复制/外传音频）
**依赖**: M1.1（Settings 含 whisper_* 字段）→ **阻塞**: M1.8
**预估工时**: **0.5d**（v0.3 原估 1d，本地化后省去 OSS 流水线 + tenacity + cleanup）

**新增风险关联**:
- R15: 首次模型权重下载慢/失败 → 提供 `scripts/preload_whisper.py`
- R17: 低配 Mac 跑 large-v3 内存爆 → Settings 暴露 model_size 配置项

---

### M1.6 — Ingest Stage（FFmpeg 双轨 normalize + 音频抽离）（v0.5 修订）

**目标**: 实现第一个具体 stage handler — 把上传的原片**双轨归一化**（720p low 给检测 / 1080p hd 给出片）+ 抽离 16kHz mono WAV。

> **v0.5 adhoc（2026-05-04）**: 单轨 → 双轨 normalize（design.md Part IV §24 ADR-010）。工时 1.0d → 1.3d。详见 plan.md changelog v0.3。

**关键设计决策**:
- **ffmpeg 命令封装**（utils 层，可独立测试）:
  - `probe_video(path)` → ffprobe JSON（codec / resolution / fps / duration / has_audio）
  - `build_normalize_low_cmd(src, dst)` → 720p 25fps，libx264 + crf=23 + preset=medium + faststart + aac 128k
  - `build_normalize_hd_cmd(src, dst)` → 1080p 原帧率，libx264 + crf=21 + preset=medium + faststart + aac 192k
  - `build_extract_audio_cmd(src, dst)` → -vn -ac 1 -ar 16000 -c:a pcm_s16le（**喂给 LocalWhisperProvider**）
- **双轨产物语义**（design.md §6.1 Video 实体新增字段）:
  - `normalized_low.mp4` → 给 PySceneDetect（M1.7）+ KeyFrameDesc（v1.1+）
  - `normalized_hd.mp4` → 给 Render 阶段（M3.4 剪映 / M3.5 mp4 拼接）出片源
  - `audio.wav` → 给 ASR（M1.8）；通常从 hd 抽（保留更多采样信息）
- **进度上报**: 0.05（probe）→ 0.45（normalize_low）→ 0.85（normalize_hd）→ 0.95（audio）→ 1.0
- **Cancel 自检**: 在 4 个阶段之间各检查一次 `is_cancelled()`
- **失败兜底**: 任何异常都 mark FAILED 并抛出（让父进程感知 exitcode）；已生成的临时产物保留供 debug
- **handler 签名**: `run_ingest(job_dir: Path, stage_name: str)` → `register_stage_handler(Stage.INGEST, run_ingest)`
- **输入约定**: `job_dir/raw/<filename>` 存放用户上传的原片；handler 自动 glob 找第一个视频文件
- **磁盘成本**: 双轨产物约为单轨 1.6-2.0x；M3.8 cleanup 时**保留 hd 删除 low**（low 已经完成 shot/asr 索引使命）

**涉及文件**:
- Create: `src/autoclip/utils/{__init__,ffmpeg}.py`（probe + 3 个 build_* 函数）
- Create: `src/autoclip/pipeline/ingest.py`（run_ingest handler，4 阶段编排）
- Create: `tests/unit/test_ffmpeg_utils.py`（命令片段断言，不真跑 ffmpeg）
- Create: `tests/integration/test_ingest.py`（默认 skip，RUN_INTEGRATION=1 启用）
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import ingest`）

**测试策略**:
- 单元（必须）: 测试 4 个 build_* 函数返回的命令片段正确；test_run_ingest_emits_progress（mock subprocess）；test_run_ingest_cancel_between_stages
- 集成（手跑）: 真跑 ~/Downloads 用户视频前 30s，验证 3 个产物 + state DONE + 进度字段单调递增

**验收标准**:
- [ ] ffmpeg 命令构造测试通过（4 个 build_*）
- [ ] handler 单元测试通过（mock subprocess + cancel 自检 + 进度上报）
- [ ] 集成测试（手跑）：30s 短片 ingest 完成 < 30s（M3 Pro）
- [ ] state.json 进度字段正确递增（0.05 → 0.45 → 0.85 → 0.95 → 1.0）
- [ ] 产物三件套同时存在: normalized_low.mp4 + normalized_hd.mp4 + audio.wav

**关联 KPI**:
- K6（端到端耗时基线）— 双轨较单轨 +30-50% ingest 耗时；M4.5 端到端测试时验证总耗时仍 ≤ 16min/90min
- K1（绑定准确率）— 不变；low 轨道保证 720p 检测语义与 hd 出片语义对齐

**依赖**: M1.4（PipelineRunner）+ 系统已装 ffmpeg → **阻塞**: M1.7（需要 normalized_low.mp4） / M1.8（需要 audio.wav） / M3.4/M3.5（需要 normalized_hd.mp4）
**预估工时**: 1.3d（v0.5 修订；原 1.0d + 0.3d 用于第二轨编码 + 测试用例增加）

---

### M1.7 — Index Stage：镜头切分（PySceneDetect）

**目标**: 实现镜头切分算法封装，作为 Index stage 的前半部分。

**关键设计决策**（design.md §6.2 + ADR-003）:
- **算法**: PySceneDetect `ContentDetector(threshold=27.0, min_scene_len=0.8s*fps)`
- **threshold 选型**: 27.0 适合实拍内容（电影/电视剧），动漫可调到 30+（M4 提供风格预设可选切换）
- **最小镜头时长**: 0.8s（design.md §16.3 算法约束的硬下限）
- **数据结构**: `Shot(idx, start_sec, end_sec)` + `to_dict()` + `duration_sec` 属性
- **fallback**: 整片无场景切换 → 回退为单镜头覆盖全片
- **独立模块**: 放在 `algo/` 而非 `pipeline/`，便于 M2a / M2b 直接调用做单元测试

**涉及文件**:
- Create: `src/autoclip/algo/{__init__,shot_detector}.py`
- Create: `tests/unit/test_shot_detector.py`

**测试策略**:
- 单元: Shot dataclass duration / to_dict 验证
- 集成（依赖 fixture）: 5s 短片至少返回 1 个 shot；shots 时间严格升序

**验收标准**:
- [ ] dataclass 单元测试通过
- [ ] 集成测试: 90min 电影切分 < 60s 且 shot 数量合理（电影通常 800-1500 个）

**关联 KPI**: K8
**依赖**: M1.1 → **阻塞**: M1.8（Index stage 集成）
**预估工时**: 0.5d

---

### M1.8 — Index Stage：ASR 调度 + 注册到 Runner

**目标**: 把 M1.5（LocalWhisperProvider）+ M1.7（shot detector）组合为完整的 Index stage handler，并注册到 PipelineRunner。

**关键设计决策**:
- **handler 流程**:
  1. 加载 normalized.mp4 + audio.wav
  2. 镜头切分（CPU bound，~30s/90min）→ 写 `shots.json`
  3. ASR 调用（IO bound，~5min/90min）→ 写 `asr.json`
  4. **零知识架构**: 删除 audio.wav（直接关联 K9）
  5. mark Stage.INDEX DONE
- **进度节奏**: 0.0 → 0.3（shots done）→ 0.95（ASR done）→ 1.0
- **Cancel 检查点**: shot 切分后、ASR 调用前
- **注册**: `register_stage_handler(Stage.INDEX, run_index)`

**涉及文件**:
- Create: `src/autoclip/pipeline/index.py`
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import index`）
- Create: `tests/integration/test_index.py`（需 fixtures；本地 ASR 无凭证依赖，但需预下载 whisper 权重）

**测试策略**:
- 集成（端到端，需 keys）: 模拟 Ingest 已 DONE，注入 fixture normalized.mp4 + audio.wav，run_index 后验证 shots.json + asr.json 结构正确，audio.wav 已被删除

**验收标准**:
- [ ] 集成测试通过
- [ ] **Milestone 端到端验收**: `curl -X POST /api/jobs ...` 上传 5min 短片，2 分钟内 ingest+index 全部 DONE，产出 shots.json + asr.json
- [ ] audio.wav 在 Index 完成后不存在

**关联 KPI**: K7 / K9 / K6
**依赖**: M1.5 + M1.6 + M1.7 → **阻塞**: M2a 全部
**预估工时**: 1d

---

## M1 总工时估算
| 任务 | 工时 |
|---|---|
| M1.1 脚手架 | 0.5d |
| M1.2 ORM | 1.0d |
| M1.3 状态机 | 0.5d |
| M1.4 Runner + API | 1.5d |
| M1.5 ASR Provider（v0.4 本地化后） | **0.5d**（原 1.0d） |
| M1.6 Ingest（v0.5 双轨 normalize 后） | **1.3d**（原 1.0d） |
| M1.7 Shot detector | 0.5d |
| M1.8 Index 集成 | 1.0d |
| **总计** | **6.8d**（v0.4 -0.5d + v0.5 +0.3d，仍控制在 W1 内）|

## M1 完成时的 git 行为
按 250.md 规范，每个 task 至少 1 次 commit。Milestone 整体可考虑一次 squash merge 到 main 时使用如下 PR 描述模板：

```
✨feat: M1 - Infrastructure + Ingest + Index pipeline
    - T1.1 Poetry bootstrap + Settings
    - T1.2 ORM models + DB init (incl. TimelineSegment unified model)
    - T1.3 File state machine (atomic write + cancel + resume)
    - T1.4 PipelineRunner (multiprocessing spawn) + jobs API
    - T1.5 ASRProvider abstraction + LocalWhisper (faster-whisper + large-v3) impl
    - T1.6 Ingest stage (FFmpeg normalize + audio extract)
    - T1.7 Shot detector (PySceneDetect ContentDetector)
    - T1.8 Index stage (shots + ASR + audio cleanup)
```


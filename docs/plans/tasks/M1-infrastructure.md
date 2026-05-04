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
- **必备依赖**: fastapi / uvicorn / sqlalchemy 2.0 / pydantic 2.x / dashscope / alibabacloud-nls SDK / scenedetect / ffmpeg-python / pyjianyingdraft / loguru / tenacity / pytest 8.x
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

### M1.5 — ASRProvider 抽象 + AliyunASRProvider 实现

**目标**: 定义 ASR 接口契约，实现阿里云智能语音转写 Provider（design.md §16.1 ADR-004 再修订）。

**关键设计决策**:
- **ASRProvider abstract base**: 单方法 `transcribe(audio_path: Path, language: str) -> ASRResult`
- **数据结构**:
  - `ASRSentence(idx, start_sec, end_sec, text, speaker?)`
  - `ASRResult(sentences: list, language, provider)` + `to_dict()`
- **AliyunASRProvider 链路**:
  1. 上传音频到 OSS 临时 bucket（`autoclip-asr-tmp`）
  2. 调用 alibabacloud_nls SDK `SubmitTask` → 拿 task_id
  3. 轮询 `GetTaskResult`（10s 间隔，超时 600s）→ 拿 raw JSON
  4. 解析 raw → 组装 ASRResult
  5. **零知识架构**: finally 块强制删除 OSS object（K9 直接关联）
- **重试**: tenacity 装饰器，3 次指数退避（min=2, max=30）
- **额外依赖**: `oss2`, `alibabacloud-nls20180628`

**涉及文件**:
- Create: `src/autoclip/providers/__init__.py`
- Create: `src/autoclip/providers/asr/{__init__,base,aliyun}.py`
- Create: `tests/unit/test_asr_base.py`
- Create: `tests/integration/test_aliyun_asr.py`（默认 skip，需 `RUN_INTEGRATION=1`）

**测试策略**:
- 单元: dataclass 字段 / duration_sec 计算 / mock provider 实现接口
- 集成（手动）: 真实 5s 中文样本音频，验证返回 sentences 非空

**验收标准**:
- [ ] 接口设计通过 mock provider 验证可继承
- [ ] 集成测试在本地一次手跑通过（开发者私下验证）
- [ ] OSS object 在 transcribe 返回后已不存在

**关联 KPI**: K9（OSS 临时文件清理）
**依赖**: M1.1 → **阻塞**: M1.8
**预估工时**: 1d

---

### M1.6 — Ingest Stage（FFmpeg 视频归一化 + 音频抽离）

**目标**: 实现第一个具体 stage handler — 把上传的原片归一化为 H.264 720p 25fps + 抽离 16kHz mono WAV。

**关键设计决策**:
- **ffmpeg 命令封装**（utils 层，可独立测试）:
  - `probe_video(path)` → ffprobe JSON
  - `build_normalize_cmd(src, dst, fps=25, height=720)` → libx264 + crf=23 + faststart
  - `build_extract_audio_cmd(src, dst)` → -vn -ac 1 -ar 16000 -c:a pcm_s16le
- **进度上报**: 0.1（probe done）→ 0.6（normalize done）→ 0.95（audio done）→ 1.0（DONE）
- **Cancel 自检**: 在 normalize / audio 之间检查 `is_cancelled()`
- **失败兜底**: 任何异常都 mark FAILED 并抛出（让父进程感知 exitcode）
- **handler 签名**: `run_ingest(job_dir: Path, stage_name: str)` → 通过 `register_stage_handler(Stage.INGEST, run_ingest)` 注册

**涉及文件**:
- Create: `src/autoclip/utils/{__init__,ffmpeg}.py`
- Create: `src/autoclip/pipeline/ingest.py`
- Create: `tests/unit/test_ffmpeg_utils.py`
- Create: `tests/integration/test_ingest.py`（需 ffmpeg + sample.mp4 fixture）
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import ingest`）

**测试策略**:
- 单元: 测试 build_normalize_cmd / build_extract_audio_cmd 命令片段正确（不真跑 ffmpeg）
- 集成: 真跑 5s 短片 fixture，验证 normalized.mp4 + audio.wav 生成 + state DONE

**验收标准**:
- [ ] ffmpeg 命令构造测试通过
- [ ] 集成测试（手跑）：5s 短片 ingest 完成 < 30s
- [ ] state.json 进度字段正确递增

**关联 KPI**: K6（端到端耗时基线）
**依赖**: M1.4 + 系统已装 ffmpeg → **阻塞**: M1.7（需要 normalized.mp4） / M1.8（需要 audio.wav）
**预估工时**: 1d

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

**目标**: 把 M1.5（AliyunASR）+ M1.7（shot detector）组合为完整的 Index stage handler，并注册到 PipelineRunner。

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
- Create: `tests/integration/test_index.py`（需 fixtures + Aliyun keys）

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
| M1.5 ASR Provider | 1.0d |
| M1.6 Ingest | 1.0d |
| M1.7 Shot detector | 0.5d |
| M1.8 Index 集成 | 1.0d |
| **总计** | **7.0d**（5 工作日 + 2d buffer，控制在 W1 内）|

## M1 完成时的 git 行为
按 250.md 规范，每个 task 至少 1 次 commit。Milestone 整体可考虑一次 squash merge 到 main 时使用如下 PR 描述模板：

```
✨feat: M1 - Infrastructure + Ingest + Index pipeline
    - T1.1 Poetry bootstrap + Settings
    - T1.2 ORM models + DB init (incl. TimelineSegment unified model)
    - T1.3 File state machine (atomic write + cancel + resume)
    - T1.4 PipelineRunner (multiprocessing spawn) + jobs API
    - T1.5 ASRProvider abstraction + Aliyun ISR impl
    - T1.6 Ingest stage (FFmpeg normalize + audio extract)
    - T1.7 Shot detector (PySceneDetect ContentDetector)
    - T1.8 Index stage (shots + ASR + audio cleanup)
```


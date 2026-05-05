# AutoClip 技术设计文档

> **版本**：v0.1（MVP 设计稿）
> **日期**：2026-05-04
> **作者**：六饼 × 技术方案生成器
> **状态**：Proposed（待用户 review）
> **范围**：MVP 阶段（S1 — Demo 级技术闭环）

---

## 1. 项目概述

### 1.1 一句话定义

**AutoClip** 是一个面向**影视/电视剧/动漫二创创作者**的 **AI 解说视频创作助手**，将一部完整作品（单视频输入）转化为带 AI 解说稿、TTS 配音、智能拼接画面、智能混音的**短视频草稿**，由用户在编辑器中二次加工后发布。

### 1.2 用户与价值

| 维度 | 描述 |
|---|---|
| **目标用户** | B 站 / 抖音 / YouTube 上的影视/动漫解说类 UP 主 |
| **现状痛点** | 一部 90 分钟电影做一支 5 分钟解说，平均耗时 8-15 小时（看片+提炼+写稿+剪辑+配音+混音） |
| **核心价值** | 把 8-15 小时的工作量压缩到 **30-60 分钟人工调整**（系统跑 10-30 分钟出草稿，用户改稿+换镜头+发布） |
| **产品定位** | 创作助手（不是一键发布工具），版权和发布责任归用户 |

### 1.3 MVP 范围（S1 验收）

**做什么**：能用一部 90 分钟电影/一集动漫，**端到端跑通**：
上传 → 索引 → AI 文稿 → TTS → 拼接 → 带音轨预览（mp4 输出）。

**不做什么**：
- ❌ 多用户、登录、付费、并发任务队列
- ❌ Web UI（可以是命令行 + 简易预览页）
- ❌ M3-a（AI 自动推荐"原音保留段"）— 推到 v1.1
- ❌ 角色识别、说话人分离、情感标签
- ❌ 多视频合并、跨集叙事

---

## 2. 核心决策矩阵（Brainstorming 收敛）

| # | 决策维度 | 选择 | 关键理由 |
|---|---|---|---|
| 1 | 应用场景 | A1 — 影视/电视剧/动漫二创 | 用户明确需求，市场最大 |
| 2 | 产品定位 | B — 创作助手 | 版权风险可控，商业模式健康 |
| 3 | 输入形态 | 单视频输入 | 索引结构最简，核心闭环最短 |
| 4 | 索引模态 | a 镜头切分 + b ASR + d VLM按需 | 兼顾对白片和动漫（大量画面叙事） |
| 5 | 剪辑哲学 | Z 混合策略 | 默认时间线跟随，保留语义检索升级路径 |
| 6 | 文稿粒度 | P3 双层结构（段落+句子） | MVP 跑句子层，schema 一次到位免迁移 |
| 7 | 解说音轨 | V1 纯 TTS | 自动化优先，预览闭环完整 |
| 8 | 混音策略 | M3-c 终态 → MVP 实做 M2+M3-b | 用户手动标记原音，AI 推荐留 v1.1 |
| 9 | 时长档位 | T1 优先（3-5 min） → T2（10-15 min） | 市场认知最强，技术栈不变 |
| 10 | 验收级别 | S1 — Demo 级技术闭环 | 2-4 周跑通，先验证可行性 |

> ⚠️ **范围权衡说明**：第 8 项 M3-c 是终态目标，但 S1 阶段实际只交付 M2（智能让位）+ M3-b（手动标记）。M3-a（AI 推荐）作为 v1.1 追加模块，**不阻塞 S1 出片**。

---

## 3. 系统架构（C4 Level 1 - 系统上下文）

```
                ┌──────────────────────────────────────────┐
                │            Creator User                   │
                │   (个人 UP 主 / 解说类创作者)              │
                └────────┬─────────────────────────▲────────┘
                         │ 上传单视频 + 时长档位     │ 下载草稿 mp4
                         │ + 解说风格选项           │ + JSON 时间线
                         ▼                          │
        ┌────────────────────────────────────────────────────┐
        │                    AutoClip                         │
        │   单机服务（MVP）— FastAPI + Python Worker          │
        │                                                     │
        │  Ingest → Index → Scripting → Assembly → Render     │
        └──┬───────────┬──────────┬──────────┬─────────┬─────┘
           │           │          │          │         │
           ▼           ▼          ▼          ▼         ▼
        ┌──────┐  ┌────────┐  ┌──────┐  ┌──────┐  ┌──────┐
        │FFmpeg│  │ Whisper│  │ LLM  │  │ TTS  │  │FFmpeg│
        │      │  │ (ASR)  │  │ API  │  │ API  │  │      │
        │      │  │PySceneD│  │(GPT/ │  │(豆包/│  │      │
        │      │  │ etect  │  │Claude│  │Mini- │  │      │
        │      │  │ Qwen-VL│  │Qwen) │  │max)  │  │      │
        │      │  │(按需)  │  │      │  │      │  │      │
        └──────┘  └────────┘  └──────┘  └──────┘  └──────┘

        本地存储：data/{video_id}/{原视频, 镜头切分, ASR, VLM, 文稿, TTS, 输出}
```

---

## 4. 系统架构（C4 Level 2 - 容器视图）

```
┌─────────────────────────────────────────────────────────────────┐
│                       AutoClip MVP（单机部署）                    │
│                                                                   │
│  ┌────────────┐         ┌──────────────────────────────────┐    │
│  │ Web/CLI    │  HTTP   │   API Layer (FastAPI)            │    │
│  │ Frontend   ├────────▶│   - POST /videos        (上传)   │    │
│  │ (极简 UI   │         │   - POST /jobs          (启动)   │    │
│  │  Next.js   │         │   - GET  /jobs/{id}     (轮询)   │    │
│  │  或 CLI)   │         │   - GET  /timeline/{id} (取JSON) │    │
│  └────────────┘         │   - PATCH /timeline/{id}(改稿)   │    │
│                         │   - POST /render/{id}   (出片)   │    │
│                         └──────────┬───────────────────────┘    │
│                                    │ 入队                        │
│                                    ▼                             │
│                         ┌──────────────────────┐                │
│                         │  Job Queue           │                │
│                         │  (MVP: SQLite +      │                │
│                         │   in-process worker) │                │
│                         └──────┬───────────────┘                │
│                                │ 执行                            │
│                                ▼                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Worker Pipeline（5 个阶段）                   │  │
│  │                                                            │  │
│  │  ① Ingest    → 视频归一化、抽轨、抽帧                      │  │
│  │       ↓                                                    │  │
│  │  ② Index     → 镜头切分(Shot) + ASR(Sentence) +           │  │
│  │                VLM 按需(KeyFrameDescription)               │  │
│  │       ↓                                                    │  │
│  │  ③ Scripting → LLM 生成解说稿 + 句子↔镜头绑定（核心算法） │  │
│  │       ↓                                                    │  │
│  │  ④ Assembly  → 时间线装配（句子拼接镜头 + 时长适配）       │  │
│  │       ↓                                                    │  │
│  │  ⑤ Render    → TTS 合成 + FFmpeg 拼接 + 智能混音 → MP4    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         Storage Layer                                      │   │
│  │  - SQLite (元数据、任务状态、时间线 JSON)                  │   │
│  │  - 本地文件系统 data/{video_id}/                          │   │
│  │      ├─ raw/             原视频                            │   │
│  │      ├─ audio.wav        分离出的音轨                      │   │
│  │      ├─ keyframes/       关键帧 jpg                        │   │
│  │      ├─ shots.json       镜头切分结果                      │   │
│  │      ├─ asr.json         ASR 结果                          │   │
│  │      ├─ vlm/             按需 VLM 描述                     │   │
│  │      ├─ script.json      文稿 + 时间线                     │   │
│  │      ├─ tts/             TTS 音频片段                      │   │
│  │      └─ output.mp4       最终成片                          │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

外部依赖：
- LLM API：通义千问 / DeepSeek / Claude / GPT（任选其一）
- TTS API：火山豆包语音 / Minimax speech-02 / CosyVoice2 (本地)
- VLM API：Qwen2.5-VL（按需触发）
```

---

## 5. 后续章节占位（待第 2-4 次扩写）

- ⏳ **第 6 节**：核心数据模型（Video / Shot / Sentence / Paragraph / Timeline / Job）
- ⏳ **第 7 节**：核心数据流（一次端到端调用的完整字段流转）
- ⏳ **第 8 节**：5 个核心模块详细设计
  - 8.1 Ingest（视频归一化）
  - 8.2 Index（三模态索引：镜头/ASR/VLM）
  - 8.3 Scripting（LLM 解说稿生成 — 核心算法）
  - 8.4 Assembly（时间线装配 — 时长适配算法）
  - 8.5 Render（TTS + FFmpeg 拼接 + 智能混音）
- ⏳ **第 9 节**：技术选型 ADR
  - ADR-001 LLM 选型（通义千问 vs DeepSeek vs Claude）
  - ADR-002 TTS 选型（API vs 本地 CosyVoice2）
  - ADR-003 镜头切分（PySceneDetect vs TransNetV2）
  - ADR-004 ASR 选型（Whisper vs FunASR/Paraformer）
  - ADR-005 存储选型（SQLite vs Postgres）
  - ADR-006 任务队列（in-process vs Celery vs RQ）
- ⏳ **第 10 节**：风险评估 + 缓解策略
- ⏳ **第 11 节**：S1 演进路线图 + 里程碑


---

## 6. 核心数据模型

### 6.1 ER 关系图（逻辑）

```
Job (1) ──── (1) Video
              │
              ├── (1..N) Shot              ← 视觉索引（PySceneDetect）
              ├── (1..N) ASRSentence       ← 音频索引（Whisper/FunASR）
              └── (0..N) KeyFrameDesc      ← 视觉描述（VLM 按需）
                              ▲
                              │ 通过 shot_id 关联
                              │
Timeline (1) ── (1) Video
    │
    ├── (1..N) Paragraph (P3 双层 - 段落层，MVP 预留)
    │              │
    │              └── (1..N) NarrationSentence  ← 解说句（核心实体）
    │                            │
    │                            ├── (1..N) ClipBinding  ← 句子↔镜头绑定
    │                            ├── (1)    TTSAudio
    │                            └── (0..1) AudioOverride ← M3-b 原音保留标记
```

### 6.2 核心实体定义（Python dataclass / Pydantic 形式）

```python
# ============ 输入侧（Index 阶段产物） ============

class Video:
    id: str                  # uuid
    file_path: str           # 原视频本地路径（M3.8 cleanup 后置 None）
    duration_sec: float      # 总时长
    fps: float
    resolution: tuple[int, int]
    # ↓ v0.5 ADR-010 双轨 normalize 产物
    normalized_low_path: str  # 720p 25fps，给 PySceneDetect / KeyFrameDesc
    normalized_hd_path: str   # 1080p 原帧率，给 Render 出片（M3.4/M3.5）
    audio_path: str          # 16kHz mono pcm_s16le，给 LocalWhisperProvider
    metadata: dict           # codec / bitrate 等

class Shot:                  # 镜头分段（视觉原子单位）
    id: str
    video_id: str
    index: int               # 镜头序号
    start_sec: float
    end_sec: float
    keyframe_path: str       # 该镜头的代表关键帧
    confidence: float        # 切分置信度

class ASRSentence:           # ASR 转写句（对白原子单位）
    id: str
    video_id: str
    index: int
    start_sec: float
    end_sec: float
    text: str
    confidence: float
    speaker_id: str | None   # MVP 不用，预留

class KeyFrameDesc:          # VLM 画面描述（按需触发）
    id: str
    shot_id: str             # 1:1 关联到 Shot
    description: str         # 自然语言描述
    tags: list[str]          # ["夜景","打斗","近景"...]
    embedding: list[float] | None  # 语义检索用，MVP 可缺省

# ============ 输出侧（Scripting + Assembly 产物） ============

class Timeline:              # 完整成片时间线
    id: str
    video_id: str
    job_id: str
    target_duration_sec: float       # 目标成片时长（如 240s）
    actual_duration_sec: float       # 实际拼装出的时长
    paragraphs: list[Paragraph]      # P3 双层 - 段落层
    created_at: datetime
    version: int                     # 用户每改一次 +1

class Paragraph:             # 解说段落（P3 上层，MVP 预留）
    id: str
    timeline_id: str
    index: int
    theme: str               # 该段主题，如 "主角的成长"
    sentences: list[NarrationSentence]

class NarrationSentence:     # ★ 核心实体：一句解说
    id: str
    paragraph_id: str
    index: int
    text: str                # 解说文本
    target_duration_sec: float       # 期望时长（由 TTS 决定）
    actual_duration_sec: float       # TTS 实际产出时长
    start_sec_in_timeline: float     # 在最终成片中的起始时间
    clip_bindings: list[ClipBinding] # 关联的视频片段（1:N）
    tts_audio: TTSAudio
    audio_override: AudioOverride | None  # M3-b 原音保留

class ClipBinding:           # 解说句 ↔ 视频镜头 的绑定
    id: str
    sentence_id: str
    shot_id: str             # 关联的 Shot
    order: int               # 一句话内可以有多个镜头，按 order 拼
    use_start_sec: float     # 取该 Shot 的子段起点（允许裁剪）
    use_end_sec: float       # 取该 Shot 的子段终点
    rationale: str | None    # AI 给出的"为什么选这个镜头"理由（可选）

class TTSAudio:
    id: str
    sentence_id: str
    file_path: str           # tts/{sentence_id}.wav
    voice_id: str            # 音色标识
    duration_sec: float
    
class AudioOverride:         # M3-b 原音保留标记
    id: str
    sentence_id: str         # 哪句解说被"让位"
    mode: Literal["keep_original", "mix"]  # MVP 只用 keep_original
    original_volume: float = 1.0           # 原音音量（0-1）
    narration_volume: float = 0.0          # 让位时解说静音

# ============ 任务管理 ============

class Job:
    id: str
    video_id: str
    status: Literal["pending","ingesting","indexing","scripting",
                    "assembling","rendering","done","failed"]
    progress: float          # 0-1
    target_duration_sec: float       # 用户指定目标时长（T1: 180-300s）
    style_preset: str        # "幽默吐槽"/"严肃影评"/"剧情速览" 等
    error_msg: str | None
    timeline_id: str | None
    output_path: str | None
    created_at: datetime
    updated_at: datetime
```

### 6.3 持久化（MVP）

| 数据 | 存储 | 说明 |
|---|---|---|
| Job / Video / Timeline 元数据 | SQLite | 单表结构，方便查询 |
| Paragraph / Sentence / ClipBinding | SQLite (JSON 字段) | MVP 直接整段 JSON 存，简化模型 |
| Shot / ASRSentence / KeyFrameDesc | 本地 JSON 文件 | `data/{video_id}/index/*.json` |
| 关键帧 / TTS 音频 / 输出 mp4 | 本地文件系统 | `data/{video_id}/` 下分目录 |
| Embedding（v1.1+ 才用） | 本地文件 / Chroma | MVP 不必引入向量数据库 |

> **Schema 一次到位原则**：即使 MVP 不用 `Paragraph`、`speaker_id`、`embedding`、`audio_override.mode=mix`，字段也先在数据结构里留好 ——避免 v2 做数据迁移。

---

## 7. 核心数据流（端到端时序）

### 7.1 一次完整调用的字段流转

```
[T0] User 上传 movie.mp4 (90 min)
       │
       ▼  POST /videos
[T1] Ingest 阶段（耗时 1-2 min）
       ├─ FFmpeg 抽离音轨        → audio.wav
       ├─ FFmpeg 归一化 fps/分辨率
       └─ 生成 Video 记录          → SQLite

       │
       ▼  POST /jobs { target_duration: 240, style: "剧情速览" }
[T2] Index 阶段（耗时 5-10 min，可并行）
       ├─ ① 镜头切分 PySceneDetect → shots.json (~800 shots)
       │      并对每个 shot 抽取 1 张关键帧 → keyframes/*.jpg
       ├─ ② ASR Whisper           → asr.json (~600 sentences)
       └─ ③ VLM 按需               → MVP 跳过（剪辑哲学=Z 默认）

       │
       ▼
[T3] Scripting 阶段（核心算法，耗时 30-60s）
       │
       ├─ Step 3.1: 剧情主线提取
       │     输入：asr.json 全文 + 视频元数据
       │     LLM Prompt：「以下是一部电影的完整对白，请提炼 8-12 个剧情节点」
       │     输出：plot_outline.json（剧情骨架）
       │
       ├─ Step 3.2: 解说稿生成
       │     输入：plot_outline + target_duration(240s) + style_preset
       │     LLM Prompt：「写一段 240 秒、风格=剧情速览 的二创解说稿，
       │                    分为 N 段，每段 M 句」
       │     输出：[Paragraph[Sentence[]]] (粗稿，无时间戳)
       │
       └─ Step 3.3: ★句子↔镜头绑定（最核心算法）
             对每个 Sentence:
             ├─ 默认策略（剪辑哲学 Z 默认）：
             │     时间线跟随 — 通过该句对应的 plot_outline 节点
             │     映射回原片时间区间，从该区间内的 Shots 里挑选
             │     拼接出"刚好覆盖 sentence.target_duration"的镜头序列
             │
             └─ 输出：ClipBinding[] for each sentence

       → 完成后落库：Timeline + Paragraph + Sentence + ClipBinding
       → API 返回 timeline_id 给用户

       │
       ▼  GET /timeline/{id}    （用户查看 + 可选编辑）
[T4] User 在编辑器里：
       ├─ 改解说文本（PATCH sentence.text）
       ├─ 替换某句的镜头（PATCH sentence.clip_bindings）
       └─ 标记某段原音保留（PATCH sentence.audio_override）— M3-b

       │
       ▼  POST /render/{id}
[T5] Render 阶段（耗时 1-3 min）
       ├─ Step 5.1: TTS 批量合成
       │     for sentence in timeline:
       │         tts_api(sentence.text, voice_id) → tts/{sid}.wav
       │
       ├─ Step 5.2: 时长再适配
       │     for sentence:
       │         如果 tts.duration ≠ sentence.target_duration:
       │             重新调整 clip_bindings 的 use_start/use_end
       │             （拉长：补镜头；缩短：裁画面）
       │
       ├─ Step 5.3: FFmpeg 视频拼接（filter_complex）
       │     按 sentence 顺序拼接所有 ClipBinding 对应的视频片段
       │     → video_track.mp4 (无音轨)
       │
       ├─ Step 5.4: 音轨混音
       │     - 解说轨：concat 所有 tts/*.wav，按 sentence 时间戳对齐
       │     - 原视频轨：截取拼接镜头对应的原音
       │     - M2 智能让位：解说有声时原音 → 0.15，解说间隙 → 0.7
       │     - M3-b 处理：标记了 keep_original 的 sentence 段，
       │                   原音 → 1.0，解说 → 0
       │     → mixed_audio.wav
       │
       └─ Step 5.5: 视频 + 音轨合成 → output.mp4

       → 任务完成，返回 output_path
```

### 7.2 关键时长约束（MVP 性能预算）

| 阶段 | 90 min 输入电影 → 4 min 输出 | 目标耗时 | 备注 |
|---|---|---|---|
| Ingest | 视频归一化 | < 2 min | 取决于源文件 codec |
| Index | 镜头切分 + ASR | < 10 min | ASR 是瓶颈，可走 GPU |
| Scripting | LLM 生成稿 + 绑定 | < 1 min | 主要是 API 网络耗时 |
| Render | TTS + 拼接 + 混音 | < 3 min | TTS 串行，FFmpeg 一次完成 |
| **总计** | **端到端** | **< 16 min** | S1 验收点 |


---

## 8. 核心模块详细设计

### 8.1 Ingest 模块（视频归一化）

**职责**：把任意格式的用户上传视频，归一化为后续模块可稳定处理的标准形态。

**输入**：用户上传的原始视频文件（mp4/mkv/mov/avi/webm…）
**输出**：
- `data/{video_id}/raw/source.mp4`（原视频，仅作备份引用）
- `data/{video_id}/audio.wav`（16kHz 单声道，给 ASR 用）
- `data/{video_id}/normalized.mp4`（统一 codec/fps/分辨率，给 Index 和 Render 用）
- `Video` 元数据记录入库

**关键处理**：

| 步骤 | 命令/工具 | 说明 |
|---|---|---|
| 1. 探针 | `ffprobe -v quiet -print_format json -show_streams` | 拿到 codec、duration、fps、resolution |
| 2. 归一化 | `ffmpeg -i src -c:v libx264 -preset fast -crf 23 -r 25 -vf scale=-2:720` | 统一为 720p / 25fps / H.264，便于后续 filter 操作稳定 |
| 3. 音轨抽离 | `ffmpeg -i src -ac 1 -ar 16000 -vn audio.wav` | ASR 模型期望 16kHz mono |
| 4. 校验 | 检查 duration 是否 ≥ 10min（MVP 限制：避免上传短视频跑全流程没意义） | 不满足直接 return error |

**失败模式**：
- 文件损坏 → ffprobe 失败 → Job 状态置 `failed`，error_msg 记录
- 文件过大（>5GB）→ MVP 直接拒绝（避免磁盘爆炸）
- 无音轨 → 仍可继续（ASR 阶段会跳过，但 Scripting 质量会很差，给 warning）

---

### 8.2 Index 模块（三模态索引）

**职责**：建立"视频 → 镜头 + 对白 + (按需)画面描述"的可检索索引。

**子模块 8.2.1：镜头切分（Shot Detector）**

```python
# 伪代码
from scenedetect import detect, ContentDetector

def detect_shots(video_path, threshold=27.0):
    scenes = detect(video_path, ContentDetector(threshold=threshold))
    shots = []
    for i, (start, end) in enumerate(scenes):
        shot = Shot(
            id=uuid4(),
            index=i,
            start_sec=start.get_seconds(),
            end_sec=end.get_seconds(),
            keyframe_path=extract_keyframe(video_path, midpoint(start, end)),
            confidence=...,
        )
        shots.append(shot)
    return shots
```

- **算法**：PySceneDetect ContentDetector（对色彩/亮度变化敏感，对动漫友好）
- **关键帧抽取**：每个 Shot 中点抽 1 帧 jpg，分辨率 480x270，作为 VLM/预览用
- **MVP 阈值**：threshold=27（默认值，对大多数影片合适）；动漫可能需要降到 20（变化更激烈）→ v1.1 做品类自适应

**子模块 8.2.2：ASR 转写**

```python
# 伪代码（Whisper 路线）
import whisper

def transcribe(audio_path, lang="zh"):
    model = whisper.load_model("medium")  # 或 large-v3
    result = model.transcribe(audio_path, language=lang, word_timestamps=False)
    sentences = []
    for i, seg in enumerate(result["segments"]):
        sentences.append(ASRSentence(
            id=uuid4(), index=i,
            start_sec=seg["start"], end_sec=seg["end"],
            text=seg["text"].strip(), confidence=seg.get("avg_logprob", 0.0),
        ))
    return sentences
```

- **MVP 默认**：Whisper-medium（GPU 推理快，质量足够）；中文可备选 FunASR/Paraformer-large
- **后处理**：合并过短片段（<1s）、去除纯噪音段（confidence < -1.0）
- **失败兜底**：ASR 完全无输出（纯无对白电影）→ 仅依赖 Shot + 用户提示"该片素材为无对白片，建议改用 v1.1 强 VLM 模式"

**子模块 8.2.3：VLM 画面描述（按需触发）**

- **MVP 默认**：**不主动跑全量 VLM**（剪辑哲学 Z 默认为时间线跟随）
- **触发条件**：
  1. 用户在编辑器里某句解说点击"找更贴的画面"按钮 → 对相关时间段镜头跑 VLM
  2. ASR 输出过于稀疏（10 分钟原片 ASR 句子 < 30 句）→ 自动 fallback 跑 VLM 补全
- **实现**：调用 Qwen2.5-VL-7B API，prompt: `"用一句中文描述这张电影截图的内容（画面元素、人物动作、氛围）"`
- **存储**：写入 `KeyFrameDesc`，可选生成 embedding（MVP 不做）

---

### 8.3 Scripting 模块 ★（核心算法）

**职责**：把"剧情骨架"转化为"带镜头绑定的解说稿时间线"。

**这是整个项目最难、最值得投入的模块。** 拆为 3 个 Step：

**Step 8.3.1：剧情主线提取（Plot Outline）**

```text
[LLM Prompt 模板 v1]
你是一位资深影视解说稿编剧。

下面是一部影片的完整对白时间轴（来自 ASR）：
{asr_transcript_with_timestamps}

请提炼出这部影片的剧情主线，输出 8-15 个关键剧情节点，
每个节点包含：
- index: 序号
- title: 节点小标题（≤10 字）
- description: 一句话描述发生了什么（≤40 字）
- start_sec / end_sec: 该节点对应的原片时间区间
- importance: 1-5（5 最重要，对应高潮 / 反转 / 名场面）

返回 JSON 数组。
```

**Step 8.3.2：解说稿生成**

```text
[LLM Prompt 模板 v1]
你是一位 B 站头部影视解说 UP 主，擅长「{style_preset}」风格。

下面是一部影片的剧情骨架（共 {N} 个节点）：
{plot_outline_json}

请写一段总时长 {target_duration_sec} 秒的二创解说稿，要求：
1. 中文按 4.5 字/秒 估算字数 → 目标字数 ≈ {target_duration_sec * 4.5}
2. 分为 3-5 个段落（Paragraph），每段对应 1-3 个剧情节点
3. 每个段落由 4-8 句话（Sentence）组成，每句独立成一个完整意群
4. 句子长度 12-30 字，避免过长（TTS 会分段不自然）
5. 风格要求：{style_preset_detail}
6. 严禁逐字复述对白；要有"二创视角"——总结、点评、悬念铺设

返回 JSON：
{
  "paragraphs": [
    {
      "index": 0,
      "theme": "...",
      "linked_plot_nodes": [0, 1],   // 对应剧情节点 index
      "sentences": [
        { "index": 0, "text": "..." },
        ...
      ]
    },
    ...
  ]
}
```

**Step 8.3.3 ★：句子↔镜头绑定算法**（MVP 核心创新点）

**输入**：`paragraphs[].sentences[]` + 该段落 `linked_plot_nodes` + `Shot[]` + `ASRSentence[]`
**输出**：`sentence.clip_bindings[]`

**算法（默认时间线跟随策略 Z）**：

```python
def bind_sentences_to_clips(paragraph, shots, asr_sentences):
    # 1. 该段落对应的原片时间区间（基于 plot nodes 的并集）
    plot_start = min(node.start_sec for node in paragraph.linked_plot_nodes)
    plot_end   = max(node.end_sec   for node in paragraph.linked_plot_nodes)
    
    # 2. 截取该区间内所有可用镜头（按时间序）
    candidate_shots = [s for s in shots 
                       if s.start_sec >= plot_start and s.end_sec <= plot_end]
    
    # 3. 估算每句解说的目标时长（按 4.5 字/秒，TTS 阶段会再校准）
    for sentence in paragraph.sentences:
        sentence.target_duration_sec = len(sentence.text) / 4.5
    
    # 4. 按比例把镜头分配给句子（贪心算法）
    total_target_dur  = sum(s.target_duration_sec for s in paragraph.sentences)
    total_shots_dur   = sum(s.end_sec - s.start_sec for s in candidate_shots)
    speed_ratio       = total_shots_dur / total_target_dur  # 一般 > 1（原片更长）
    
    shot_idx = 0
    for sentence in paragraph.sentences:
        accumulated = 0.0
        bindings = []
        while accumulated < sentence.target_duration_sec and shot_idx < len(candidate_shots):
            shot = candidate_shots[shot_idx]
            need = sentence.target_duration_sec - accumulated
            shot_dur = shot.end_sec - shot.start_sec
            
            if shot_dur <= need * speed_ratio:
                # 整个 shot 用完
                bindings.append(ClipBinding(
                    shot_id=shot.id,
                    use_start_sec=shot.start_sec,
                    use_end_sec=shot.end_sec,
                ))
                accumulated += shot_dur / speed_ratio
                shot_idx += 1
            else:
                # 只用 shot 的前半段
                use_dur = need * speed_ratio
                bindings.append(ClipBinding(
                    shot_id=shot.id,
                    use_start_sec=shot.start_sec,
                    use_end_sec=shot.start_sec + use_dur,
                ))
                # 注意：实际工程中要避免单镜头被切碎——如果切剩余<1s就把整段给这句
                accumulated = sentence.target_duration_sec
                shot_idx += 1  # 该 shot 整个消耗
        sentence.clip_bindings = bindings
```

**算法约束（避免视觉跳跃）**：
- ❗ **最小镜头时长 0.8s**：如果 candidate_shot 切出来 < 0.8s，跳过或合并到上一段
- ❗ **单句最多 5 个镜头**：避免一句话内画面切换太快
- ❗ **跨段不复用**：上一段用过的镜头不再分给下一段

**降级策略**：如果 `candidate_shots` 总时长 < `total_target_dur`（原片该段时间不够覆盖解说时长），允许：
1. 复用本段的 importance ≥ 4 的高光镜头（慢动作或重复）
2. 从相邻 paragraph 借镜头（仅相邻 ±1 段）
3. 实在不行则压缩 sentence.target_duration（给 Render 阶段重做 TTS 时使用更快语速）

---

### 8.4 Assembly 模块（时间线装配）

**职责**：把 Scripting 输出的"逻辑时间线"转成"绝对时间戳的物理时间线"，并处理用户编辑后的时长再适配。

**输入**：`Timeline`（含所有 Sentence 和 ClipBinding）+ TTS 实际产出时长（来自 Render Step 5.1）
**输出**：可直接喂给 FFmpeg 的"片段裁剪指令清单"

**关键算法 — 时长再适配**（解决 TTS 实际时长 ≠ 估算时长的问题）：

```python
def reconcile_durations(sentence, tts_actual_dur):
    """
    TTS 跑完后，实际时长可能和估算的 4.5字/秒 偏差 ±20%。
    此时要重新调整 clip_bindings 的覆盖时长。
    """
    target = tts_actual_dur  # 真值
    current_clips_dur = sum(b.use_end_sec - b.use_start_sec for b in sentence.clip_bindings)
    
    if current_clips_dur >= target:
        # 镜头比解说长 → 等比裁剪每个镜头尾部
        ratio = target / current_clips_dur
        for b in sentence.clip_bindings:
            dur = b.use_end_sec - b.use_start_sec
            b.use_end_sec = b.use_start_sec + dur * ratio
    else:
        # 镜头比解说短 → 优先延长最后一个镜头（用同一 Shot 的剩余部分）
        deficit = target - current_clips_dur
        last = sentence.clip_bindings[-1]
        shot = get_shot(last.shot_id)
        room = shot.end_sec - last.use_end_sec
        if room >= deficit:
            last.use_end_sec += deficit
        else:
            last.use_end_sec = shot.end_sec  # 用尽该 shot
            # 还差就静帧或加慢动作（v1.1，MVP 接受少量黑场）
```

**M3-b 原音保留段处理**：

```python
def apply_audio_overrides(timeline):
    """
    遍历 sentences，对标记了 audio_override.mode=='keep_original' 的句子：
    - 该句的 TTS 不参与混音（narration_volume = 0）
    - 该句对应的镜头段，原音轨拉到 1.0
    - 该句的 clip 时长不再绑定 TTS 时长，直接用原片镜头的自然长度
    """
    for sent in timeline.all_sentences():
        if sent.audio_override and sent.audio_override.mode == "keep_original":
            sent.tts_audio.muted = True
            for b in sent.clip_bindings:
                b.use_original_audio_volume = 1.0
            # 时长重置为镜头段自然时长，不再做时长适配
            sent.actual_duration_sec = sum(b.use_end_sec - b.use_start_sec 
                                           for b in sent.clip_bindings)
```

**时间戳归一化**：装配完成后，遍历所有 sentence 累加 actual_duration_sec，写入 `start_sec_in_timeline`，得到一份"绝对时间戳的播放清单"。

---

### 8.5 Render 模块（TTS + 拼接 + 混音 → MP4）

**职责**：把时间线物理化为最终成片。

**Step 8.5.1 — TTS 批量合成**

```python
async def synthesize_all(timeline):
    tasks = []
    for sent in timeline.all_sentences():
        if sent.audio_override and sent.audio_override.mode == "keep_original":
            continue  # 该句不需要 TTS
        tasks.append(tts_api(
            text=sent.text,
            voice_id=timeline.voice_id,
            speed=1.0,
            output=f"data/{vid}/tts/{sent.id}.wav",
        ))
    results = await asyncio.gather(*tasks)
    for sent, audio in zip(needs_tts, results):
        sent.tts_audio.duration_sec = audio.duration
```

- **并发**：MVP 控制在 5 并发（避免 API 限速）
- **重试**：单句失败重试 2 次，仍失败则记 warning，最终用静音 wav 占位

**Step 8.5.2 — 视频拼接（FFmpeg filter_complex）**

```bash
# 概念命令（实际由 Python 生成）
ffmpeg -y \
  -i normalized.mp4 \
  -filter_complex "
    [0:v]trim=start=12.3:end=16.5,setpts=PTS-STARTPTS[v0];
    [0:v]trim=start=20.1:end=23.4,setpts=PTS-STARTPTS[v1];
    [0:v]trim=start=45.0:end=48.7,setpts=PTS-STARTPTS[v2];
    [v0][v1][v2]concat=n=3:v=1:a=0[outv]
  " \
  -map "[outv]" -c:v libx264 -preset fast video_track.mp4
```

- 一次 filter_complex 完成所有片段裁剪 + 拼接，避免多次落盘
- 镜头数过多（>200）时分批合并，避免 filter graph 超长

**Step 8.5.3 — 双音轨混音**

```bash
# 概念：解说轨 (concat 所有 TTS) + 原视频音轨 (与拼接镜头同步切片)
# M2 智能让位：用 sidechaincompress 实现 ducking
ffmpeg -y \
  -i video_track.mp4 \
  -i narration_track.wav \
  -filter_complex "
    [0:a]volume=1.0[orig];
    [orig][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[ducked];
    [ducked][1:a]amix=inputs=2:duration=longest[aout]
  " \
  -map 0:v -map "[aout]" -c:v copy -c:a aac output.mp4
```

- **M2 智能让位**：sidechain ducking — 解说有声时原音自动压低（ratio 8:1）
- **M3-b 原音保留段**：在装配阶段已把这些片段标记 `narration_volume=0`，TTS 轨在该段内是静音，于是 ducking 自然不触发，原音 100%
- **音量参数**（MVP 默认值）：
  - 解说 0 dB
  - 原音 base -12 dB（让位时）
  - 原音 base -3 dB（让位间隙）

**Step 8.5.4 — 输出**

最终 `output.mp4`：
- 720p / 25fps / H.264 / AAC / 双声道
- metadata 写入：`comment="Generated by AutoClip v0.1"` + `Job ID`


---

## 9. 技术选型 ADR（Architecture Decision Records）

### ADR-001：LLM 选型 — DeepSeek-V3 主 + 通义千问兜底（**v0.5 修订**）

**Status**: Accepted (MVP, **revised at 2026-05-05 by M2a brainstorming v0.5**)

**Context**：Scripting 模块需要一个能稳定输出长 JSON、理解中文影视语境、成本可控的 LLM。M2a kickoff brainstorming 时进一步引入了 4 个新约束：(1) 双引擎并存以防单一 provider 故障 (2) 通过统一抽象层避免代码绑死 provider (3) LLM 调用必须可观测可追溯 (4) >2h 长视频暂不支持但需要明确边界。

**Decision**（**v0.5 更新**）：
- **主 provider：DeepSeek-V3**（model `deepseek-chat`），通过 LangChain `langchain_openai.ChatOpenAI`（DeepSeek 官方支持 OpenAI 兼容协议）+ `base_url="https://api.deepseek.com/v1"` 接入
- **兜底 provider：通义千问 qwen-plus**，通过 LangChain `langchain_community.chat_models.ChatTongyi` 接入；当 DeepSeek 不可用或用户显式指定时启用
- **统一抽象层：LangChain `BaseChatModel`**，封装在 `src/autoclip/providers/llm/factory.py` 的 `get_llm(provider, json_mode, callbacks, **model_kwargs)` factory 内；切换 provider = 改一行 env var `AUTOCLIP_LLM_PROVIDER`
- **可观测性：LangChain `BaseCallbackHandler`** 实现 `LlmCallsRecorder`，每次 call 落盘到 `{job_dir}/llm_calls/{stage}_{seq:03d}.json`（含 messages / response / usage / cost）

**Consequences**：
- ✅ DeepSeek-V3 成本最低（$0.14/$0.28 per 1M token，输入/输出），128k context window 充裕
- ✅ JSON mode 通过 `model_kwargs={"response_format": {"type": "json_object"}}` 支持，与 OpenAI 协议一致
- ✅ 中文理解 + 影视语境处理与 qwen-plus 相当，代码生成 + reasoning 显著强于 qwen-plus
- ✅ LangChain 抽象层让"切 provider"成本降到 0；M2b 加 mock provider 直接用 `langchain.chat_models.fake.FakeListChatModel`
- ✅ Callback 落盘让 LLM 调用 100% 可追溯（debug + prompt 调优 + 成本审计）
- ❌ LangChain 0.x 大版本破坏性改动多，依赖紧锁 `langchain-core>=0.3,<0.4 + langchain-openai>=0.2,<0.3 + langchain-community>=0.3,<0.4`
- ❌ 长 JSON 输出偶尔截断（M2a.4 自写 JSON repair 兜底；**故意不用** LangChain `OutputFixingParser`，避免修复策略黑盒化）
- ❌ DeepSeek attention 在 >32k 输入后劣化，M2a 阶段限制单次 input ≤32k token，>2h 视频留给 M2b/M3

**Alternatives Considered**（**v0.5 重新评估**）：
- **qwen-plus 单一 provider（v0.4 旧方案）**：风险集中、无 fallback，dashscope 限速时整个 pipeline 阻塞 — 已被 v0.5 否决
- **自抽象 `LLMProvider` ABC（v0.4 旧方案）**：~150 行抽象层 + 每个 provider 重新实现 chat() / token 统计 / 错误处理 — 被 LangChain 替代，~30 行 factory 即可
- **LangChain `OutputFixingParser`**：把 JSON 修复策略交给框架黑盒（失败时再调 LLM 让它修自己输出），调试成本极高 — B1=A 决策保留 M2a.4 自写 repair（5 步确定性策略）
- **LangChain `ChatPromptTemplate` + `PydanticOutputParser`**：B1=A 决策不引入，prompt 仍用 f-string，输出仍走 M2a.4 自写解析；M2b 阶段如证明此处是瓶颈再升级
- **Claude 3.5 Sonnet**：质量最高但成本 5x、国内访问需代理 — v2 可作为高级用户可选 upgrade
- **GPT-4o**：综合能力强，国内接入麻烦，性价比一般
- **本地 Qwen2.5-72B / DeepSeek-V3 本地**：避免 API 成本但需要 80GB+ 显存，不在 MVP 范围

**Migration from v0.4**：v0.4 的 "qwen-plus 单一 + 自抽象" 方案在 M2a kickoff 时未实施任何代码（M2a.1 仍是 plan 状态），本次修订对实施零回滚成本；M2a.1 task 直接按 v0.5 方案落地。

---

### ADR-002：TTS 选型 — 火山豆包语音 / Minimax speech-02

**Status**: Accepted (MVP)

**Context**：解说音轨决定成片质量天花板，影视解说圈对"塑料音"敏感度高。

**Decision**：MVP 接 **火山豆包语音合成 API**（默认）+ **Minimax speech-02** 备选；本地方案 **CosyVoice2** 留作 v1.1 自部署选项。

**Consequences**：
- ✅ 火山豆包"灿灿"等音色已达短视频可用水准
- ✅ API 化避免 GPU 资源占用
- ✅ 支持中英混读、情感参数（语速/音调）
- ❌ 按字符计费，长片成本累积（10 万字 ≈ ¥10-30）
- ❌ API 限速（通常 5-10 QPS），需要本地队列

**Alternatives Considered**：
- ElevenLabs：质量顶级但成本极高且中文不如国产
- Azure TTS：稳定但音色偏"机器播报"
- CosyVoice2 本地：开源、零成本，但需 GPU + 工程化复杂度，留 v1.1

---

### ADR-003：镜头切分 — PySceneDetect ContentDetector

**Status**: Accepted (MVP)

**Context**：需要一个开箱即用、CPU 可跑、对动漫和实拍都稳定的镜头切分工具。

**Decision**：使用 **PySceneDetect** + **ContentDetector**（threshold=27 默认）。

**Consequences**：
- ✅ Python 原生，零依赖外部服务
- ✅ CPU 可跑（90 min 电影约 3-5 min 处理时间）
- ✅ 对色彩/亮度变化敏感，对动漫战斗、转场识别准确
- ❌ 渐变转场（淡入淡出）易漏切，需配合 AdaptiveDetector 微调
- ❌ 阈值需要按品类调整（实拍 27 / 动漫 20）— v1.1 做品类自适应

**Alternatives Considered**：
- TransNetV2：深度学习模型，召准更高，但需 GPU + 模型加载开销
- FFmpeg `scene` filter：最快但召准低，会把每个剪辑都拆成 N 段
- 不切分（按固定 5s 切片）：最简单但视觉不自然

---

### ADR-004：ASR 选型 — Whisper-large-v3 / FunASR-Paraformer

**Status**: Accepted (MVP)

**Context**：影视/动漫对白多有背景音乐和音效干扰，普通 ASR 词错率会偏高。

**Decision**：MVP 默认 **Whisper-large-v3**（多语言通用），中文场景可切换 **FunASR Paraformer-large**（中文专精）。

**Consequences**：
- ✅ Whisper 时间戳准确，支持 zh/en/ja（覆盖电影+动漫）
- ✅ 本地部署（避免 API 长视频成本）
- ✅ 句级 timestamp 和置信度满足绑定算法需求
- ❌ Whisper 对动漫女声/儿童音偶尔漏识，需 v1.1 引入 VAD 预处理
- ❌ Large 模型需 ≥10GB VRAM（MVP 接受 medium 模型作为降级）

**Alternatives Considered**：
- 阿里云 / 字节 ASR API：质量高但长视频成本高（90 min ≈ ¥3-10/次）
- WhisperX：带强制对齐，更精确但工程复杂
- Faster-Whisper（CTranslate2）：速度快 4x，MVP 性能够就先不引入

---

### ADR-005：存储 — SQLite + 本地文件系统

**Status**: Accepted (MVP only, will revisit at v2)

**Context**：MVP 是单机 Demo，只服务 1 个开发者自用，不需要并发/分布式。

**Decision**：**SQLite** 存元数据 + **本地文件系统** 存大文件（视频/音频/帧）。

**Consequences**：
- ✅ 零部署、零配置、单文件迁移
- ✅ 整个项目可以打包成 docker 一键运行
- ✅ Pydantic + SQLAlchemy 同套 ORM 未来可平滑切 Postgres
- ❌ 多用户并发场景必须切 Postgres（不在 MVP 范围）
- ❌ 大文件检索能力差，但 MVP 不需要

**Alternatives Considered**：
- Postgres：未来 v2 会切，但 MVP 引入太重
- MongoDB：JSON 字段方便但 ACID 不如 SQLite
- 纯 JSON 文件：太脆弱，事务和查询不便

---

### ADR-006：任务队列 — In-Process Worker（MVP）

**Status**: Accepted (MVP only)

**Context**：MVP 阶段任务并发数 ≤ 1，但流水线阶段多（5 个），需要状态可见。

**Decision**：MVP 用 **FastAPI BackgroundTasks + asyncio Queue**（in-process），不引入 Celery/RQ。

**Consequences**：
- ✅ 零额外依赖（不需要 Redis/RabbitMQ）
- ✅ 调试方便、日志集中
- ❌ 进程重启任务丢失（MVP 接受，提供 resume 接口作为 v1.1）
- ❌ 不能横向扩展，但 MVP 不需要

**Alternatives Considered**：
- Celery + Redis：v2 必上，MVP 太重
- RQ：比 Celery 轻，仍需要 Redis
- Dramatiq：现代化但生态弱于 Celery

---

### ADR-007：前端 — 极简 Web UI（FastAPI + Jinja）或 CLI

**Status**: Proposed (待用户选择)

**Context**：S1 验收只要"端到端跑通"，前端只是为了演示流程。

**Decision Options**：
- **A. CLI Only**：Click/Typer 命令行 + 输出 mp4 + 配套 JSON 时间线（最快出 Demo）
- **B. 极简 Web**：FastAPI + Jinja + 几个 HTML 页面（上传/进度/预览/编辑）
- **C. 现代 Web**：Next.js + React 编辑器（功能完整但工程量翻倍）

**MVP 推荐**：**B（极简 Web）**——上传需要 UI，进度查看需要 UI，原音保留标记 M3-b 也需要时间线 UI。Next.js 留到 S2/S3。

---

## 10. 风险评估 + 缓解策略

| # | 风险 | 概率 | 影响 | 缓解策略 |
|---|---|---|---|---|
| R1 | **AI 解说稿质量不达"二创"标准**（被吐槽流水线复述） | 🔴 高 | 🔴 高 | ① 在 prompt 里强制注入"风格预设"（剧情速览/吐槽/严肃影评等）<br>② MVP 后做用户调研，迭代 5+ 个 prompt 版本<br>③ 提供"重新生成"按钮，用户不满意可重抽 |
| R2 | **句子↔镜头绑定算法画面不贴文** | 🔴 高 | 🟡 中 | ① MVP 默认时间线跟随策略，画面和原片同步天然不脱节<br>② 编辑器允许用户单句替换镜头<br>③ v1.1 加入 VLM 语义检索升级路径 |
| R3 | **TTS 时长偏差导致拼接卡顿** | 🟡 中 | 🟡 中 | ① Assembly 阶段做时长再适配（拉伸/裁剪镜头）<br>② TTS 选支持 speed 参数的服务，必要时 0.95-1.05 微调 |
| R4 | **ASR 漏识/错识导致剧情骨架失真** | 🟡 中 | 🔴 高 | ① 用 Whisper-large 而非 medium<br>② 后处理过滤 confidence < -1.0 的句子<br>③ 严重失真时给 warning，建议用户改用 v1.1 强 VLM 模式 |
| R5 | **LLM 生成 JSON 格式损坏** | 🟡 中 | 🟢 低 | ① 用 structured output / json_mode<br>② 失败时 jsonrepair 库修复，仍失败则 retry 3 次 |
| R6 | **FFmpeg filter graph 过长导致 OOM** | 🟢 低 | 🔴 高 | ① 镜头数 > 200 时分批 concat<br>② 使用临时中间文件避免一次性巨型 graph |
| R7 | **版权 — 用户用本工具生成的视频被平台下架** | 🔴 高 | 🟡 中（用户侧） | ① 产品定位 B（创作助手）已把责任前置给用户<br>② Disclaimer：「本工具不保证生成内容可发布，用户需自行评估版权风险」<br>③ 不内置任何"反规避"功能（不变速、不加滤镜伪装） |
| R8 | **MVP 工期超过 4 周**（违反 S1 验收） | 🟡 中 | 🟡 中 | ① 严格遵守"M3-a 推后到 v1.1"<br>② 前端选 B 极简方案，不做 React 编辑器<br>② 镜头自适应、品类自适应等优化全部留给 v1.1 |
| R9 | **依赖外部 API 不稳定**（LLM/TTS 限速、降级） | 🟡 中 | 🟡 中 | ① 抽象 LLMProvider / TTSProvider 接口，至少 2 个 provider 实现<br>② 失败重试 + circuit breaker<br>② 全部任务可断点续跑（state 持久化在 SQLite） |

---

## 11. S1 演进路线图（MVP → v1.1 → v2）

### 11.1 S1（MVP）— 4 周完成

**M1（Week 1）：技术骨架 + Ingest + Index 跑通**
- 项目脚手架（FastAPI + SQLite + 目录骨架）
- Ingest 模块（视频归一化 + 音轨抽离）
- Index 模块（PySceneDetect + Whisper）
- ✅ 验收点：上传一部电影，能在 data/ 下看到完整 shots.json + asr.json

**M2（Week 2）：Scripting 跑通（最难）**
- LLM Provider 抽象（先只接通义千问）
- Plot Outline 提取
- 解说稿生成（先支持 1 种 style preset："剧情速览"）
- 句子↔镜头绑定算法（默认时间线跟随）
- ✅ 验收点：能输出一份 timeline.json，肉眼可见解说和镜头对得上

**M3（Week 3）：Render 跑通 + 端到端联调**
- TTS Provider 抽象（先只接火山豆包）
- FFmpeg 拼接（filter_complex）
- M2 智能让位混音（sidechain ducking）
- ✅ 验收点：端到端跑出第一支 4 分钟 mp4 成片

**M4（Week 4）：极简 Web UI + 编辑器 + M3-b 手动标记 + 体验打磨**
- FastAPI + Jinja 上传/进度/预览页
- 时间线编辑器（改稿 / 替换镜头 / 标记原音保留）
- ✅ 最终验收点：用 3 部不同电影跑通，输出物自己看得过去

### 11.2 v1.1（S1 + 1-2 个月）— 体验提升

- M3-a：AI 自动推荐"原音保留段"（音频事件分类）
- VLM 语义检索（剪辑哲学 Z 的进化）
- 多 style preset（吐槽 / 影评 / 速览 / 严肃）
- 多 TTS 音色 + 用户音色克隆（V4）
- 任务断点续跑、失败 resume

### 11.3 v2（S2/S3 阶段）— 产品化

- 切 Postgres + Celery + 用户系统
- Next.js 现代化编辑器（拖拽 / 波形图 / 缩略图条）
- T2 时长档位（10-15 min 深度解说）
- 文稿粒度从 P3 句子层 → 段落层完整启用
- B 端 SaaS / 多用户

---

## 12. 待用户确认的开放问题

下列 3 项还需要你拍板，会直接影响下一步 plan.md 的任务拆解：

- **Q1**：前端是 **CLI Only** / **极简 Web** / **现代 Web**？我推荐"极简 Web"。
- **Q2**：MVP 阶段你是否有可用 GPU（≥10GB VRAM）跑 Whisper-large？
  - 有：默认走本地 Whisper
  - 无：MVP 改用 OpenAI Whisper API 或国内 ASR API（成本约 ¥3-8/电影）
- **Q3**：开发语言确认 — 后端 **Python 3.11**，是否接受？前端如果选"极简 Web"用 Jinja2；如果未来切现代 Web 优先 **Next.js + React + TypeScript**。


---

# Part II — 方案 D 调整记录（2026-05-04 11:18）

> **变更触发**：用户在 review v0.1 时提出"能否把生成结果导入剪映"。经调研发现成熟开源库 `pyJianYingDraft` 可生成剪映草稿，遂将产品形态从"自建编辑器+mp4 出片"调整为"**剪映草稿包输出 + 极简 Web 状态页**"。
>
> **变更范围**：颠覆 ADR-007、第 8.5 节 Render、第 11 节路线图；新增 ADR-008；微调 ADR-004、第 6 节数据模型、第 7 节数据流、第 8.4 节 Assembly。
>
> **影响评估**：MVP 工期由 4 周压缩到 **3 周**；编辑器工程量从 1500-3000 行降到 0；用户工作流从"在 AutoClip 内编辑"改为"在剪映内编辑"。
>
> **决策原则**：保留 v0.1 原章节不删（保留决策演变痕迹），通过 §13-§16 增量覆盖关键章节；阅读时以本 Part II 为准。

---

## 13. ADR 修订与新增

### ADR-004 修订：ASR 选型 — 改为 API 优先

**Status**: Superseded by this revision (原 v0.1 ADR-004: Whisper-large-v3 本地)

**触发原因**：用户确认无 GPU。

**新决策**：MVP 默认 **OpenAI Whisper API**（按分钟计费 $0.006/min ≈ ¥0.04/min），90 min 电影约 ¥3.6/次；备选 **阿里云智能语音转写**（中文准确率更高，约 ¥0.5-2/次），**字节火山 ASR**（与火山 TTS 同账号，集成方便）。

**Consequences**：
- ✅ 零 GPU 依赖，开发者笔记本即可全流程开发
- ✅ ASR 阶段并发能力交给云端，本地资源全部留给 Index/Render
- ✅ 单部电影 ASR 成本 < ¥5，可控
- ❌ 长视频 API 上传慢（90 min 音频文件 ~50MB，建议先 ffmpeg 压缩到 16kHz mono 再上传）
- ❌ 网络抖动导致重试，需要分段上传 + 断点续传（v1.1 优化）

**MVP 实现**：抽象 `ASRProvider` 接口，先实现 `OpenAIWhisperProvider`，预留 `AliyunASRProvider` / `LocalWhisperProvider` 实现位。

---

### ADR-007 修订：前端方案 — 极简 Web 状态页（不含编辑器）

**Status**: Superseded by this revision (原 v0.1 ADR-007: Proposed 三选一)

**触发原因**：用户先选 C 现代 Web，后采纳剪映对接方案 D 后，编辑器需求消失。

**新决策**：**FastAPI + Jinja2 + 原生 JS + Tailwind CDN** 极简 Web 状态页，**不实现任何编辑器组件**。

**页面清单（共 4 个）**：

| 页面 | 路由 | 功能 |
|---|---|---|
| 上传页 | `GET /` | 拖拽上传视频 + 选时长档位 + 选风格预设 + 提交 |
| 任务列表 | `GET /jobs` | 历史任务列表（状态/进度/耗时/操作） |
| 任务详情 | `GET /jobs/{id}` | 单任务进度详情（5 个 stage 进度条 + 错误日志） |
| 结果页 | `GET /jobs/{id}/result` | 下载 .zip 草稿包 + 显示"如何导入剪映"图文教程 + 解说稿预览（只读） |

**Consequences**：
- ✅ 总前端代码量 < 600 行（4 模板 + 1 个公共 layout + 简单 JS 轮询任务状态）
- ✅ 1 名工程师 3-4 天可写完
- ✅ 零编辑器维护负担
- ❌ 用户必须装剪映才能继续创作（限定客群：影视解说圈，本来就 99% 在用剪映）
- ❌ 移动端体验差（剪映草稿格式仅支持桌面端导入）— MVP 接受

**Alternatives Reconsidered**：
- 现代 Web (Next.js)：编辑器消失后，Next.js 反而是过度工程，**v2 重新评估**
- 纯 CLI：上传/进度/下载无 UI 体验差，**否决**

---

### ADR-008（新增）：剪映草稿对接 — pyJianYingDraft

**Status**: Accepted

**Context**：方案 D 的核心实现依赖于"用代码生成剪映可识别的草稿文件"。剪映草稿本质是 `draft_content.json` + `draft_meta_info.json` + `materials/` 素材文件夹的组合，剪映启动时扫描 `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/` 目录加载草稿。

**Decision**：MVP 使用开源库 **`pyJianYingDraft`**（GitHub: GuanYixuan/pyJianYingDraft，PyPI: `pyjianyingdraft`）作为剪映草稿生成层，**不自己逆向 JSON 格式**。

**Consequences**：
- ✅ 草稿 JSON 格式由库维护，用户升级剪映后维护成本由社区分担
- ✅ 库提供 `Track / Segment / Clip / Audio / Text / Effect / KeyFrame` 全套高层 API，与本项目数据模型 1:1 映射
- ✅ 跨平台：Windows / macOS / Linux 都能生成草稿（macOS 是用户当前系统）
- ✅ 模板模式：未来支持用户上传"自己的剪映模板"作为风格基础
- ❌ 仅支持剪映 5.9 及以下未加密版本最稳；新版本（6.x+）部分草稿 schema 加密 — 缓解：MVP 推荐用户使用 5.9 版本（影视解说圈仍是主流）；同时观察 pyJianYingDraft 对新版本的兼容进度
- ❌ CapCut 海外版兼容仍在开发中 — 不影响 MVP（国内场景）
- ❌ 引入第三方依赖，库停更风险存在 — 缓解：抽象 `DraftExporter` 接口，未来可切换到自研格式生成器或 Premiere XML / Final Cut XML 等通用格式

**核心 API 使用示意**：

```python
import pyJianYingDraft as draft

# 1. 创建草稿
script = draft.Script_file(width=1920, height=1080, fps=25)

# 2. 添加素材
video_material = draft.Video_material("/path/to/normalized.mp4")
audio_material = draft.Audio_material("/path/to/narration.wav")
script.add_material(video_material)
script.add_material(audio_material)

# 3. 创建轨道
video_track = script.add_track(draft.Track_type.video, "video_main")
narration_track = script.add_track(draft.Track_type.audio, "narration")
original_audio_track = script.add_track(draft.Track_type.audio, "original")

# 4. 按 Sentence 添加片段
for sent in timeline.all_sentences():
    for binding in sent.clip_bindings:
        # 视频片段：从原片裁剪 + 落在解说时间线上
        video_track.add_segment(draft.Video_segment(
            material=video_material,
            target_timerange=draft.Timerange(sent.start_sec_in_timeline, binding.duration),
            source_timerange=draft.Timerange(binding.use_start_sec, binding.duration),
        ))
    
    # 解说音频片段
    narration_track.add_segment(draft.Audio_segment(
        material=audio_material,
        target_timerange=draft.Timerange(sent.start_sec_in_timeline, sent.actual_duration_sec),
        source_timerange=draft.Timerange(sent.tts_offset_sec, sent.actual_duration_sec),
        volume=1.0 if not sent.audio_override else 0.0,  # M3-b 标记的句子静音
    ))
    
    # 原音轨片段（音量曲线由 M3-b 控制）
    original_audio_track.add_segment(draft.Audio_segment(
        material=video_material,
        target_timerange=draft.Timerange(sent.start_sec_in_timeline, sent.actual_duration_sec),
        source_timerange=draft.Timerange(binding.use_start_sec, sent.actual_duration_sec),
        volume=1.0 if sent.audio_override == "keep_original" else 0.15,
    ))

# 5. 导出草稿（写入 ~/Movies/JianyingPro/User Data/Projects/...）
script.dump("/Users/.../JianyingPro/User Data/Projects/com.lveditor.draft/AutoClip_xxx/")
```

**Alternatives Considered**：
- 自己逆向 JSON 格式：开发周期 +2 周，维护成本极高
- Adobe Premiere XML 输出：通用格式但 PR 国内创作者占比低（影视解说圈 < 5%）
- Final Cut Pro XML：仅 Mac，且影视解说圈占比更低
- 直接生成 mp4（保留 v0.1 方案）：用户无法继续编辑，违背"创作助手"定位


---

## 14. Render 模块重写（替代原 §8.5）

> **本节替代 v0.1 §8.5**。原 §8.5 使用 FFmpeg 直接合成 mp4，方案 D 改为生成剪映草稿包。

### 14.1 新职责定义

**输入**：完整的 `Timeline`（含所有 Sentence、ClipBinding、TTSAudio、AudioOverride）+ 原视频文件
**输出**：可直接被剪映打开的草稿包目录，结构如下：

```
output/AutoClip_<job_id>/                          ← 草稿目录名（剪映里显示的草稿名）
├── draft_content.json                             ← 时间线核心（pyJianYingDraft 生成）
├── draft_meta_info.json                           ← 草稿元数据（封面、版本、修改时间）
├── materials/                                     ← 素材集合
│   ├── video/
│   │   └── source.mp4                             ← 原视频（软链接或拷贝）
│   └── audio/
│       ├── narration.wav                          ← 拼接后的解说总轨（按句拼接，TTS 总和）
│       └── （如有用户音色克隆）voice_xxx.wav
└── README.txt                                     ← AutoClip 元信息（job_id / 生成时间 / 源解说稿全文）
```

**交付物**：将整个目录**zip 打包**供用户下载，或在用户授权下**直接写入剪映草稿目录**：
- macOS: `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/`
- Windows: `C:/Users/<user>/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/`

### 14.2 草稿轨道结构（核心设计）

剪映草稿采用**多轨道堆叠**模型，与原 v0.1 的"单 mp4 + 双音轨"对应关系如下：

```
┌──────────────────────────────────────────────────────────────────┐
│  剪映时间线（从上到下）                                              │
│                                                                    │
│  Track 1: 字幕轨（subtitle）        ← 解说文本（可选，便于用户       │
│           [句1文字][句2文字][句3文字...]    在剪映里直接套样式）       │
│                                                                    │
│  Track 2: 视频主轨（video_main）    ← 拼接的镜头序列                │
│           [shot12.3-16.5][shot20.1-23.4][shot45.0-48.7]...        │
│                                                                    │
│  Track 3: 解说音轨（narration）     ← TTS 拼接，volume=1.0 (默认)   │
│           [TTS 句1][TTS 句2]   ___   [TTS 句4]   ___              │
│                              ↑标记原音段时静音                       │
│                                                                    │
│  Track 4: 原始音轨（original）      ← 从原视频抽取，跟随视频片段     │
│           [原音12.3-16.5(0.15)][原音20.1-23.4(0.15)]              │
│           [原音45.0-48.7(1.0) ★] ← M3-b 标记段，音量曲线拉满       │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

**关键设计点**：
1. **视频轨与原音轨完全同步**：剪映里 `target_timerange` 和 `source_timerange` 对应一致，原音 = 该镜头自身的音
2. **解说轨独立时间线**：按 Sentence 顺序拼接，时长 = TTS 实际时长之和
3. **音量曲线由静态值表达**（MVP）：M3-b 标记的段直接 `volume=1.0`，其他段 `volume=0.15`；v1.1 升级为剪映关键帧动画（解说有声→0.15，无声→0.7 渐变）
4. **字幕轨可选**：MVP 默认开启（用户在剪映里可一键改字体/位置/动画）

### 14.3 实现伪代码

```python
import pyJianYingDraft as draft
from pathlib import Path

class JianyingDraftExporter:
    def export(self, timeline: Timeline, video_path: Path, 
               output_dir: Path) -> Path:
        """
        生成剪映草稿目录，返回草稿目录绝对路径。
        """
        # === Step 1: 准备素材文件 ===
        materials_dir = output_dir / "materials"
        materials_dir.mkdir(parents=True, exist_ok=True)
        
        # 视频素材：拷贝（剪映要求绝对路径，且不能移动）
        video_dst = materials_dir / "video" / "source.mp4"
        shutil.copy(video_path, video_dst)
        
        # 解说音轨：拼接所有 TTS 片段为一个 wav
        narration_path = self._concat_tts(timeline, materials_dir / "audio" / "narration.wav")
        
        # === Step 2: 创建草稿对象 ===
        script = draft.Script_file(width=1920, height=1080, fps=25)
        
        video_mat = draft.Video_material(str(video_dst))
        narration_mat = draft.Audio_material(str(narration_path))
        script.add_material(video_mat)
        script.add_material(narration_mat)
        
        # === Step 3: 创建轨道 ===
        text_track = script.add_track(draft.Track_type.text, "subtitle")
        video_track = script.add_track(draft.Track_type.video, "video_main")
        narr_track = script.add_track(draft.Track_type.audio, "narration")
        orig_track = script.add_track(draft.Track_type.audio, "original")
        
        # === Step 4: 遍历 Sentence 添加片段 ===
        narration_offset = 0.0  # 解说轨内累计偏移
        for sent in timeline.all_sentences():
            sent_start = sent.start_sec_in_timeline
            sent_dur   = sent.actual_duration_sec
            keep_orig  = (sent.audio_override and 
                         sent.audio_override.mode == "keep_original")
            
            # 4.1 视频片段 + 同步原音片段（一句解说可对应多个镜头）
            for binding in sent.clip_bindings:
                clip_dur = binding.use_end_sec - binding.use_start_sec
                
                video_track.add_segment(draft.Video_segment(
                    material=video_mat,
                    target_timerange=draft.Timerange(sent_start, clip_dur),
                    source_timerange=draft.Timerange(binding.use_start_sec, clip_dur),
                ))
                
                # 原音轨：跟随视频片段，音量由 keep_orig 决定
                orig_track.add_segment(draft.Audio_segment(
                    material=video_mat,  # 复用视频素材的音轨
                    target_timerange=draft.Timerange(sent_start, clip_dur),
                    source_timerange=draft.Timerange(binding.use_start_sec, clip_dur),
                    volume=1.0 if keep_orig else 0.15,
                ))
                sent_start += clip_dur
            
            # 4.2 解说音频（M3-b 标记段静音）
            if not keep_orig:
                narr_track.add_segment(draft.Audio_segment(
                    material=narration_mat,
                    target_timerange=draft.Timerange(
                        sent.start_sec_in_timeline, sent_dur),
                    source_timerange=draft.Timerange(narration_offset, sent_dur),
                    volume=1.0,
                ))
                narration_offset += sent_dur
            # keep_orig 段：narration_offset 不前进（该句没生成 TTS）
            
            # 4.3 字幕（可选）
            text_track.add_segment(draft.Text_segment(
                text=sent.text,
                target_timerange=draft.Timerange(
                    sent.start_sec_in_timeline, sent_dur),
                style=draft.Text_style(font_size=48, color=(1,1,1)),
            ))
        
        # === Step 5: 写入草稿 ===
        script.dump(str(output_dir))
        
        # === Step 6: 写 README + 元信息 ===
        self._write_readme(timeline, output_dir / "README.txt")
        return output_dir
    
    def _concat_tts(self, timeline, dst_path):
        """把所有非 keep_original 的 sentence TTS 按顺序拼成一个 wav"""
        # 用 ffmpeg concat：
        # ffmpeg -f concat -safe 0 -i list.txt -c copy narration.wav
        ...
    
    def _write_readme(self, timeline, dst_path):
        """写入 job 元信息和完整解说稿，便于用户查看"""
        ...
```

### 14.4 与 v0.1 §8.4 Assembly 的协作关系（M3-b 实现变化）

原 v0.1 §8.4 描述的"M3-b 处理"在 FFmpeg 模式下需要：
- 静音 TTS、设置 `narration_volume=0`
- sidechain ducking 在该段不触发
- 原音音量手动拉到 1.0

**方案 D 下大幅简化**：
- M3-b 标记的 sentence **直接跳过 TTS 合成**（不进入 narration.wav）
- 在 narration_track 上**不放 segment**（自然静音）
- 在 original_track 上把该段 segment 的 `volume` 改成 1.0
- **完全不需要 sidechain ducking**——剪映播放时多轨道按 volume 直接 mix

这意味着 §8.4 的 `apply_audio_overrides` 函数**不再需要**，逻辑下沉到 §14.3 的 `keep_orig` 分支即可。

### 14.5 失败模式与缓解

| 失败 | 影响 | 缓解 |
|---|---|---|
| pyJianYingDraft 不兼容用户的剪映版本 | 草稿打不开 | ① 启动时检测剪映版本（读 `~/Movies/JianyingPro/version.txt`）<br>② 不兼容版本给警告，建议用户用 5.9<br>③ MVP 接受"仅支持 5.x" |
| 素材路径含中文/特殊字符 | 剪映找不到素材 | 文件命名一律 ASCII（用 job_id 命名） |
| 用户操作系统非 macOS/Windows | 无法直接打开剪映 | 仅生成草稿包 zip，让用户手动放置 |
| TTS 拼接 wav 过大（超 200MB） | 加载慢 | MVP 接受；v1.1 改为按句独立 audio segment |

### 14.6 性能预算变化（vs v0.1 §7.2）

| 阶段 | v0.1 mp4 模式 | 方案 D 草稿模式 |
|---|---|---|
| Render | < 3 min（FFmpeg 拼接 + 混音） | **< 30 秒**（仅 TTS 拼接 + JSON 序列化） |
| **端到端** | **< 16 min** | **< 13 min** |

> Render 阶段提速 6-10 倍 — 这是方案 D 最直接的工程收益。


---

## 15. 路线图修订（替代原 §11.1 S1 部分）

> **本节替代 v0.1 §11.1**。原 §11.2（v1.1）和 §11.3（v2）保持不变，仅 v1.1 微调一项（M3-a 实现下沉到剪映音量曲线关键帧）。

### 15.1 S1（MVP）— **3 周完成**（原 4 周）

**关键变化**：
- M3 / M4 合并为新 M3（剪映草稿导出 + 极简 Web）
- 编辑器开发任务**完全移除**
- Render 阶段从 FFmpeg 拼接简化为 JSON 序列化

**M1（Week 1）：技术骨架 + Ingest + Index 跑通**
- 项目脚手架（FastAPI + SQLite + 目录骨架 + pyproject.toml + 依赖固定）
- `ASRProvider` 抽象 + `OpenAIWhisperProvider` 实现
- Ingest 模块（FFmpeg 视频归一化 + 音轨抽离 + 音频压缩为 16kHz mono）
- Index 模块（PySceneDetect 镜头切分 + ASR API 调用 + 结果落盘）
- ✅ **验收点**：上传一部 90min 电影，10min 内能在 `data/{video_id}/` 下看到完整 `shots.json` + `asr.json`

**M2（Week 2）：Scripting 跑通（最难，最值得投入）**
- `LLMProvider` 抽象 + `QwenProvider` 实现（通义千问 qwen-plus）
- Plot Outline 提取（LLM Prompt v1）
- 解说稿生成（先支持 1 种 style preset："剧情速览"）
- ★ 句子↔镜头绑定算法（默认时间线跟随，含降级策略）
- Timeline 数据结构落 SQLite
- ✅ **验收点**：能输出一份 `timeline.json`，肉眼检查解说和镜头时间区间匹配合理

**M3（Week 3）：Render（剪映草稿）+ 极简 Web + 端到端联调**

子任务（按依赖顺序）：

| # | 子任务 | 估时 | 验收 |
|---|---|---|---|
| 3.1 | `TTSProvider` 抽象 + 火山豆包接入 | 0.5d | 单句 TTS 能落盘 |
| 3.2 | TTS 批量合成 + 拼接为 narration.wav（M3-b 标记句跳过） | 0.5d | 解说总轨可播放 |
| 3.3 | Assembly 时长再适配（TTS 实际时长 vs 估算） | 0.5d | timeline 时间戳归一化通过 |
| 3.4 | `JianyingDraftExporter` 实现（基于 pyJianYingDraft） | 1.5d | 生成的草稿能被剪映 5.x 打开 |
| 3.5 | 草稿轨道结构验证（4 轨道 + M3-b 音量逻辑） | 0.5d | 剪映播放预览音轨混音正确 |
| 3.6 | FastAPI + Jinja 极简 Web（4 页面） | 1d | 上传 → 进度 → 下载草稿包闭环 |
| 3.7 | 端到端联调 + 3 部不同电影回归测试 | 1d | 3 部成片均可在剪映打开并继续编辑 |

- ✅ **最终验收点**：用 3 部不同类型作品（1 部电影 + 1 部电视剧单集 + 1 部动漫单集）跑通，输出的剪映草稿在剪映中**可打开、可播放、轨道结构正确、解说与画面对得上**。

**M3 缓冲**：第 3 周末预留 0.5-1 天作为 buffer，应对剪映版本兼容性 / 中文路径 / pyJianYingDraft 边角 case。

### 15.2 S1 全周期里程碑总览

```
Week 1            Week 2            Week 3
├──── M1 ────┼──── M2 ────┼──── M3 ────┤
Ingest+Index   Scripting     Render+Web
   ↓             ↓             ↓
shots.json     timeline.json  剪映草稿包
asr.json                      .zip
                              （可在剪映中打开）
```

**关键路径**（决定能否 3 周达成 S1 的 must-have）：
- M2.句子↔镜头绑定算法（最难，质量决定整个产品价值）
- M3.4 JianyingDraftExporter（最不确定，依赖外部库版本兼容性）

**并行机会**：
- M1 完成后，M3.6（极简 Web 模板）可与 M2 并行（前端代码不依赖 Scripting）
- M3.1（TTS Provider）可在 M2 期间提前验证 API 调用

### 15.3 v1.1 增量调整（基于 §11.2）

原 §11.2 已列计划基本不变，**唯一调整**：
- **M3-a（AI 自动推荐"原音保留段"）的实现方式变更**：
  - 原方案：音频事件分类 + FFmpeg sidechain 阈值
  - **新方案**：仍是音频事件分类（YAMNet/PANNs），但输出**直接写入剪映的音量关键帧动画**——即 narration_track 在该段渐变到 0、original_track 在该段渐变到 1.0，用户在剪映里看到的是带关键帧的音量曲线，可视化、可手动调整
  - 工程量：**与原方案持平**，但用户体验提升一档（剪映里的音量曲线对创作者是熟悉的交互）

### 15.4 v2 阶段调整（基于 §11.3）

- 原 v2 的"Next.js 现代化编辑器"**永久取消**——剪映对接已永久解决了编辑器问题
- 原本编辑器的工程预算**重新分配**到：
  - B 端 SaaS 多用户能力（更值得投入）
  - 自研草稿格式 fallback（防止 pyJianYingDraft / 剪映版本断裂的灾难）
  - Premiere XML / Final Cut XML 输出（拓展专业用户群）


---

# Part III — v0.3 多角度评审修订（2026-05-04 11:57）

> **变更触发**：用户在 review v0.2 时要求"多角度评价方案，3 轮讨论后达成共识"。AI 扮演 4 个角色（产品经理 Eve / 算法工程师 Lin / 工程架构师 Rao / 法律顾问 Wu）独立评审，产出 12 项修订（5 项 P0 阻塞 / 5 项 P1 必须 / 2 项 P2 最简实现），用户全盘接受。
>
> **变更原则**：保留 Part I（v0.1）和 Part II（v0.2）原章节不删；通过 §16-§19 增量覆盖关键决策；阅读时以 Part III 为最高优先级。
>
> **总评**：v0.2 方向正确但过于乐观。v0.3 修订后**MVP 工期 5-6 周**（不是 3 周）、**核心算法升级**、**合规设计前置**、**测试与防御性设计补齐**。

---

## 16. P0 修订（5 项 — 阻塞 MVP 启动）

### 16.1 ADR-004 再修订：ASR 默认改为阿里云智能语音转写

**Status**: Supersedes Part II §13 ADR-004 revision (Whisper API)

**触发原因**：算法工程师 Lin 指出 Whisper 在影视配乐+多人对白场景下中文 WER 实测 15-25%，比中文专精模型差一档。ASR 准确率是产品质量天花板（剧情骨架的全部输入），必须用最稳的方案。

**新决策**：MVP 默认 **阿里云智能语音转写（一句话 + 长语音异步）**；备选 **火山 ASR**（与火山 TTS 同账号，集成方便）；OpenAI Whisper API 降级为 fallback。

**Consequences**：
- ✅ 中文影视/动漫场景 WER 5-10%，对剧情理解准确率提升 15-20 个百分点
- ✅ 阿里云 + 通义千问 + 火山 TTS 形成"国内云一站式"，账户/网络/合规更顺
- ✅ 长语音异步接口原生支持 90min+ 单文件上传
- ❌ 计费按时长（约 ¥0.5-2/小时音频）vs Whisper API ($0.006/分钟)，单部电影成本相近
- ❌ 仅支持中文为主的输入，纯日文动漫需要切回 Whisper 或火山 ASR

**MVP 实现**：`ASRProvider` 接口先实现 `AliyunASRProvider`（默认）+ `OpenAIWhisperProvider`（fallback），运行时通过配置切换。

---

### 16.2 ADR-006 修订：任务执行改为 multiprocessing + 文件状态机

**Status**: Supersedes Part I §9 ADR-006 (FastAPI BackgroundTasks)

**触发原因**：架构师 Rao 指出 FastAPI BackgroundTasks 在长任务（30min+）下会撑爆 worker，无 graceful 中断/恢复能力。MVP 用户第一次点"取消"按钮就崩 = Demo 灾难。

**新决策**：MVP 使用 **multiprocessing 子进程 + 文件状态机** 执行流水线任务；Web 进程通过文件系统轮询状态，子进程通过文件信号（`.cancel`）支持取消。

**架构**：

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI Web 进程（主进程，常驻）                         │
│   ↓ 接到 POST /jobs                                      │
│   ↓ multiprocessing.Process(target=run_pipeline, ...)   │
│   ↓ 立即返回 job_id                                      │
└─────────────────────────────────────────────────────────┘
                ↓ fork
┌─────────────────────────────────────────────────────────┐
│  Pipeline Worker 子进程（每个 job 独立进程）              │
│   状态文件：data/{job_id}/state.json                    │
│     {                                                    │
│       "stage": "indexing",                              │
│       "progress": 0.45,                                 │
│       "error": null,                                    │
│       "started_at": "...",                              │
│       "checkpoint": {"step": "asr", "done": ["shot"]}   │
│     }                                                    │
│                                                          │
│   每完成一个 stage 就 atomic write state.json           │
│   每个 stage 开始前检查 data/{job_id}/.cancel 文件       │
│   崩溃后下次启动可基于 checkpoint resume                 │
└─────────────────────────────────────────────────────────┘
```

**Consequences**：
- ✅ 长任务不阻塞 Web 进程，用户可随时刷新看进度
- ✅ 子进程崩溃不影响 Web；state.json 持久化，重启可 resume
- ✅ 取消机制简单可靠（写文件即可）
- ✅ 不引入 Redis/RabbitMQ 等外部依赖（仍是单机部署）
- ❌ 不支持横向扩展（v2 切 Celery 时再说）
- ❌ macOS fork 模式下 Whisper/PyTorch 模型加载需注意（用 spawn 模式 + 子进程内独立加载）

---

### 16.3 §8.3 算法重写：narrative IR + post-validation（绑定算法升级）

**Status**: Supersedes Part I §8.3 Step 8.3.3 binding algorithm

**触发原因**：算法工程师 Lin 与架构师 Rao 共同指出：原绑定算法假设"LLM 输出会精准遵守 linked_plot_nodes"，但实测 LLM 写稿时会幻觉时间区间，导致 30-50% 句子镜头匹配明显违和。**这是 MVP 最大的算法风险**。

**新算法（两阶段 + 反向校验）**：

#### Stage 1: LLM 输出扁平 narrative IR（不嵌套段落，不让 LLM 自报时间）

```text
[LLM Prompt 模板 v2]
你是 B 站头部影视解说 UP 主，风格="{style_preset}"。

下面是影片的剧情骨架：
{plot_outline_json}

下面是影片对白时间轴片段（仅供你引用证据用）：
{asr_sentences_compact}

请写一段总时长 {target_duration_sec} 秒的解说稿，输出格式必须为扁平的 IR 数组：
[
  {
    "id": 1,
    "text": "解说句",
    "evidence": "我写这句是因为原片对白/旁白里出现了：「xxx」",  ← 必须引用 ASR 原文
    "evidence_keywords": ["关键词1", "关键词2"],                 ← 用于反向检索
    "narrative_intent": "summary"|"comment"|"transition",
    "paragraph_hint": 0|1|2|...                                 ← 段落归属（可选）
  },
  ...
]

约束：
- 每句必须给出 evidence（来自 ASR 原文片段）；找不到证据的句子标 evidence: null
- 每句必须给出 2-5 个 evidence_keywords，用于工程层反向定位时间区间
- 严禁自报时间戳（time_range 字段不允许出现），时间由工程层计算
```

#### Stage 2: 工程层反向校验时间区间

```python
def resolve_time_for_sentence(ir_item, asr_sentences, shots):
    """
    用 evidence_keywords 反向检索 ASR，定位该解说句对应的原片时间窗口。
    返回 candidate_time_range: (start_sec, end_sec) 或 None。
    """
    # 1. 用 evidence_keywords 在 ASR 文本里检索（BM25 / 字符级匹配）
    candidates = []
    for asr_sent in asr_sentences:
        score = keyword_match_score(asr_sent.text, ir_item.evidence_keywords)
        if score > THRESHOLD:
            candidates.append((asr_sent, score))
    
    # 2. 取 top-3 得分最高的 ASR 句子，取其时间区间的并集
    top = sorted(candidates, key=lambda x: -x[1])[:3]
    if not top:
        return None  # fallback 到段落均分策略
    
    start = min(c[0].start_sec for c in top)
    end   = max(c[0].end_sec   for c in top)
    
    # 3. 与 LLM 自报的 paragraph_hint 对应的 plot_node 区间求交（容错）
    if ir_item.paragraph_hint is not None:
        hint_range = paragraphs[ir_item.paragraph_hint].time_range
        # 优先取交集，没交集就用反向检索的结果
        intersection = (max(start, hint_range[0]), min(end, hint_range[1]))
        if intersection[0] < intersection[1]:
            return intersection
    
    return (start, end)


def bind_clips(ir_items, asr_sentences, shots):
    """
    完整绑定流程：
    1. 对每个 ir_item 反向定位 candidate_time_range
    2. 在 candidate_time_range 内挑选镜头按贪心算法分配
    3. 失败 fallback：均分相邻段落区间
    """
    bindings = []
    for item in ir_items:
        time_range = resolve_time_for_sentence(item, asr_sentences, shots)
        if time_range is None:
            # Fallback: 用 paragraph_hint 区间均分
            time_range = fallback_paragraph_split(item, ir_items)
        
        candidates = [s for s in shots 
                      if s.start_sec >= time_range[0] and s.end_sec <= time_range[1]]
        bindings.append(greedy_assign(item, candidates))
    return bindings
```

#### MVP 验收 KPI（量化）

| 指标 | 目标 | 评估方法 |
|---|---|---|
| **绑定准确率** | ≥ 70% | 人工打标 50 个解说句的镜头匹配是否"合理" |
| **evidence 召回率** | ≥ 80% | LLM 输出 evidence 字段非 null 的比例 |
| **fallback 触发率** | ≤ 30% | resolve_time_for_sentence 返回 None 的比例 |

> ⚠️ 如果 MVP 跑完达不到这 3 个 KPI，需要返工（增加 few-shot、调整 keyword 检索权重、优化 prompt）。

---


### 16.4 路线图重写：5-6 周 / 4 milestones

**Status**: Supersedes Part II §15.1 (3 weeks roadmap)

**触发原因**：架构师 Rao 拆解发现，原 §15.1 的"Scripting M2 = 1 周"严重低估（绑定算法实际工程量 500-1000 行 + 海量调参，需 2-3 周）。算法工程师 Lin 进一步指出 narrative IR + post-validation 升级再加 1 周。诚实工期为 **5-6 周**，对应 4 个 milestones。

**新版 S1 路线图**：

```
Week 1     Week 2-3              Week 4              Week 5     Week 6 (buffer)
├── M1 ───┼─── M2a ──── M2b ────┼── M3 ──────────────┼── M4 ───┼─────────────┤
Ingest    Scripting     Scripting    Render+Web         E2E +    KPI 验收 +
+Index    主链路         鲁棒性        +合规             质量验证   修复
                        +narrativeIR
```

#### M1（Week 1）—— 技术骨架 + Ingest + Index

- T1.1 项目脚手架（pyproject.toml + 依赖固定 + Makefile）
- T1.2 SQLite + ORM（Video / Job / Timeline / Sentence / ClipBinding 表）
- T1.3 FastAPI 主应用 + multiprocessing 任务执行框架（**新**：ADR-006 修订）
- T1.4 文件状态机（state.json 原子写 + checkpoint + .cancel 信号）
- T1.5 `ASRProvider` 抽象 + `AliyunASRProvider` 实现（**新**：ADR-004 再修订）
- T1.6 Ingest 模块（FFmpeg 视频归一化 + 音频抽离 + 16kHz mono 压缩）
- T1.7 Index 模块（PySceneDetect 镜头切分 + 关键帧抽取）
- T1.8 Index 模块（Aliyun ASR 调用 + 结果落盘 + 失败重试）
- ✅ **验收**：上传 90min 电影，10min 内 `data/{job_id}/` 下完整 `shots.json`+`asr.json`，state.json 进度更新正确，可取消可 resume

#### M2a（Week 2）—— Scripting 主链路（最小可行）

- T2.1 `LLMProvider` 抽象 + `QwenProvider` 实现（通义千问 qwen-plus）
- T2.2 Plot Outline 提取（Prompt v1）
- T2.3 解说稿生成（"剧情速览" style preset，Prompt v1，输出扁平 narrative IR）
- T2.4 LLM 输出 schema validation + JSON repair + retry 3 次
- T2.5 简化版绑定（仅按 paragraph_hint 时间区间贪心分配，不做 evidence 反向校验）
- T2.6 Timeline ORM + JSON 序列化
- ✅ **M2a 验收**：能输出 timeline.json，肉眼检查 50% 以上句子镜头匹配合理

#### M2b（Week 3）—— Scripting 鲁棒性（关键升级）

- T2.7 evidence_keywords 反向检索算法（BM25 / 字符级匹配）
- T2.8 `resolve_time_for_sentence` 实现（含 paragraph_hint 求交、fallback 到段落均分）
- T2.9 绑定算法约束补齐（最小镜头时长 0.8s / 单句最多 5 镜头 / 跨段不复用）
- T2.10 评估脚本：50 句人工打标 → 自动计算"绑定准确率"
- T2.11 Prompt v2 调优（few-shot 例子 × 3，覆盖电影/电视剧/动漫）
- ✅ **M2b 验收**：3 部不同类型作品的绑定准确率 ≥ 70%，evidence 召回率 ≥ 80%，fallback 触发率 ≤ 30%

#### M3（Week 4）—— Render（剪映草稿）+ 极简 Web + 合规

- T3.1 `TTSProvider` 抽象 + `VolcengineTTSProvider`（火山豆包）
- T3.2 TTS 批量合成（5 并发 + 失败重试）+ 拼接为 narration.wav
- T3.3 Assembly 时长再适配（含 ±20% 硬约束 + 超出时降级策略）
- T3.4 ★ `JianyingDraftExporter`（基于 pyJianYingDraft）
- T3.5 草稿轨道结构验证（4 轨道 + M3-b 音量逻辑 + 中文路径处理）
- T3.6 `JsonTimelineExporter` 防御实现（**新**：P1-3，剪映方案崩了的兜底）
- T3.7 极简 Web 4 页面（Jinja + Tailwind CDN）
- T3.8 ★ **零知识架构落地**（**新**：raw 文件 24h 自动删除 + 派生数据脱敏）
- T3.9 用户协议勾选拦截（**新**：未勾选不允许提交任务）
- ✅ **验收**：端到端跑通 1 部精选作品，剪映可打开草稿继续编辑

#### M4（Week 5）—— E2E 质量验证 + 多片回归

- T4.1 3 部不同类型作品（实拍剧情 / 实拍动作 / 动漫）端到端跑通
- T4.2 用户主观评分 ≥ 4/5（自评 + 1-2 个真实创作者朋友评）
- T4.3 风格预设扩展到 3 种（剧情速览 / 吐槽 / 严肃影评）
- T4.4 AI 自评分 + 一键重生成（**新**：P1-2）
- T4.5 错误兜底完善（任意 stage 失败有清晰错误提示 + 部分结果可用）
- ✅ **最终验收**：3 部作品都能在剪映打开 + 1 小时内人工调优到"愿意自己发布"水平

#### Week 6（Buffer）—— KPI 验收 + 关键修复

- 留作不可预见的兼容性问题、剪映版本适配、性能调优
- 不计入承诺工期，但**强烈建议预留**

#### 关键路径与并行机会

| 关键路径（must-have，串行） | 并行机会 |
|---|---|
| M1.基础设施 → M2a.主链路 → M2b.鲁棒性 → M3.4 草稿导出 → M4 E2E | M3.7 Web 模板可与 M2a 并行<br>T3.1 TTS Provider 可在 M2a 末尾提前接入<br>T3.6 JsonTimelineExporter 可与 T3.4 并行 |

---

### 16.5 零知识架构设计（合规设计前置）

**Status**: New section (P0-4, proposed by Wu)

**触发原因**：法律顾问 Wu 指出"用户上传的电影/动漫长期保留 = 版权方诉讼时的侵权证据库"。MVP 必须设计为"服务器永远不持有可还原原片的内容"，否则商业化前必然返工。

#### 设计目标

监管/版权方质问"你是否存储过侵权内容？"时，能基于系统设计**直接证伪**——不只是"我们已删除"，而是"我们**架构上不可能持有**"。

#### 数据生命周期分级

| 数据 | 是否落盘 | 生命周期 | 脱敏处理 |
|---|---|---|---|
| 上传的原视频 `source.mp4` | ✅ 临时落盘（FFmpeg 不支持纯流式处理 90min 视频） | **任务完成后立即删除**，最长不超过 24h（兜底定时清理任务） | — |
| 归一化视频 `normalized.mp4` | ✅ 临时落盘（Index/Render 阶段引用） | 同上，任务完成后删除 | — |
| 关键帧 `keyframes/*.jpg` | ✅ | 任务完成后删除（剪映草稿包不需要） | 480x270 低分辨率 |
| 音轨 `audio.wav` | ✅ 临时（ASR 用） | ASR 完成后立即删除 | 16kHz mono 已显著低于发布质量 |
| ASR 文本 `asr.json` | ✅ 长期保留（用于回放编辑） | 任务保留 30 天 → 仅保留 timeline 元数据 | **不保留可还原音频的信息** |
| 解说稿 `script.json` | ✅ 长期 | 同上 | 用户原创内容，归用户所有 |
| TTS 音频 `tts/*.wav` | ✅ 临时 | 草稿包打包后删除 | 仅含 AI 生成解说，无原片内容 |
| 剪映草稿包 `output/*.zip` | ✅ 临时 | 用户下载后 24h 删除 | **草稿引用素材的路径必须改写为占位符** |
| 操作日志 | ✅ 长期 | 30 天滚动 | 不记录视频文件名/路径具体内容 |

#### 关键设计点

1. **草稿包内素材引用改写**（最关键）：
   - pyJianYingDraft 默认要求素材绝对路径
   - **MVP 实现**：草稿包导出时，`draft_content.json` 里所有素材路径改写为相对路径占位符（如 `./materials/source.mp4`），并在 `README.txt` 中告知用户"双击草稿前需用剪映导入素材"
   - 这样草稿包**不包含原片本身**，仅包含轨道时间戳、音量曲线、解说音轨、字幕——**架构上不持有版权方可主张的内容**

2. **临时文件统一管理**：
   - 所有临时数据放在 `data/{job_id}/temp/` 目录
   - Pipeline Worker 在每个 stage 结束时调用 `cleanup_temp(job_id, stage)` 删除该 stage 的中间产物
   - 兜底定时任务（cron / FastAPI startup hook）：扫描 `temp/` 目录，删除 24h 未访问文件

3. **数据库脱敏**：
   - SQLite 中不存视频文件原始路径（用 hash 替代）
   - 不存 ASR 全文（仅存句级摘要 + 时间戳元数据）
   - Job 完成 30 天后自动清理 timeline 详细字段，仅保留摘要

4. **可证伪性 / 审计能力**：
   - 提供 `python -m autoclip.audit` 命令，扫描整个数据目录，生成"当前持有的所有数据清单"
   - 用户可随时执行"完全清理"指令，删除所有自己的数据

#### 工程量评估

| 项 | 估时 |
|---|---|
| 临时文件管理（cleanup hook + cron） | 0.5d |
| 草稿包素材路径占位符改写 + 用户引导 | 0.5d |
| 数据库脱敏（schema 调整 + 数据清理任务） | 0.5d |
| 审计命令 + "完全清理"接口 | 0.5d |
| 共计 | **2 天**（含在 M3 路线图） |

#### Consequences

- ✅ MVP 商业化前的合规审计能直接通过"架构层证伪"
- ✅ 用户感知"产品对版权敏感"，提升专业感
- ❌ 用户体验略变（需在剪映里手动重新导入素材），但有清晰引导可接受
- ❌ "断点续跑"功能受限（原片删了就续不了，必须重新上传）—— v1.1 解决方案：上传时打 hash，重传时跳过 Ingest


---

## 17. P1 修订（5 项 — MVP 必须包含，可在执行中并行）

### 17.1 风格预设扩展：3 种 + few-shot 例子（解决 LLM 风格不稳定）

**Status**: New (P1-1, proposed by Eve + Lin)

**触发原因**：MVP 仅 1 种 "剧情速览" 风格只能服务 10% 目标用户；LLM 在没有 few-shot 时风格输出极不稳定。

**MVP 实现 3 种风格预设**：

| Preset | 名称 | 调性 | 典型代表 | few-shot 例子来源 |
|---|---|---|---|---|
| `plot_summary` | **剧情速览** | 客观、紧凑、信息密度高 | 早期 X 分钟看电影类 | 自己手写 3 条 |
| `humor_roast` | **吐槽点评** | 幽默、口语化、带情绪 | 谷阿莫 / 马督工 | 公开网络收集脱敏 3 条 |
| `serious_review` | **严肃影评** | 深度、有观点、有铺垫 | 木鱼水心 / 电影最 TOP | 同上 3 条 |

**Prompt 工程结构**：

```python
# 风格预设配置
STYLE_PRESETS = {
    "plot_summary": {
        "system_prompt": "你是 B 站头部剧情速览解说 UP 主...",
        "few_shots": [
            {"input": "...", "output": "..."},  # 3 条例子
            ...
        ],
        "constraints": [
            "句子 12-25 字",
            "禁止出现「我觉得」「个人认为」等主观表述",
            "每段 4-6 句，节奏紧凑",
        ],
        "opening_templates": ["这是一部...", "故事开始于...", "今天给大家讲..."],
    },
    "humor_roast": { ... },
    "serious_review": { ... },
}
```

**工程量**：每种 preset ≈ 0.5d 设计 + 0.5d 调优 = **3d 总计**（M4 完成 2 种，M2b 先做 1 种 plot_summary）。

---

**v0.7 修订（M2a-fix brainstorming Q1-Q8 + 8 角度 critique，2026-05-05）— 升级为 5 种品类化预设矩阵**：

P1-1（Eve/Lin v0.3 提案）的 3 种风格预设（plot_summary / humor_roast / serious_review）在 M2a baseline 实施过程中暴露出 **"风格按 UP 主分类而非按内容品类分类"** 的根本问题：用户上传一个动漫片段（应当用"燃向激昂"调性），但 LLM 仍按"客观剧情速览"输出冷叙述，导致 R5（第三人称冷叙述）100% 命中、K-style-1 严重超标。

**根因**: 风格维度缺失"内容品类"（genre）和"叙事意图"（narrative_intent）两层正交分类，导致 1 种 preset 强行覆盖所有视频类型。

**v0.7 升级方案** — 5 种品类化预设矩阵（M2a-fix.2 → M2a-fix.3 实施）:

| Preset | 名称 | 默认 genre | 默认 tone | 默认 narrative_intent | 实施里程碑 |
|---|---|---|---|---|---|
| `movie_summary` | 电影/电视剧速览 | 电影/电视剧 | 温和讲解 / 冷静客观 | 剧情速览 | M2a-fix.2 (Day 1) |
| `shortdrama_推流` | 短剧推流 | 短剧 | 紧张悬念 | 吐槽点评 / 情绪共鸣 | M2a-fix.3 (Day 2) |
| `anime_情绪` | 动漫情绪向 | 动漫 | 燃向激昂 / 俏皮幽默 | 情绪共鸣 | M2a-fix.3 (Day 2) |
| `tv_追更` | 电视剧追更（M4+） | 电视剧 | 俏皮幽默 / 紧张悬念 | 吐槽点评 / 信息盘点 | M4 预留 |
| `movie_roast` | 电影吐槽（M4+） | 电影 | 俏皮幽默 | 吐槽点评 | M4 预留 |

**MVP 阶段实施**: 仅前 3 个（movie_summary / shortdrama_推流 / anime_情绪），后 2 个（tv_追更 / movie_roast）记入 M4 预留范围。

**与 P1-1 原 3 preset 的关系**:
- `plot_summary` → 重命名为 `movie_summary`（语义更准确，对应 X 分钟看电影品类）
- `humor_roast` → 拆分为多个 preset 的 `tone='俏皮幽默'` + `narrative_intent='吐槽点评'`组合（不再独立 preset）
- `serious_review` → 暂缓（M4+ 视用户需求决定，目前定位偏 hardcore 影评受众较窄）

**详细实施规约**: 见 `docs/plans/tasks/M2a-fix-narrative-style.md` §M2a-fix.2/.3，本里程碑 6.6d 工时实现 movie_summary + shortdrama_推流 + anime_情绪 三种 + R1-R6 反模式 hard gate（见本文档 §17.6 两阶段 LLM 设计）。

---

### 17.2 AI 自评分 + 一键重生成（用户体验保底）

**Status**: New (P1-2, proposed by Eve)

**触发原因**：剪映打开看到烂稿子，用户不会"自己改"，只会"弃用产品"。MVP 必须有质量保底机制。

**自评分实现**（在 Scripting 末尾追加）：

```python
def self_evaluate(timeline: Timeline, plot_outline: list) -> dict:
    """
    用 LLM 给自己生成的解说稿打分（4 维度，每维 1-5 分）。
    """
    prompt = f"""
    评估以下解说稿质量（每维度 1-5 分）：
    1. 剧情完整性：覆盖原片关键节点的程度
    2. 叙事连贯性：句子之间逻辑流畅度
    3. 风格一致性：与目标风格 "{style}" 的契合度
    4. 二创视角：是否有总结/点评，避免逐字复述
    
    解说稿：{timeline.full_text()}
    剧情骨架：{plot_outline}
    
    返回 JSON: {{"plot_completeness": 1-5, "narrative_coherence": 1-5,
                "style_consistency": 1-5, "creative_perspective": 1-5,
                "overall": 1-5, "issues": ["问题1", "问题2"]}}
    """
    return llm_call(prompt)
```

**Web UI 集成**：
- 任务详情页显示评分卡（4 维度雷达图 / 进度条 + issues 列表）
- 评分 < 3.5 时自动标红，附"重新生成"按钮
- 重新生成时附带"上次的 issues"作为反向指令（"避免上次出现的问题：xxx"）

**工程量**：评分函数 0.5d + Web UI 0.5d = **1d 总计**（M4）。

---

### 17.3 DraftExporter 第二实现：JsonTimelineExporter（防御性设计）

**Status**: New (P1-3, proposed by Rao)

**触发原因**：pyJianYingDraft 是单人维护的开源库 + 剪映在加密草稿格式，**单点依赖是炸弹**。MVP 必须有第二个 exporter 实现作为防御。

**新接口契约**：

```python
class DraftExporter(ABC):
    @abstractmethod
    def export(self, timeline: Timeline, video_path: Path,
               output_dir: Path) -> Path: ...
    
    @abstractmethod
    def supports_jianying_version(self) -> tuple[str, str] | None:
        """返回 (min, max) 版本号；None 表示与剪映无关"""

class JianyingDraftExporter(DraftExporter):  # 主方案
    """生成剪映草稿包"""
    def supports_jianying_version(self) -> tuple[str, str]:
        return ("5.0", "5.9")

class JsonTimelineExporter(DraftExporter):  # 防御方案
    """生成通用 JSON 时间线（含 EDL 风格的片段列表 + 解说音轨 wav 引用）
    
    格式参考行业 EDL（Edit Decision List），可被未来的 Premiere/FCP/达芬奇导入器消费。
    MVP 阶段仅作为"剪映方案崩了"时的兜底——用户至少能拿到所有素材+解说稿+时间戳，
    手动在任意剪辑软件里重建。
    """
    def supports_jianying_version(self) -> None: return None
```

**Web UI 集成**：上传时增加"输出格式"选项（默认剪映，下拉可选 JSON Timeline）。

**工程量**：JsonTimelineExporter ≈ **1d**（M3，与 JianyingDraftExporter 并行）。

---

### 17.4 数据模型统一：引入 TimelineSegment 中间层

**Status**: Supersedes Part I §6 partial (resolves §6 vs §14 time representation conflict)

**触发原因**：架构师 Rao 指出 §6 的 `ClipBinding.use_start_sec/use_end_sec`（"原片裁剪起止"）与 §14 剪映 `target_timerange`（"在最终时间线上的位置"）+ `source_timerange`（"在素材中的位置"）是两套概念，落地必然要做映射层。MVP 应该一次到位。

**统一模型（修订 §6 ClipBinding）**：

```python
class TimelineSegment:  # 新增中间层（统一概念）
    """一个"时间线片段"——同时承载源时间和目标时间两套时间表示"""
    id: str
    sentence_id: str
    shot_id: str                        # 关联的 Shot
    order: int                          # 在 sentence 内的顺序
    
    # === 源时间（在原视频中） ===
    source_start_sec: float             # 替代原 use_start_sec
    source_end_sec: float               # 替代原 use_end_sec
    
    # === 目标时间（在最终成片时间线中） ===
    target_start_sec: float             # 该片段在成片中的起始时刻
    target_end_sec: float               # 该片段在成片中的结束时刻
    
    # === 元数据 ===
    duration_sec: float                 # = end - start（两套必须相等，作为 invariant）
    rationale: str | None               # AI 给出的"为什么选这个镜头"理由
    use_original_audio_volume: float = 0.15  # 原音音量（M3-b 标记为 1.0）

# 弃用：ClipBinding 改名为 TimelineSegment，含义保留但字段重命名
# 弃用：sentence.start_sec_in_timeline 改为 derived（= 第一个 TimelineSegment.target_start_sec）
```

**好处**：
- pyJianYingDraft 的 `target_timerange / source_timerange` 1:1 映射，**无需中间转换层**
- 未来 JsonTimelineExporter / Premiere XML 导出器都用同一套字段
- 解说音轨同样用 TimelineSegment 表示（source = TTS wav 偏移 / target = 成片时间）

**迁移成本**：MVP 阶段未写代码，**纯 schema 调整，零迁移**。

**v0.6 修订（adhoc self-review, 2026-05-05）— `target_duration_sec_estimate` 中间字段补充**：

M2a baseline（HINT_UNIFORM 绑定）阶段，TimelineSegment 的 `target_start_sec` / `target_end_sec` / `duration_sec` 三个 target-side 字段无法直接计算（TTS 还没跑、单句实际播放时长未知）。为避免 timeline.json 在 M2a 阶段缺少 target 信息（M3.2/M3.3 拿到"96s 原片素材"却不知该裁成几秒），引入中间字段：

| 阶段 | 字段 | 含义 | 计算方式 |
|---|---|---|---|
| **M2a baseline** | `target_duration_sec_estimate: float`（**新增中间字段，序列化层填**） | 按字数加权预估的目标播放时长占位 | `(len(sentence_text) / total_chars) × state.target_duration_sec` |
| **M3.2 TTS 实跑后** | `target_duration_sec: float`（**真值，回填**） | TTS 实际产出的音频时长 | `librosa.get_duration(tts_wav)` 或 TTS API 返回值 |
| **M3.3 Assembly 适配后** | `target_start_sec` / `target_end_sec`（**真值，最终值**） | 在最终成片时间线上的精确起止时刻 | 累加 + ±20% 时长适配后输出 |

**字段演化不变量**：
- M2a 阶段：`sum(seg.target_duration_sec_estimate for all segs) == state.target_duration_sec`（浮点累加误差 < 0.01s）
- M3.2 阶段：`target_duration_sec_estimate` 字段保留为 audit（可与真值对比衡量字数加权估算偏差），不删除
- M3.3 阶段：`target_end_sec - target_start_sec == target_duration_sec`（invariant）

**为什么不在 M2a 一步到位计算 `target_duration_sec`**：
- TTS 实际产出受语速/音色/标点影响，估算 ±5-15% 不可避免；用 `_estimate` 后缀明示"占位、会被改写"是最干净的语义
- M2a 算法层（`bind_naively`）的 `BoundSegment` dataclass **不感知"目标时长"** 这个产品概念——`target_duration_sec_estimate` 仅在 M2a.6 序列化层补充，避免污染算法层职责
- 详见 `docs/plans/tasks/M2a-scripting-main.md` §M2a.5 / §M2a.6 v0.6 修订段

---

**v0.7 修订（M2a-fix C5 数据契约，2026-05-05）— `(genre, narrative_intent) → preset` fallback 矩阵**：

为支撑 §17.6 两阶段 LLM 的兜底路径（第 1 次调用推断 `genre + tone + narrative_intent`，第 2 次按推荐 preset 写文案），需要一份显式的 `(genre, narrative_intent) → preset` 映射表。当 LLM 推断出的组合无对应专属 preset 时，按此表回退到最近邻 preset。

**fallback 矩阵**（10 genre × 5 narrative_intent = 50 格，去重后实际 14 唯一映射）:

| genre \ narrative_intent | 剧情速览 | 吐槽点评 | 情绪共鸣 | 信息盘点 | 其他 |
|---|---|---|---|---|---|
| 电影 | movie_summary | movie_summary | anime_情绪 | movie_summary | movie_summary |
| 电视剧 | movie_summary | movie_summary | anime_情绪 | movie_summary | movie_summary |
| 动漫 | anime_情绪 | anime_情绪 | anime_情绪 | movie_summary | anime_情绪 |
| 短剧 | shortdrama_推流 | shortdrama_推流 | shortdrama_推流 | shortdrama_推流 | shortdrama_推流 |
| 综艺 | movie_summary | shortdrama_推流 | anime_情绪 | movie_summary | movie_summary |
| 电竞 | movie_summary | shortdrama_推流 | anime_情绪 | movie_summary | movie_summary |
| 教学 | movie_summary | movie_summary | movie_summary | movie_summary | movie_summary |
| Vlog | movie_summary | movie_summary | anime_情绪 | movie_summary | movie_summary |
| 纪录片 | movie_summary | movie_summary | movie_summary | movie_summary | movie_summary |
| 其他 | movie_summary | movie_summary | movie_summary | movie_summary | movie_summary |

**矩阵设计原则**:
- **MVP 阶段只有 3 个真实 preset**（movie_summary / shortdrama_推流 / anime_情绪），矩阵每格必须落到这 3 个之一
- **`movie_summary` 是默认兜底**（覆盖 25 格）：温和讲解 + 客观叙述风险最低，不易冒犯任何品类
- **`shortdrama_推流` 适用范围**: 仅短剧（强相关）+ 综艺/电竞的吐槽点评（高节奏强反转场景）
- **`anime_情绪` 适用范围**: 动漫全意图 + 影视/Vlog 的情绪共鸣（需要"哭一场"或"燃起来"）
- **教学 / 纪录片 / 其他**: 全部走 movie_summary（这 3 类与 anime_情绪 / shortdrama_推流 调性冲突）

**静态默认三元组（F1，失败兜底）**:
- 当第 1 次 LLM 调用失败 / 输出非合法枚举值 / 网络异常时，使用 `{genre='其他', tone='温和讲解', narrative_intent='剧情速览'}`
- 经查表 `(其他, 剧情速览) → movie_summary`
- **justification**：温和讲解 tone 在所有调性中冒犯风险最低（俏皮幽默 / 燃向激昂在错误内容上极易翻车）；剧情速览 narrative_intent 是最常见的二创场景；其他 genre 触发"通用兜底"语义

**M4+ 扩展规则**: 新增 preset（如 `tv_追更` / `movie_roast`）时，本矩阵需同步更新对应行/列；M2a-fix.4 阶段冻结此矩阵作 schema invariant。

---

### 17.5 测试策略（核心算法必须有测试）

**Status**: New (P1-5, proposed by Rao)

**触发原因**：1419 行设计文档零行 testing。跨 5 模块 + 10+ 外部依赖的系统，没测试 = 上线即下线。

**MVP 测试金字塔**：

```
         ┌────────────────────┐
         │  E2E 测试（1 个）   │  ← 1 部精选短片端到端跑通（M4）
         └────────────────────┘
       ┌──────────────────────────┐
       │  集成测试（5-8 个）       │  ← 每模块 1-2 个，用 fixture 数据
       └──────────────────────────┘
   ┌────────────────────────────────────┐
   │  单元测试（30-50 个）                │  ← 核心算法 + 数据模型 + Provider mock
   └────────────────────────────────────┘
```

**重点覆盖（must-have）**：

| 模块 | 测试类型 | 覆盖点 |
|---|---|---|
| **Scripting 绑定算法** | 单元 + 集成 | resolve_time_for_sentence / greedy_assign / fallback / KPI 评估脚本 |
| **Assembly 时长适配** | 单元 | TTS 时长 vs 镜头时长 4 种边界 case（等于 / 长 / 短 / 极短） |
| **JianyingDraftExporter** | 集成 | 生成草稿能被 pyJianYingDraft 自身的 loader 重新加载（schema 自洽） |
| **零知识架构** | 集成 | 任务完成后 raw 文件确实被删除；草稿包不含原片绝对路径 |
| **Provider 接口** | 单元（mock） | LLM/TTS/ASR 接口契约测试，不真调用 API |

**工程量**：测试代码约占主代码 30-40%，约 **3-4 天**（分布在 M1-M4 各阶段）。

**CI 配置**：MVP 用 GitHub Actions 跑 unit + integration（不跑 E2E，因为依赖外部 API），E2E 仅本地手跑。


---

### 17.6 二创风格修正：两阶段 LLM + 三层封闭枚举（M2a-fix v0.7）

**Status**: New (M2a-fix milestone, 2026-05-05; brainstorming Q1-Q8 + 8 角度 critique 19 项 P0 修正共识结果)

**触发原因**: M2a baseline (commit eecab0f) 端到端跑 `job_20260505_144455` 暴露 R5 第三人称冷叙述命中率 100%、缺二创视角；根因为缺少"内容品类 → 调性 → 叙事意图"的三层正交分类，单一 plot_summary preset 无法覆盖动漫/短剧/Vlog 等非影视品类。

**核心设计**:

#### (1) 三层封闭枚举集（C1-C4 数据契约）

**`genre`（10 值，覆盖二创视频所有内容品类）**:

| 枚举值 | 50 字描述符 | 典型示例 |
|---|---|---|
| 电影 | 院线/网络长片，单一完整叙事，时长 90+ min；解说节奏偏舒缓深度 | 流浪地球 / 让子弹飞 |
| 电视剧 | 多集连续叙事，单集 30-60 min；解说常按集数推进或抓人物线 | 漫长的季节 / 狂飙 |
| 动漫 | 含番剧/国漫/动画电影，强情绪表达 + ACG 受众文化背景 | 鬼灭之刃 / 中国奇谭 |
| 短剧 | 竖屏 1-3 min/集，强反转节奏，付费引导/抖快推流场景 | 霸总短剧 / 战神短剧 |
| 综艺 | 真人秀/访谈/竞演节目，多 MC 互动，亮点是金句和"名场面" | 脱口秀大会 / 向往的生活 |
| 电竞 | 赛事录像/职业选手集锦，节奏快、术语密集，观众有强参与感 | LPL S 赛 / DOTA 国际邀请赛 |
| 教学 | 知识科普/教程/课程，以信息传递为目的，受众主动学习 | 老高小茉 / B 站学习区 |
| Vlog | 创作者第一视角生活记录，无强叙事弧，调性松弛 | 影视飓风 / 旅行 Vlog |
| 纪录片 | 真实事件/历史/自然题材，调性偏严肃克制 | 河西走廊 / 蓝色星球 |
| 其他 | 上述未覆盖的内容（如直播切片/短视频混剪/MV），走默认兜底 | 未分类 |

**`tone`（7 值，正交于 genre 的语气调性）**:

| 枚举值 | 50 字描述符 | 典型 UP 主参考 |
|---|---|---|
| 温和讲解 | 第三人称客观叙述，无强情绪起伏，信息密度均匀；最不易冒犯，默认兜底 | 早期"X 分钟看电影"风 |
| 俏皮幽默 | 网络化表达 + 适度自嘲/抖机灵，节奏轻快；适合短剧/综艺/部分动漫 | 谷阿莫早期 |
| 紧张悬念 | 多用反问/省略号/反转句式，营造"接下来会发生什么"的钩子感 | 短剧推流剪辑 |
| 克制深沉 | 长句为主，留白多，避免感叹号；适合纪录片/严肃题材 | 木鱼水心 |
| 燃向激昂 | 短句密集 + 大量感叹号，情绪 1:1 放大；动漫战斗场面/电竞高光首选 | LexBurner / 阿斗归来了 |
| 冷静客观 | 类似温和讲解但更"中立"，多用数据/时间线引述；适合教学/纪录片 | 半佛仙人 |
| 其他 | 上述未匹配的特殊调性，回退到温和讲解 | — |

**`narrative_intent`（5 值，用户视角的"为什么要二创这条视频"）**:

| 枚举值 | 50 字描述符 | UX 按钮文案 |
|---|---|---|
| 剧情速览 | 浓缩主线剧情，让没看过原片的观众快速了解；最常见 MVP 场景 | 📖 速览 / X 分钟看完 |
| 吐槽点评 | 带创作者视角的评论，含吐槽/反差观察/金句，强个人风格 | 🎤 吐槽 / 边看边喷 |
| 情绪共鸣 | 烘托情绪氛围（燃/泪/治愈），适合 MV 化二创和动漫"名场面"切片 | 💖 情绪 / 燃哭/治愈 |
| 信息盘点 | TopN 排行/盘点合集格式，信息密度高节奏快 | 📊 盘点 / Top10 / 合集 |
| 其他 | 用户暂未确定意图，走 LLM 自动推断 | 🎲 自动选择（默认） |

#### (2) 两阶段 LLM 设计

```
┌─────────────────────────────────────────────────────────┐
│ Stage 1: Genre/Tone/Intent Inference (轻量, ~3s, 缓存)  │
│ Input: plot_outline_json (M2a-fix.2 实现)                │
│ Output: {genre, tone_recommendation, narrative_intent}   │
│         三个枚举值 + 50 字 reasoning                     │
│ Failure → 静态默认三元组 F1                              │
└──────────────────────┬──────────────────────────────────┘
                       │ (查 §17.4 fallback 矩阵)
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Stage 2: Narrative IR Generation (重量, ~25s, 不缓存)   │
│ Input: plot_outline + 选中的 preset + (genre, tone, intent) │
│ Output: narrative_ir.paragraphs[].sentences[].text       │
│ Hard gate: K-style-1 R1-R6 命中率 ≤ 10%                  │
│ Failure → 重试 1 次 → 仍失败标记 stage FAILED            │
└─────────────────────────────────────────────────────────┘
```

**缓存策略（M2a-fix.4 实现，P3）**:
- Stage 1 缓存 key = SHA256(`plot_outline_json + style_preset + (cli_narrative_intent or '')`)
- 同 plot_outline 切换 tone 不重复推断 → 命中率 < 100ms（vs 首次 ~3s）
- Stage 2 不缓存（输出方差大，缓存意义小）

**成本分析（K8）**:
- Stage 1: ~500 input tokens + ~200 output tokens ≈ ¥0.001/次
- Stage 2: ~3000 input tokens + ~5000 output tokens ≈ ¥0.05/次
- 单次端到端 ≈ ¥0.051；缓存命中场景降至 ¥0.05（Stage 1 跳过）

**失败兜底（F1）**: 见 §17.4 末尾"静态默认三元组"；任何阶段失败都不应阻塞主链路，最差降级为 movie_summary + 温和讲解。

#### (3) R1-R6 反模式 hard gate（K-style-1）

实现 `src/autoclip/algo/style_violations.py`（M2a-fix.1，已落地）:

| ID | 反模式 | 检测方式 | M2a-fix.2 集成点 |
|---|---|---|---|
| R1 | 画面描述（"X 展示 Y 图片"） | 句级正则 | narrative_ir 后置扫描 |
| R2 | 流水账动作（"然后接着"） | 句级正则 | 同上 |
| R3 | 复读对白 | 软规则（M2a-fix.2 后续增强，需 ASR text 上下文） | 暂占位 |
| R4 | 客观零情绪 | 段落级（≥6 句无 [！？] 且无情绪词） | 同 R1 |
| R5 | 第三人称冷叙述 | 句级正则（"主持人/角色 + 陈述动词"开头） | 同 R1 |
| R6 | 缺二创视角 | 段落级（无吐槽词/反差词） | 同 R1 |

**hard gate 规则**: `hit_rate = 命中反模式句数 / 总句数 ≤ 10%`；超过则 stage FAILED + 1 次重试机会（M2a-fix.2 实现）。

**v0.7 修订（M2a-fix v0.7.1 P0 补强）**: 详细任务拆解见 `docs/plans/tasks/M2a-fix-narrative-style.md`，5 子任务 6.6d 工时实现。

---

### 17.7 UX 4 意图按钮规约（M2a-fix v0.7，M3.7 Web UI 实施）

**Status**: New (M2a-fix milestone, U1/U2 修正项)

**触发原因**: U1 修正提出"露 4 意图按钮（narrative_intent 是否预填的开关），自动选择为默认且最显眼"。本节为 M3.7 Web UI 实施提供完整规约（本里程碑只规约不实现）。

**4 意图按钮设计**:

| 按钮位置 | 主文案 | 副文案（hover 显示） | 对应 narrative_intent | 视觉权重 |
|---|---|---|---|---|
| 第 1 位（最显眼） | 🎲 **自动选择**（默认选中） | 让 AI 看完视频后自己决定（推荐） | 不预填，走 LLM 推断 | **主按钮**（高亮 + 放大 1.2x + 默认 selected 状态） |
| 第 2 位 | 📖 **速览** | X 分钟看完，浓缩剧情主线 | `narrative_intent='剧情速览'` | 普通按钮 |
| 第 3 位 | 🎤 **吐槽** | 带个人风格的评论，边看边喷 | `narrative_intent='吐槽点评'` | 普通按钮 |
| 第 4 位 | 💖 **情绪** | 烘托燃/泪/治愈氛围 | `narrative_intent='情绪共鸣'` | 普通按钮 |
| 第 5 位 | 📊 **盘点** | TopN/合集风格，信息密度高 | `narrative_intent='信息盘点'` | 普通按钮 |

**交互行为**:
- **默认状态**: "自动选择"按钮选中（蓝色背景），其他 4 个按钮为 outline 灰边
- **单选**: 5 个按钮互斥，点击切换；提交时把选中的 narrative_intent 通过 CLI/API 传给 dispatcher
- **hover 提示**: 副文案 + 1 张示例图占位（M3.7 实施时填真实示例图，本规约只占位）
- **移动端折叠**: 5 按钮在窄屏（< 480px）下水平滚动，"自动选择"始终首位置且 sticky

**API/CLI 契约（M2a-fix.4 实现）**:
- CLI 入参: `--narrative-intent {自动选择|剧情速览|吐槽点评|情绪共鸣|信息盘点|盘点|...}`
- "自动选择"传值时不写入 state.json `narrative_intent` 字段（保留 None），由 Stage 1 LLM 推断
- 其他 4 值传值时直接写入 state.json，Stage 1 LLM 仍跑（推断 genre + tone）但 narrative_intent 用 CLI 预填值

**与 §17.6 fallback 矩阵的协同**:
- 用户选 "📖 速览" + LLM 推断 genre='动漫' → 查矩阵 `(动漫, 剧情速览) → anime_情绪`
- 用户选 "🎲 自动选择" → LLM 推断完整 (genre, narrative_intent) → 查矩阵选 preset

**M3.7 实施任务清单**（doc-only，本里程碑不实施）:
- [ ] 5 个按钮组件（React/Vue 任选，遵循现有 UI 库）
- [ ] hover 提示组件 + 5 张示例图占位（图待 M3.7 设计师补）
- [ ] 移动端响应式（≥ 320px 兼容）
- [ ] 选中状态持久化到 localStorage（用户下次打开记住偏好）
- [ ] A/B 测试钩子（统计 4 个非默认按钮的点击占比，反推用户真实偏好）

---

## 18. P2 修订（2 项 — 必须有，但可最简实现）

### 18.1 用户协议草稿 v0.1

**Status**: New (P2-1, proposed by Wu)

**触发原因**：法律顾问 Wu 强调"用户协议必须随 MVP 一起交付，不能等以后"。MVP 自用阶段也必须有勾选拦截，否则未来商业化无法主张"用户已知情同意"。

**实现方式**：
- 文件位置：`docs/legal/user-agreement-v0.1.md`（独立于 design.md，便于法务后续编辑）
- Web UI 集成：上传页底部显示协议摘要 + checkbox + 完整协议链接（弹窗显示），未勾选则提交按钮 disabled

**协议核心条款（v0.1 草稿要点，最终版需法务过审）**：

| 条款 | 要点 |
|---|---|
| 1. 工具性质声明 | AutoClip 是创作辅助工具，不审核用户上传内容的版权归属 |
| 2. 用户责任 | 用户保证对上传视频拥有合法使用权（自有版权 / 已获授权 / 属于合理使用范围） |
| 3. 输出物归属 | 解说稿和剪映草稿的著作权归用户所有，AutoClip 不主张任何权利 |
| 4. 数据处理 | 临时数据 24h 内删除；元数据保留 30 天；用户可随时申请完全清除 |
| 5. 使用限制 | 仅供个人创作研究使用；商业发布前用户应自行评估版权风险 |
| 6. 责任豁免 | 用户因使用 AutoClip 产出物而引发的版权纠纷，由用户自行承担 |
| 7. 争议解决 | （MVP 自用阶段从简，商业化前需重写） |

**工程量**：协议文件 0.5d + 勾选拦截 0.25d = **0.75d**（M3）。

---

### 18.2 MVP 验收 KPI 量化

**Status**: Supersedes Part II §15.1 verification criteria (loose "看得过去")

**触发原因**：原验收标准"自己看得过去"是模糊判断，无法证明 MVP 真的可用。算法工程师 Lin 和产品经理 Eve 共同要求量化。

**MVP 完整验收 KPI 矩阵**：

| 维度 | 指标 | 目标值 | 评估方法 | 责任 |
|---|---|---|---|---|
| **算法质量** | 绑定准确率 | ≥ 70% | 3 部作品各 50 句人工打标 | M2b 验收 |
| **算法质量** | evidence 召回率 | ≥ 80% | 自动统计 LLM 输出非 null 比例 | M2b 验收 |
| **算法质量** | fallback 触发率 | ≤ 30% | 自动统计 resolve 返回 None 比例 | M2b 验收 |
| **产品体验** | 用户主观评分 | ≥ 4/5 | 自评 + 1-2 个真实创作者朋友盲评 3 部成品 | M4 验收 |
| **产品体验** | 人工调优时间 | ≤ 1 小时/部 | 在剪映里调到"愿意发布"水平的时长 | M4 验收 |
| **工程质量** | 端到端耗时 | ≤ 16 min/90min电影 | 自动计时 | M4 验收 |
| **工程质量** | 任务可恢复性 | 子进程 kill 后重启可 resume | 集成测试 | M3 验收 |
| **工程质量** | 单元测试覆盖率 | 核心算法 ≥ 70% | pytest --cov | M2b/M3/M4 持续 |
| **合规质量** | 任务完成后 raw 文件已删除 | 100% | 集成测试 | M3 验收 |
| **合规质量** | 草稿包不含原片绝对路径 | 100% | 集成测试 + 人工抽检 | M3 验收 |
| **合规质量** | 用户协议勾选拦截 | 未勾选不可提交 | 集成测试 | M3 验收 |

**KPI 不达标的处理**：
- P0 KPI（算法质量 + 合规质量）任一不达标 → MVP **不发布**，回炉到对应 milestone 调优
- P1 KPI（产品体验 + 工程质量）部分不达标 → 评估影响范围，必要时延长 Week 6 buffer 修复

---

## 19. v0.3 总览（修订汇总 + 新版决策矩阵 + 新版工期）

### 19.1 v0.1 → v0.2 → v0.3 演进总表

| 演进 | 触发 | 核心变化 | design.md 范围 | MVP 工期 |
|---|---|---|---|---|
| **v0.1** | Brainstorming 收敛 | 10 项决策落地，FFmpeg 出片 + 自建编辑器 | §1-§12（行 1-1003） | 4 周 |
| **v0.2** | 用户神来一笔"能不能放剪映" | 颠覆为剪映草稿模式 + 极简状态页 | §13-§15（行 1004-1419） | 3 周 |
| **v0.3** | 4 角色多角度评审 | 12 项修订（5 P0 + 5 P1 + 2 P2） | §16-§19（行 1420-end） | **5-6 周** |

### 19.2 v0.3 最终决策矩阵（覆盖前两版）

| 维度 | 最终选择 | 决策来源 |
|---|---|---|
| 场景 | A1 影视/电视剧/动漫二创 | v0.1 Q1 |
| 定位 | B 创作助手 | v0.1 Q3 |
| 输入 | 单视频 | v0.1 Q4 |
| 索引模态 | a 镜头切分 + b ASR + d VLM 按需 | v0.1 Q5 修正 |
| 剪辑哲学 | Z 混合策略 | v0.1 Q5 |
| 文稿粒度 | P3 双层结构（MVP 跑句子层） | v0.1 Q6 |
| 解说音轨 | V1 纯 TTS | v0.1 Q7 |
| 混音策略 | M3-c 终态，MVP 实做 M2 + M3-b | v0.1 Q8 拆分 |
| 时长档位 | T1 (3-5min) 优先 → T2 演进 | v0.1 Q9 |
| 验收级别 | S1 Demo 级 | v0.1 Q10 |
| **最终输出** | **剪映草稿包**（pyJianYingDraft） | v0.2 ADR-008 |
| **第二输出** | **JsonTimelineExporter**（防御） | v0.3 P1-3 |
| 前端 | 极简 Web 4 页面（Jinja + Tailwind） | v0.2 ADR-007 修订 |
| LLM | 通义千问 qwen-plus | v0.1 ADR-001 |
| **ASR** | **阿里云智能语音转写** | v0.3 ADR-004 再修订 |
| 镜头切分 | PySceneDetect ContentDetector | v0.1 ADR-003 |
| TTS | 火山豆包语音 API | v0.1 ADR-002 |
| 存储 | SQLite + 本地文件 | v0.1 ADR-005 |
| **任务执行** | **multiprocessing + 文件状态机** | v0.3 ADR-006 修订 |
| **绑定算法** | **narrative IR + post-validation** | v0.3 §16.3 重写 |
| **合规架构** | **零知识架构**（raw 24h 删除 + 草稿不含原片） | v0.3 §16.5 |
| **风格预设** | **3 种 + few-shot** | v0.3 P1-1 |
| **质量保底** | **AI 自评分 + 一键重生成** | v0.3 P1-2 |
| **数据模型** | **TimelineSegment 统一中间层** | v0.3 P1-4 |
| **测试策略** | **金字塔（30+ 单元 + 5-8 集成 + 1 E2E）** | v0.3 P1-5 |
| **用户协议** | **v0.1 草稿 + 勾选拦截** | v0.3 P2-1 |
| **验收 KPI** | **量化 11 项指标** | v0.3 P2-2 |

### 19.3 v0.3 最终路线图速览（5-6 周 / 4 milestones）

```
Week 1   Week 2     Week 3      Week 4         Week 5   Week 6 (buffer)
├── M1 ─┼── M2a ───┼── M2b ────┼── M3 ────────┼── M4 ──┼─────────────┤
基础设施  Scripting   Scripting    Render+合规     E2E +     KPI 验收 +
+Ingest   主链路       鲁棒性       +Web           风格扩展   修复
+Index                (narrIR)                    +自评分
```

### 19.4 v0.3 关键工程量增量（vs v0.2）

| 项 | 工程量 |
|---|---|
| narrative IR + post-validation 算法升级 | +5d（M2b 新增） |
| 零知识架构（合规） | +2d（M3） |
| multiprocessing + 文件状态机 | +2d（M1） |
| 风格预设 3 种 + few-shot | +3d（分布 M2b/M4） |
| AI 自评分 + 重生成 | +1d（M4） |
| JsonTimelineExporter（防御） | +1d（M3） |
| 测试代码（单元+集成） | +3-4d（分布全程） |
| 数据模型 TimelineSegment 重构 | +0.5d（M1，纯 schema） |
| 用户协议 + 勾选拦截 | +0.75d（M3） |
| ASR 切阿里云 | +0.5d（M1，仅 SDK 替换） |
| **总计增量** | **~19 工作日 ≈ 4 周 →** **从 3 周 → 5-6 周** |

### 19.5 v0.3 风险评估更新（增量风险）

| # | 新增风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R10 | narrative IR 升级后 LLM 仍幻觉 evidence | 🟡 中 | 🔴 高 | post-validation 反向校验兜底；fallback 到段落均分 |
| R11 | 阿里云 ASR 长视频接口限速 | 🟢 低 | 🟡 中 | 90min 拆 3 段并行；失败重试 |
| R12 | multiprocessing 在 macOS spawn 模式下模型加载慢 | 🟡 中 | 🟢 低 | 子进程内独立加载；进程池复用 |
| R13 | 零知识架构导致 resume 失效 | 🟢 低 | 🟡 中 | v1.1 用户上传 hash 跳过 Ingest |
| R14 | KPI 不达标导致 MVP 延期 | 🟡 中 | 🟡 中 | Week 6 buffer 兜底；P0 KPI 严守，P1 KPI 可让步 |

> 原 §10 R1-R9 风险条目继续生效，本节为增量补充。

---

## 20. 文档导航（v0.3 完整版）

| 阶段 | 章节 | 状态 |
|---|---|---|
| **Part I — v0.1 初稿** | §1-§12（行 1-1003） | 历史保留，部分被覆盖 |
| **Part II — v0.2 剪映对接** | §13-§15（行 1004-1419） | 部分有效，§15 被 §16.4 覆盖 |
| **Part III — v0.3 多角度评审** | §16-§19（行 1420-end） | **当前最新，最高优先级** |

**冲突时的优先级**：v0.3 > v0.2 > v0.1（后写后准）

**需要重读哪些章节**：
- 算法相关 → §16.3（绑定算法）+ §17.4（数据模型）
- 工期/路线图 → §16.4（路线图）+ §19.3
- 合规/法律 → §16.5（零知识架构）+ §18.1（用户协议）
- 验收标准 → §18.2（KPI 矩阵）
- 体验保障 → §17.1（风格预设）+ §17.2（自评分）
- 工程基础 → §16.2（multiprocessing）+ §17.5（测试策略）


---

# Part IV — v0.4 本地化与角色推断修订（2026-05-04 15:20）

> **变更触发**：用户在 M1.5 启动前提出两个核心诉求 — (1) 阿里云 ASR 需要先上传 OSS 太麻烦，要求**纯本地方案**；(2) MVP 阶段需要**让 LLM 知道角色信息**以提升解说稿质量（"男主对女主说..."而非"有人说..."）。
>
> **变更原则**：保留 Part I/II/III 全部章节不删；通过 §21-§22 增量覆盖 ADR-004 与 §8.2.2、§8.3.2；阅读时以 Part IV 为最高优先级。
>
> **决策来源**：本次 brainstorming 收敛过程见 `.context/chat.md` Session 4。
>
> **冲突时优先级**：v0.4 > v0.3 > v0.2 > v0.1（后写后准）

---

## 21. P0 修订（2 项）

### 21.1 ADR-004 三度修订：ASR 默认改为本地 faster-whisper + large-v3

**Status**: Supersedes Part III §16.1 ADR-004 (Aliyun NLS) AND Part II §13 ADR-004 (OpenAI Whisper API)

**触发原因**：
1. 用户明确反对阿里云 ASR 的 5 步 OSS 流水线（上传 OSS → SubmitTask → 轮询 → DELETE），认为对单机本地工具链过度复杂
2. 开发机为 **Apple M3 Pro / 36GB / arm64**，本地 ASR 性能完全够用（实测 large-v3 实时率 4-5x，90min 电影约 12-18min）
3. 本地方案天然满足零知识架构 K9/K10（音频从未离开本地）

**新决策**：MVP 默认 **`faster-whisper` + `large-v3` 模型本地推理**；保留 `ASRProvider` 抽象基类不变，仅替换默认实现为 `LocalWhisperProvider`。

**Consequences**：
- ✅ 零网络依赖、零云服务凭证、零计费
- ✅ 零知识架构强化：原音频文件**从未离开本地**（vs Aliyun 方案需短暂上传 OSS）
- ✅ 跨平台兼容（CPU / CUDA / Metal 都跑）；未来若需上声纹兜底，可平滑切换 WhisperX
- ✅ 集成成本低：M1.5 工期从 1d 降为 0.5d
- ✅ 中文 WER 8-12%（large-v3）— 对下游 LLM 剧情理解任务足够（vs 阿里云 5-10% 的优势在 LLM 容错下感知不强）
- ❌ 首次模型下载约 3.1GB（HF mirror 国内可达）；CI 环境需缓存模型权重
- ❌ 90min 推理 12-18min（vs 阿里云云端 ~5-10min），但**无网络抖动 / 无配额限制 / 无重试逻辑**，总体可控

**MVP 实现**：
- `ASRProvider` 抽象基类不变（`transcribe(audio_path, language) -> ASRResult`）
- 默认实现 `LocalWhisperProvider`，构造参数：`model_size="large-v3" / device="auto" / compute_type="default"`
- `model_size` 候选：tiny / base / small / medium / large-v3（MVP 默认 large-v3）
- `device="auto"` 自动检测 cuda → mps → cpu（faster-whisper 1.x 起原生支持）
- `compute_type` 默认 `"default"`（按 device 自动选 int8/float16/float32）
- 模型加载使用 lazy initialization + module-level 单例（避免子进程内重复加载）
- 移除 `oss2` / `alibabacloud-nls-python-sdk` / `aliyun_asr_token` / `aliyun_asr_app_key` 配置项
- 新增 Settings：`whisper_model_size` / `whisper_device` / `whisper_compute_type`

**Alternatives Reconsidered**：
- **mlx-whisper**：M3 Pro 速度更快（3-6min/90min），但锁死 Apple Silicon，未来 Linux 部署需切换 → **否决**
- **FunASR / Paraformer-large**：中文 WER 5-8% 略优，但依赖重（torch + modelscope ~2GB+）、Python 3.13 兼容性未验证 → **暂不考虑**
- **WhisperX**：自带 diarization 集成，但 MVP 不做声纹（见 §22）→ **保留为未来升级路径**

---

### 21.2 §8.2.2 ASR 子模块改写（本地版伪代码）

**Status**: Supersedes Part I §8.2.2 (Whisper local v0.1) AND Part III implicit aliyun pseudocode

```python
# 伪代码 — LocalWhisperProvider
from faster_whisper import WhisperModel
from pathlib import Path

_MODEL_SINGLETON: WhisperModel | None = None

def _get_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    """Module-level singleton — 避免子进程内重复加载 3GB 模型权重."""
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        _MODEL_SINGLETON = WhisperModel(
            model_size_or_path=model_size,   # "large-v3"
            device=device,                    # "auto" → cuda/mps/cpu
            compute_type=compute_type,        # "default"
        )
    return _MODEL_SINGLETON


def transcribe(audio_path: Path, language: str = "zh") -> ASRResult:
    model = _get_model("large-v3", "auto", "default")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,        # 内置 silero VAD，过滤静音段，提速且降错
        word_timestamps=False,  # MVP 不需词级（句级足够下游绑定）
    )
    sentences = []
    for idx, seg in enumerate(segments_iter):
        if not seg.text.strip():
            continue
        sentences.append(ASRSentence(
            idx=idx,
            start_sec=float(seg.start),
            end_sec=float(seg.end),
            text=seg.text.strip(),
            confidence=float(seg.avg_logprob),
            speaker=None,            # MVP 不做声纹（见 §22）
        ))
    return ASRResult(
        sentences=sentences,
        language=info.language,
        provider="local-whisper",
    )
```

**关键约束**：
- VAD（voice activity detection）默认开启 → 90min 电影中静音段（约 30-40%）跳过推理，实际耗时 ≈ 12-18min
- `beam_size=5` 平衡质量/速度；large-v3 + beam=5 在 M3 Pro 测试下中文 WER ≈ 8%
- 模型权重缓存路径：`~/.cache/huggingface/hub/`（faster-whisper 默认）
- **失败兜底**：模型加载失败 → 降级到 `medium`（1.5GB，速度 8x 实时率）
- **后处理沿用 v0.1 §8.2.2**：合并过短片段（<1s）、过滤纯噪音段（confidence < -1.0）

**零知识架构强化（K9）**：
- 原 Part III ADR-004 K9 验证依赖"OSS object 在 transcribe 返回后已不存在"
- 改为本地后，**K9 验证简化为**："Index stage 完成后 `data/{job_id}/audio.wav` 文件已被删除"（M1.8 handler 负责）
- **音频从未离开本地** → K10（草稿不含原片路径）实质上更加彻底

---

## 22. ADR-009（新增）：MVP 角色信息走 LLM 文本推断（路径 2）

**Status**: Accepted（替换 Part I §3 第 35 行隐含决策"MVP 不做角色"）

**触发原因**：
- 用户明确希望 MVP 输出"男主对女主说..."这类带角色的解说，而非"有人说..."的含糊表达
- 但用户硬件无 GPU，MVP 工期紧（W1 已进行至 12.12%），不接受为此延长 3-4 天做声纹

**Decision**：MVP 阶段**完全不做声纹 diarization**（pyannote-audio / WhisperX 等），改用 **LLM 从对白文本推断角色** 的轻量方案：

1. **ASR 侧零改动**：`ASRSentence.speaker` 字段保持 `None`（schema 一次到位原则继续生效，未来加声纹时填充）
2. **M2a Plot Outline 增强**：在 Plot Outline 提取的 prompt 中要求 LLM 输出 `main_characters` 数组（`{role: "男主"|"女主"|"反派"|..., name?: "周星驰", description: "..."}`），并在 `key_acts.summary` 中显式标注哪些角色参与了该幕
3. **M2a 解说稿生成增强**：在 narrative IR 生成的 prompt 的 user 段落中注入 `main_characters` 上下文，要求 LLM 用角色称呼（如"男主"、"女主"、"反派 A"，**或对白中明确出现的姓名**）替代"有人"、"某人"等含糊表达
4. **不做的事**：
   - 不做声纹聚类（Speaker_00/01/02）
   - 不做角色名映射服务（"Speaker_01 = 周星驰"）
   - 不做 ASR 句级 speaker 标注（保持 `speaker=None`）

**为什么不做声纹**：
- 声纹只输出匿名 ID（Speaker_00/01/02），**仍需 LLM 映射成具名角色** → LLM 推断这一步无论如何跑不掉
- 电影场景 DER（diarization error rate）30-50%（BGM / 音效 / 重叠对白），匿名标签经常切错，**反而误导 LLM**
- LLM 通过对白内容里的"爸"/"师父"/"陛下"/"X老师" 等称呼**已经能推断 80% 的角色关系**

**Consequences**：
- ✅ MVP 工期零增加（M1.5 ASR 任务定义不变，仅 M2a prompt 微调）
- ✅ 解说稿质量提升明显（"男主对女主说..." vs "有人说..."）
- ✅ 保留升级路径：未来 M5/v1.1 可加 WhisperX diarization，把声纹聚类结果作为 LLM prompt 的额外上下文（路径 3）
- ❌ 当对白中无明确称呼/姓名时，LLM 可能仍输出"有人"（fallback 行为可接受）
- ❌ 多人混淆场景（3+ 角色对话）LLM 可能搞错"谁对谁说"（v1.1 加声纹兜底）

**关联数据模型变更**：
- `PlotOutline` 字段 `main_characters` 由 v0.3 的 `list[str]` 升级为 `list[Character]`，其中 `Character(role: str, name: str | None, description: str)`
- `KeyAct` 新增可选字段 `involved_characters: list[str]`（角色 role 列表）
- 详细 schema 见 M2a-scripting-main.md 的 M2a.2 / M2a.3 任务条目

---

## 23. 工期与 KPI 影响汇总

| 项 | 变更前（v0.3） | 变更后（v0.4） | 净影响 |
|---|---|---|---|
| M1.5 工期 | 1.0d（Aliyun OSS 5 步流水线 + tenacity + cleanup） | 0.5d（faster-whisper + 单例 + VAD） | **-0.5d** |
| M2a.2/M2a.3 prompt 设计 | 1.0d + 1.0d | 1.0d + 1.0d（仅 prompt 增强，不增工时） | 0 |
| 总工期 | 32d | 31.5d | **-0.5d** |
| K9（raw 删除） | OSS object cleanup | 本地 audio.wav cleanup | 实现更简单、更可靠 |
| K10（草稿不含原片） | 不变 | 不变（更彻底：音频从未离开本地） | 增强 |
| K8（测试覆盖） | 含 OSS mock 复杂集成 | 改为模型加载 + 假音频单测 | 测试更快、更稳 |
| R2（阿里云 ASR 限速） | 监控中 | **解除**（不再适用） | -1 风险项 |

**新增风险**：
| ID | 风险 | 概率 | 影响 | 缓解策略 |
|---|---|---|---|---|
| R15 | faster-whisper 模型权重首次下载慢/失败 | 🟡 中 | 🟡 中 | M1.5 提供 `scripts/preload_whisper.py` 预下载脚本；CI 缓存权重目录 |
| R16 | LLM 角色推断在多人混淆场景出错 | 🟡 中 | 🟢 低 | M2a.2 prompt 加 few-shot 示例；v1.1 加声纹兜底（路径 3） |
| R17 | M3 Pro 之外的低配 Mac 跑 large-v3 内存爆 | 🟢 低 | 🟡 中 | Settings 提供 model_size 配置项，文档建议低配机降到 medium |


---

## 24. ADR-010（新增）：M1.6 Ingest 改双轨 normalize（low + hd）

**触发**: 2026-05-04 v0.5 adhoc — 单轨 720p normalize 满足检测但损失出片画质（用户上传 1080p 强制降到 720p 出片不可接受）。

**决策**: Ingest 阶段产出**双轨**归一化视频（替换原单轨方案）：

| 产物 | 分辨率 / fps | 编码参数 | 用途 | 后续阶段 |
|---|---|---|---|---|
| `normalized_low.mp4` | scale=-2:720, fps=25 | libx264 crf=23 preset=medium + aac 128k + faststart | 视觉检测 / ASR 喂料 | M1.7 PySceneDetect / M1.8 ASR |
| `normalized_hd.mp4` | scale=-2:1080, 原 fps | libx264 crf=21 preset=medium + aac 192k + faststart | Render 出片 | M3.4 剪映 / M3.5 mp4 拼接 |
| `audio.wav` | 16kHz mono pcm_s16le | -vn -ac 1 -ar 16000 -c:a pcm_s16le（从 hd 抽） | ASR 输入 | M1.8 LocalWhisperProvider |

**关键约束**:
- 720p 检测必须与 1080p 出片**语义对齐**：shot 的 (start_sec, end_sec) 可直接复用到 hd 轨道（fps 差异通过秒级时间戳天然对齐）；ClipBinding 的时间码同样跨轨道有效
- 若原片本身 < 1080p：hd 轨道按 `min(原高度, 1080)` 处理，不做 upscale（避免无效编码）
- 若原片本身 < 720p：low 轨道仍按 720p（small upscale 影响可忽略），保证检测算法的输入分辨率稳定

**进度上报方案**（M1.6 handler）:
```
0.00 ─ stage start
0.05 ─ probe done (ffprobe)
0.45 ─ normalize_low done
0.85 ─ normalize_hd done
0.95 ─ audio extract done
1.00 ─ stage DONE
```

**磁盘成本**:
- 90min 1080p H.264 原片约 3-5GB；low + hd 双轨约 1.5-2.5GB（crf 主导，分辨率次之）
- 总占用约 raw 的 0.5-0.8x；M3.8 cleanup 阶段删除 raw + low，保留 hd（出片源）
- **R18 缓解开关**: Settings 暴露 `INGEST_SINGLE_TRACK=1`，强制只产出 hd（low 用 hd 做软链接）；用于磁盘吃紧场景应急

**工期影响**: M1.6 由 1.0d → 1.3d（+0.3d 用于第二轨命令构建、handler 编排扩展、对应单测增加）；全工期 31.5d → 31.8d。

**KPI 影响**:
- **K1（绑定准确率）**: 不变 — 检测 / 出片语义对齐保证 ClipBinding 时间码正确
- **K6（端到端耗时）**: Ingest 阶段 +30-50% 实际耗时（CPU 编码 2 次）；M4.5 验证总耗时仍 ≤ 16min/90min（M3 Pro 11 核可并行）
- **K9（raw 删除）**: 增强 — cleanup 后 raw + low 都删，仅 hd 保留作出片源

**为什么不选其他方案**:
| 方案 | 否决原因 |
|---|---|
| A. 单轨 720p（原 v0.4） | 出片画质损失大；用户上传 4K 强制 720p 出片不可接受 |
| B. 单轨 1080p（直接给 PySceneDetect） | shot 检测耗时翻倍；KeyFrameDesc 提取（v1.1+）耗时也涨 |
| C. 检测时 on-the-fly down-scale（不落盘） | 每次重跑都要重做 down-scale；ffmpeg 启动开销叠加；缓存逻辑复杂 |
| **D. 双轨落盘**（采纳） | 磁盘换 CPU；检测 / 出片关注点分离；语义天然对齐 |

**回滚策略**: 若 R18 触发严重磁盘问题，可走 INGEST_SINGLE_TRACK=1 应急（functional 等价于 ADR-010 之前的方案，但 hd 轨道不丢失出片质量）。

# M3 — Render（剪映+JsonTimeline）+ Web + 零知识架构（Week 4）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §14（Render 重写） / §16.5（零知识架构） / §17.3（双 Exporter） / §18.1（用户协议）

## 🎯 Milestone 目标
完成端到端可交付能力：TTS 合成 → Assembly 时长再适配 → 剪映草稿包导出（双 Exporter 防御）→ 极简 Web 4 页面 → 零知识架构落地（24h 自动清理 + 草稿不含原片路径）→ 用户协议勾选拦截。

## ✅ Milestone 验收
- [ ] 端到端跑通 1 部精选作品，输出 `output/jianying_draft.zip`
- [ ] 双击 zip 解压后能在剪映中打开，4 轨道结构正确（视频/解说/字幕/原片音量）
- [ ] JsonTimelineExporter 同步输出 `output/timeline_v2.json`（防御方案）
- [ ] Web 4 页面可用（上传/任务列表/任务详情/结果下载）
- [ ] 任务完成后 raw 文件 24h 内自动删除（K9）
- [ ] 草稿包内素材路径已脱敏为占位符（K10）
- [ ] 上传页未勾选用户协议时提交按钮 disabled（K11）
- [ ] 集成测试覆盖 Render / 零知识 / API 共 ≥ 5 个用例

## 📊 关联 KPI
- **K9**（raw 文件已删除）— P0 KPI
- **K10**（草稿不含原片路径）— P0 KPI
- **K11**（协议勾选拦截）— P0 KPI
- **K7**（resume 端到端）— Render 失败可恢复
- **K8**（测试覆盖）

## 🔗 依赖
- **前置**: M2b 完成（KPI 达标的 timeline.json）
- **阻塞下游**: M4 全部（E2E 验收依赖完整流水线）

---

## 任务清单（9 个）

### M3.1 — TTSProvider 抽象 + VolcengineTTSProvider 实现

**目标**: 定义 TTS 接口契约，实现火山豆包语音 Provider（design.md ADR-002）。**可与 M2a 末尾并行启动**。

**关键设计决策**:
- **TTSProvider abstract base**: 单方法 `synthesize(text: str, voice: str = "default", speed: float = 1.0) -> bytes`
  - 返回 16kHz/24kHz mono WAV bytes（让 Assembly 阶段统一处理 sample rate）
- **VolcengineTTSProvider**:
  - 默认 voice = "BV701_streaming"（火山豆包通用男声，可在 .env 配置）
  - HTTP API（非流式，避免 WS 连接管理复杂度），endpoint: `https://openspeech.bytedance.com/api/v1/tts`
  - Header: `Authorization: Bearer;{token}`（注意分号）
  - tenacity retry 3 次（指数退避，min=2 max=20）
  - 失败抛 `RuntimeError`
- **批量调用辅助**: `synthesize_batch(texts: list[str], concurrency=5) -> list[bytes]`
  - 用 `concurrent.futures.ThreadPoolExecutor`（IO bound）
  - 单条失败不影响整批；上层决定是否 retry 失败条
- **零知识合规**: TTS 返回的 wav bytes 仅在内存 / 临时目录暂存，Render 完成后立即删除

**涉及文件**:
- Create: `src/autoclip/providers/tts/{__init__,base,volcengine}.py`
- Create: `tests/unit/test_tts_base.py`
- Create: `tests/integration/test_volcengine_tts.py`（默认 skip）

**测试策略**:
- 单元: mock provider 接口 / synthesize_batch 并发数控制 / 批量中部分失败的容错
- 集成（手动）: 真实 token 跑 "你好世界"，验证返回 wav 可播放（< 50KB for 5 字）

**验收标准**:
- [ ] 接口可继承 / 批量并发正确
- [ ] 集成测试本地手跑通过

**关联 KPI**: K8
**依赖**: M1.1 → **阻塞**: M3.2
**预估工时**: 1d

---

### M3.2 — Assembly Stage：TTS 批量合成 + 时长再适配

**目标**: 实现 Assembly stage handler — 把 timeline.json 的句子批量 TTS，估算总时长，对超出 ±20% 目标的情况做降级，输出可供 Render 消费的 `assembly.json` + TTS wav 文件。

**关键设计决策**（design.md §8.4）:
- **流程**:
  1. 加载 `timeline.json`
  2. 按句调用 `tts.synthesize_batch()` → 落盘 `data/{job_id}/temp/tts/sentence_{N}.wav`
  3. 用 `ffprobe` 获取每条 wav 实际时长 → 写回 `narration_sentence.estimated_tts_duration_sec`
  4. 计算总解说时长 vs target_duration_sec
  5. **±20% 硬约束**:
     - 超出（解说太长）→ 截断策略：从段落末尾 sentences 开始裁（design.md §8.4 推荐"每段保留前 70%"）
     - 不足（太短）→ 仅警告，不补；让用户在剪映里手动补
- **`assembly.json` schema**:
  ```
  {
    "total_narration_duration_sec": float,
    "target_duration_sec": int,
    "duration_drift_ratio": float,
    "trimmed_sentence_ids": [int],  // 被裁掉的 sentence id（K1 评估时排除）
    "sentences": [{
      "sentence_id": int,
      "tts_wav_path": "temp/tts/sentence_3.wav",  // 相对路径
      "actual_duration_sec": float,
      "ordered_idx": int,
    }]
  }
  ```
- **进度上报**: 0.1（load） → 0.3 → 0.6 → 0.9（TTS 完成）→ 1.0
- **Cancel 检查点**: 每 10 句 TTS 后

**涉及文件**:
- Create: `src/autoclip/pipeline/assembly.py`
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import assembly`）
- Create: `tests/unit/test_assembly_logic.py`（纯函数测试：截断策略 / 漂移计算）
- Create: `tests/integration/test_assembly_e2e.py`（mock TTS）

**测试策略**:
- 单元: 漂移 +30% 时正确触发截断 / 漂移 -10% 仅警告 / trimmed_sentence_ids 去除规则正确
- 集成（mock TTS 返回固定 bytes）: 完整 timeline.json → assembly.json 结构正确

**验收标准**:
- [ ] 单元 ≥ 4 个用例通过
- [ ] mock 集成测试通过
- [ ] 真实跑 5min 短片：assembly.json 漂移 ≤ ±20%

**关联 KPI**: K6（端到端耗时） / K8
**依赖**: M3.1 + M2b 完成 → **阻塞**: M3.4 / M3.6
**预估工时**: 1.5d

---

### M3.3 — DraftExporter 抽象 + 双实现接口契约

**目标**: 在写具体 Exporter 之前，先冻结统一的输入/输出契约，确保 M3.4 和 M3.6 双实现接口一致（防御性架构 §17.3）。

**关键设计决策**（**契约先行，避免双实现接口分裂**）:
- **`DraftExporter` abstract base**:
  ```
  export(
      timeline: dict,           // timeline.json 内容
      assembly: dict,            // assembly.json 内容
      shots: list[dict],         // shots.json 内容
      job_dir: Path,             // 找 normalized.mp4 + tts wav
      output_dir: Path,          // 输出根目录
      *,
      original_video_relative: str = "./materials/source.mp4",  // 占位符路径（零知识！）
  ) -> ExportResult
  ```
- **`ExportResult` dataclass**:
  - `output_path: Path`（草稿包/JSON 文件位置）
  - `format: str`（"jianying_draft" / "json_timeline"）
  - `material_count: int`
  - `track_count: int`
  - `warnings: list[str]`
- **关键约束**:
  - **K10 强制**: 输出物中**不得**包含 `job_dir` 的绝对路径或 `normalized.mp4` 的真实路径，必须改写为 `original_video_relative` 占位符
  - **DRY**: shot id → 时间区间的查找逻辑提到基类 helper
- **统一 4 轨道语义定义**（design.md §14）:
  - Track 1（视频）: 主视频片段，按 segments 顺序拼接
  - Track 2（解说音轨）: TTS wav 队列，全程音量 100%
  - Track 3（原片音量）: normalized.mp4 的音轨，整段铺底，segments 期间音量 30%，间隙 100%（M3-b 策略）
  - Track 4（字幕）: 每个 segment 的 sentence_text

**涉及文件**:
- Create: `src/autoclip/exporters/{__init__,base}.py`
- Create: `tests/unit/test_exporter_base.py`

**测试策略**:
- 单元: helper 函数（shot_id 查找 / 占位符路径生成）
- 抽象类无法实例化的标准测试

**验收标准**:
- [ ] 接口契约单元测试通过
- [ ] M3.4 + M3.6 都能基于本契约实现

**关联 KPI**: K10（接口层强制零知识）
**依赖**: M3.2 → **阻塞**: M3.4 / M3.6
**预估工时**: 0.5d

---

### M3.4 — JianyingDraftExporter 实现（基于 pyJianYingDraft）

**目标**: 实现剪映草稿包生成的主方案，输出可在剪映 5.x+ 打开的 `.zip` 草稿包。

**关键设计决策**（design.md §14 + ADR-008）:
- **依赖**: `pyjianyingdraft` PyPI 包（如不可用，回退到 git+url 安装；版本固化在 pyproject.toml）
- **草稿包结构**（剪映标准）:
  ```
  jianying_draft.zip
  ├── draft_content.json    ← 工程文件
  ├── draft_meta_info.json  ← 元数据
  └── materials/
      ├── README.txt        ← 中文引导：双击前用剪映导入素材
      └── (无媒体文件！素材路径用占位符)
  ```
- **关键步骤**:
  1. 创建 `Script_file`（剪映工程对象），分辨率 1080x1920（竖屏）或 1920x1080（横屏，从 ingest probe 拿原片宽高比决定）
  2. 添加 4 轨道：1 video + 2 audio + 1 subtitle
  3. 遍历 timeline.segments：
     - Track 1: 添加 `VideoSegment(material_id=占位符, source_timerange=[start, end], target_timerange=[累加 t, +duration])`
     - Track 4: 添加 `TextSegment(text=sentence_text, target_timerange=同视频)`
  4. 遍历 assembly.sentences:
     - Track 2: 添加 `AudioSegment(material_id=tts_wav 路径, target_timerange=[ordered_idx 累加, +actual_duration])`
  5. Track 3: 整段添加原视频音轨，对每个 segment 区间用 `AudioSegment.set_volume_keyframes()` 降到 30%
  6. **K10 占位符注入**: `material_id` 不写入绝对路径，写相对路径 `./materials/source.mp4`
  7. 写 `README.txt`（中文引导）
  8. 打包为 zip → `output_dir / "jianying_draft.zip"`
- **边界处理**:
  - 中文路径: 强制 UTF-8 编码，文件名 ASCII 化（用 `unidecode` 或 hash）
  - 剪映版本兼容: 在 `draft_meta_info.json` 写入 `version: "5.9.0"` 兼容标识
- **失败诊断**: 任何 pyJianYingDraft 异常都包成 `JianyingExportError(orig_exc)` 抛出，不被吞

**涉及文件**:
- Create: `src/autoclip/exporters/jianying.py`
- Create: `tests/unit/test_jianying_exporter.py`（用合成 timeline，不真依赖剪映）
- Create: `tests/integration/test_jianying_real.py`（产出 zip，需手动用剪映打开验证）

**测试策略**:
- 单元: zip 内必含 draft_content.json + draft_meta_info.json + README.txt / draft_content.json 中所有 material 路径都是占位符（K10 自动化检测）/ 4 轨道结构正确
- 集成（手跑）: 5min 短片完整产出 zip，剪映打开后 4 轨道可见、字幕显示正确

**验收标准**:
- [ ] 单元 ≥ 5 个用例通过（含 K10 占位符自动检测）
- [ ] 手动剪映打开验证通过 1 次

**关联 KPI**: K10 / K8 — **关键路径任务**
**依赖**: M3.3 → **阻塞**: M3.5（注册到 Render handler）
**预估工时**: 2d（含剪映兼容性调试）

---

### M3.5 — Render Stage handler + 草稿轨道结构验证

**目标**: 实现 Render stage handler，调度 DraftExporter（默认 jianying，可切换 json_timeline），并对产出做轨道结构自动验证。

**关键设计决策**:
- **handler 流程**:
  1. 加载 timeline.json + assembly.json + shots.json
  2. 根据 `AUTOCLIP_EXPORTER` 环境变量（默认 `jianying`，可切 `json_timeline`）选择 Exporter
  3. 调 `exporter.export()` → 拿 ExportResult
  4. **轨道验证**（K10 自动化）:
     - 解析输出文件，断言 material 路径全部是占位符（regex 检测：不匹配 `^/.*` 或 `^[A-Z]:`）
     - 断言 4 轨道存在
     - 断言所有 segment 时间范围在 [0, total_duration]
  5. 失败 → mark FAILED，不产出残缺 zip
- **进度上报**: 0.1（load）→ 0.6（export）→ 0.95（validate）→ 1.0
- **注册**: `register_stage_handler(Stage.RENDER, run_render)`

**涉及文件**:
- Create: `src/autoclip/pipeline/render.py`
- Modify: `src/autoclip/pipeline/__init__.py`（追加 `from . import render`）
- Create: `tests/integration/test_render_e2e.py`

**测试策略**:
- 集成（mock exporter）: 完整流程跑通 + 轨道验证逻辑工作
- 集成（真 exporter）: 5min 短片端到端 ingest+index+script+assembly+render 全跑通

**验收标准**:
- [ ] 集成测试通过
- [ ] **Milestone 端到端 happy path 验收**：5min 短片产出 jianying_draft.zip 可在剪映打开

**关联 KPI**: K7 / K8 / K10
**依赖**: M3.4 → **阻塞**: M3.6（同 stage 内的兜底） / M3.7-M3.9 集成
**预估工时**: 1d

---

### M3.6 — JsonTimelineExporter 防御实现（P1-3）

**目标**: 提供独立于 pyJianYingDraft 的兜底输出方案 — 自定义 JSON 格式的 timeline 描述，未来可被自研编辑器或第三方工具消费。**可与 M3.4 并行**。

**关键设计决策**（design.md §17.3 防御方案）:
- **设计动机**: pyJianYingDraft 是社区维护的非官方库，存在不维护风险（R1）；JsonTimelineExporter 保证即使 R1 发生，用户仍能拿到结构化时间线数据
- **JSON Schema**（自定义，不模仿剪映）:
  ```
  {
    "version": "1.0",
    "video_duration_sec": float,
    "tracks": {
      "main_video": [{seg_id, source_path, source_start, source_end, target_start, target_end}],
      "narration": [{seg_id, audio_path, target_start, target_end, volume: 1.0}],
      "original_audio": [{target_start, target_end, volume: 0.3 | 1.0}],  // 段内 0.3，间隙 1.0
      "subtitle": [{seg_id, text, target_start, target_end}]
    },
    "metadata": {
      "exporter": "json_timeline",
      "exporter_version": "1.0",
      "original_video_relative": "./materials/source.mp4",  // 占位符
      "generated_at": "ISO8601"
    }
  }
  ```
- **K10 同样强制**: 所有 source_path 必须用占位符
- **打包**: 输出 `.zip` 含 `timeline.json` + `README.txt`（说明这是自研格式，未来可对接何种工具）
- **基类复用**: 共享 M3.3 base 的 helper（占位符路径生成 / shot 查找）

**涉及文件**:
- Create: `src/autoclip/exporters/json_timeline.py`
- Create: `tests/unit/test_json_timeline_exporter.py`

**测试策略**:
- 单元: schema 完整性 / K10 占位符自动检测 / 4 个 track 都有内容 / volume 0.3↔1.0 切换正确

**验收标准**:
- [ ] 单元 ≥ 4 个用例通过
- [ ] 与 M3.4 共享相同 timeline.json 输入，能产出对等的时间线结构（语义对齐）

**关联 KPI**: K10 / K8 — **R1 风险缓解**
**依赖**: M3.3 → **阻塞**: 无（独立模块，与 M3.4 并行）
**预估工时**: 1d

---

### M3.7 — 极简 Web 4 页面（Jinja + Tailwind CDN）

**目标**: 实现极简前端 — 上传/任务列表/任务详情/结果下载 4 个页面，提供完整的人机交互闭环。**可与 M2a/M2b 并行**。

**关键设计决策**（design.md §13 + ADR-007 修订）:
- **技术栈**: Jinja2 模板 + Tailwind CSS CDN + 原生 JS（fetch + 轮询，无 SPA 框架）
- **页面清单**:
  1. `GET /` → `upload.html`：上传表单（file + 时长档位 select + 风格 select + **协议勾选 checkbox**）
  2. `GET /jobs` → `jobs.html`：任务列表（表格：id / 创建时间 / 进度 / 操作按钮）
  3. `GET /jobs/{id}` → `job_detail.html`：进度详情（5 stage 进度条 + 当前 stage + 取消按钮 + 错误信息）
  4. `GET /jobs/{id}/result` → `result.html`：结果下载（剪映草稿包 + JsonTimeline 包 + 时间线预览）
- **路由实现**: `src/autoclip/web/routes.py`（独立于 `api/`，避免混淆 HTML/JSON 端点）
- **轮询**: job_detail.html 用 `setInterval(fetch('/api/jobs/{id}'), 2000)` 自动刷新进度条
- **上传体验**: file input + 显示文件大小 + 上传中 spinner（无需进度条，因为 multipart 一次性上传）
- **Tailwind**: 用 CDN（`https://cdn.tailwindcss.com`），无需构建
- **无登录**: MVP 单用户本地部署（design.md ADR-007 修订）

**涉及文件**:
- Create: `src/autoclip/web/{__init__,routes}.py`
- Create: `src/autoclip/web/templates/{layout,upload,jobs,job_detail,result}.html`
- Modify: `src/autoclip/main.py`（mount Jinja2Templates + 注册 web routes）
- Create: `tests/integration/test_web_routes.py`（用 httpx TestClient）

**测试策略**:
- 集成: 4 个页面 GET 200 / 上传表单字段完整 / 协议未勾选时 form action 被前端 JS 拦截

**验收标准**:
- [ ] 4 个页面浏览器可访问
- [ ] 端到端：上传 → 等待 → 看进度 → 下载草稿包 全程顺畅
- [ ] 视觉合格（不要求设计精美，但布局清晰，移动端响应式）

**关联 KPI**: K11 部分（前端拦截）
**依赖**: M1.4 → **阻塞**: M3.9（协议拦截后端 + 前端联动）
**预估工时**: 1.5d

---

### M3.8 — 零知识架构落地（cleanup hook + audit 命令）

**目标**: 实现 design.md §16.5 零知识架构 — 临时文件 24h 自动清理 + 数据库脱敏 + audit 审计命令。

**关键设计决策**（**P0 合规**）:
- **数据生命周期实现**（参照 design.md §16.5 表格）:
  - `data/{job_id}/source.mp4` + `normalized.mp4` + `temp/`：任务完成立即删除（在 Render 成功 callback 中）
  - `audio.wav`：M1.8 已实现 ASR 后立即删
  - `output/*.zip`：用户下载后 24h 删除（用 atime + cron 任务判定）
  - `asr.json` / `timeline.json` / `assembly.json`：长期保留 30 天，30 天后自动清理（保留摘要在 SQLite）
- **`compliance/cleanup.py`**:
  - `cleanup_after_render(job_dir: Path)` — Render handler 调用，删除 normalized.mp4 / temp/
  - `cron_cleanup_temp(data_dir: Path, max_age_hours: int = 24)` — FastAPI startup 注册的 BackgroundTask（apscheduler / 简单 asyncio.create_task），每小时扫一次
  - 删除时记录到 audit log（不记录文件内容，仅文件名 + size + delete_reason）
- **`compliance/audit.py`** CLI:
  - `python -m autoclip.audit list` — 列出当前持有的所有数据（按 job 分组，显示路径 / size / age）
  - `python -m autoclip.audit purge --job-id N` — 立即删除指定 job 的全部数据（含数据库记录）
  - `python -m autoclip.audit purge --all --confirm` — nuclear option
- **数据库脱敏**:
  - Video.original_filename 已经只存文件名（不含路径），Video.filename_hash 是哈希
  - Job 完成 30 天后自动清理 timeline 详细字段，仅保留 binding_stats 摘要

**涉及文件**:
- Create: `src/autoclip/compliance/{__init__,cleanup,audit}.py`
- Modify: `src/autoclip/main.py`（startup hook 注册 cron）
- Modify: `src/autoclip/pipeline/render.py`（成功后调用 cleanup_after_render）
- Create: `tests/integration/test_zero_knowledge.py`

**测试策略**:
- 集成: 跑完一个 job 后 normalized.mp4 + temp/ 不存在 / cron 模拟时间快进 25h，output 已删 / audit list 输出格式正确

**验收标准**:
- [ ] K9 自动化测试通过：任务完成后 raw 文件 0% 残留
- [ ] audit CLI 三个子命令可用
- [ ] cron 任务正确注册（startup log 可见）

**关联 KPI**: K9 — **核心 P0 验收门禁**
**依赖**: M3.5 → **阻塞**: 无（独立模块）
**预估工时**: 1d

---

### M3.9 — 用户协议 v0.1 集成（前端拦截 + 后端二次校验）

**目标**: 把 `docs/legal/user-agreement-v0.1.md`（已存在）集成到 Web，实现"未勾选不可提交"的硬拦截。

**关键设计决策**（design.md §18.1）:
- **前端**:
  - `upload.html` 底部嵌入协议摘要（前 3 条核心条款）+ "查看完整协议" 链接（弹窗 modal 或新 tab 显示完整 markdown 渲染）
  - 必填 checkbox：`<input type="checkbox" name="agreement_accepted" required>`
  - 提交按钮初始 `disabled`，checkbox change 时启用 / 禁用
- **后端二次校验**（**重要**：前端可被绕过，后端必须再校验一次）:
  - `POST /api/jobs` 增加表单字段 `agreement_accepted: bool`
  - 未传或为 false → `HTTPException(400, "用户协议必须勾选")`
  - 落库到 Job 表新字段 `agreement_accepted_at: datetime`（举证用）
- **协议渲染**:
  - 用 Python `markdown` 库（依赖追加）把 `user-agreement-v0.1.md` 渲染为 HTML
  - `GET /agreement` 端点返回完整协议页面
- **数据库 schema 演进**:
  - Job 表新增字段 `agreement_accepted_at: Mapped[datetime | None]`
  - 用 Alembic 或简单 `ALTER TABLE` 迁移（MVP 选后者，迁移脚本放 `scripts/migrate.py`）

**涉及文件**:
- Modify: `src/autoclip/models/job.py`（新增 agreement_accepted_at）
- Modify: `src/autoclip/api/jobs.py`（POST 校验 agreement_accepted）
- Modify: `src/autoclip/web/routes.py`（GET /agreement）
- Modify: `src/autoclip/web/templates/upload.html`（checkbox + 提交按钮 disabled 逻辑）
- Create: `scripts/migrate.py`（添加列）
- Create: `tests/integration/test_agreement_block.py`

**测试策略**:
- 集成: POST /api/jobs 不传 agreement_accepted → 400 / 传 false → 400 / 传 true → 200 + DB 落字段
- 前端测试（手动）: 浏览器看到 checkbox 不勾时按钮灰，勾选后按钮亮

**验收标准**:
- [ ] K11 自动化测试通过（后端拦截 100%）
- [ ] 前端 disabled 行为正确
- [ ] DB 落字段验证通过

**关联 KPI**: K11 — **核心 P0 验收门禁**
**依赖**: M3.7 → **阻塞**: M3 milestone 整体验收
**预估工时**: 0.75d

---

## M3 总工时估算
| 任务 | 工时 |
|---|---|
| M3.1 TTSProvider | 1.0d |
| M3.2 Assembly | 1.5d |
| M3.3 DraftExporter base | 0.5d |
| M3.4 JianyingExporter | 2.0d |
| M3.5 Render handler | 1.0d |
| M3.6 JsonTimelineExporter | 1.0d |
| M3.7 Web 4 页面 | 1.5d |
| M3.8 零知识架构 | 1.0d |
| M3.9 用户协议拦截 | 0.75d |
| **总计** | **10.25d** ⚠️ 超出 W4（5d） |

> **工时风险**：M3 名义 1 周但实际 10d。**缓解方案**：
> 1. M3.1（TTSProvider）和 M3.7（Web）从 M2a/M2b 末尾提前启动（节省 1.5d）
> 2. M3.6（JsonTimelineExporter）与 M3.4 并行（节省 1d）
> 3. M3.8 + M3.9 可与 M3.4 调试期并行（节省 0.5d）
> 4. 调整后等效工时约 7.25d，仍可能侵占 W5 早期 1-2 天 → 用 W6 buffer 兜底

## M3 完成时的 PR 描述模板
```
✨feat: M3 - Render + Web + Zero-knowledge architecture
    - T3.1 TTSProvider abstraction + Volcengine impl
    - T3.2 Assembly stage (TTS batch + duration adapter ±20%)
    - T3.3 DraftExporter base + 4-track contract
    - T3.4 JianyingDraftExporter (pyJianYingDraft, K10 placeholder enforced)
    - T3.5 Render stage handler + track structure validation
    - T3.6 JsonTimelineExporter (defensive fallback for R1)
    - T3.7 Minimal web 4 pages (Jinja + Tailwind CDN)
    - T3.8 Zero-knowledge: cleanup hooks + 24h cron + audit CLI
    - T3.9 User agreement v0.1 enforcement (frontend + backend)
    - K9/K10/K11 all green (P0 compliance gates passed)
```

## ⚠️ M3 失败兜底
- **M3.4 剪映兼容性问题**：立即切到 JsonTimelineExporter 作为唯一输出，MVP 改为"输出标准 JSON timeline 让用户在他熟悉的工具里加工"，剪映对接降级为 v1.1 目标
- **M3.7 时间不够**：MVP 退化为 CLI 工具（仅保留 API + 命令行客户端），Web 移到 v1.1
- **M3.8 cron 实现复杂**：MVP 改为"启动时清理一次 + 每个任务结束后清理一次"，正式 cron 移到 v1.1（不影响 K9 验收，因为 K9 只要求"任务完成后删除"）

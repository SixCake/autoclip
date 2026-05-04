# AutoClip 设计索引（轻量版 v0.4）

> 完整设计文档：[`docs/plans/2026-05-04-autoclip-design.md`](../docs/plans/2026-05-04-autoclip-design.md)（2282 行）
>
> 文档分四部分：
> - **Part I（§1-§12，行 1-1003）** — v0.1 初版（mp4 出片 + 自建编辑器）
> - **Part II（§13-§15，行 1004-1419）** — v0.2 剪映草稿 adhoc 修订
> - **Part III（§16-§20，行 1420-2107）** — v0.3 多角度评审修订
> - **Part IV（§21-§23，行 2108-2282）** — v0.4 本地化 + 角色推断修订（**当前最新，最高优先级**）
>
> **冲突时优先级**：v0.4 > v0.3 > v0.2 > v0.1（后写后准）

## 一句话定位
面向影视/电视剧/动漫**二创解说创作者**的 AI 短视频草稿生成助手。

## ★ 核心产品形态（v0.4 最终）
1. 用户在极简 Web 上传 1 部电影 + 选时长档位 + 选风格预设（3 种） + 勾选用户协议
2. 系统跑 5 阶段流水线：Ingest → Index → **Scripting（narrative IR + post-validation）★** → Assembly → Render（剪映草稿）
3. 系统输出 AI 自评分（4 维度），用户可一键重生成
4. 用户下载 .zip 草稿包，**双击在剪映中打开继续编辑**
5. 任务完成后 raw 文件 24h 内自动删除（**零知识架构**）

## 核心原则
- **创作助手定位（B）**，编辑环节交给剪映
- **YAGNI** + **诚实工期**：5-6 周 4 个 milestones
- **Schema 一次到位**：TimelineSegment 统一中间层
- **三层抽象**：LLMProvider / TTSProvider / ASRProvider / DraftExporter（双实现）
- **测试驱动**：核心算法单元覆盖 ≥ 70%
- **合规前置**：零知识架构 + 用户协议草稿 v0.1

## MVP 5 阶段流水线（v0.3）
```
Ingest → Index → Scripting ★ → Assembly → Render
                  ↑               ↑          ↓
             narrative IR    时长再适配    剪映草稿
             post-validation              (+JsonTimeline 兜底)
```

## 关键技术栈（MVP v0.4 默认）
| 层 | 选型 | 备选/降级 |
|---|---|---|
| LLM | 通义千问 qwen-plus | DeepSeek-V3 |
| **ASR** | **faster-whisper + large-v3 本地推理**（v0.4 改本地，零网络）<br>中文 WER 8-12%，M3 Pro 实时率 4-5x | mlx-whisper / FunASR / 阿里云 NLS / Whisper API |
| 镜头切分 | PySceneDetect ContentDetector | TransNetV2 |
| 角色识别 | **LLM 文本推断（路径2，v0.4 新增）**<br>主角/反派由 LLM 从对白称呼自行推断，写入 PlotOutline.main_characters | 声纹 diarization（WhisperX，v1.1+ 兜底） |
| TTS | 火山豆包语音 API | Minimax / CosyVoice2 本地 |
| 视频归一化 | FFmpeg | — |
| **最终输出** | **pyJianYingDraft（剪映草稿）** | **JsonTimelineExporter（防御）** |
| 后端 | Python 3.11 + FastAPI | — |
| **任务执行** | **multiprocessing + 文件状态机** | — |
| 前端 | Jinja2 + Tailwind CDN（4 页面） | — |
| 存储 | SQLite + 本地文件 | Postgres (v2) |

## 5-6 周 Milestone（S1 Demo）
- **W1（M1）**：基础设施 + Ingest + Index（多进程 + 文件状态机 + Aliyun ASR）
- **W2（M2a）**：Scripting 主链路（LLM + plot outline + 简化绑定）
- **W3（M2b）**：Scripting 鲁棒性（narrative IR + post-validation + KPI 评估）
- **W4（M3）**：Render（剪映 + JsonTimeline）+ 极简 Web + 零知识架构
- **W5（M4）**：E2E + 3 种风格 + AI 自评分 + 多片回归
- **W6（buffer）**：KPI 验收 + 关键修复

## MVP 验收 KPI（11 项量化指标）
- 算法：绑定准确率 ≥70% / evidence 召回率 ≥80% / fallback ≤30%
- 体验：用户主观评分 ≥4/5 / 人工调优时间 ≤1h/部
- 工程：端到端 ≤16min / 可 resume / 单元测试覆盖 ≥70%
- 合规：raw 自动删除 100% / 草稿不含原片路径 100% / 协议勾选拦截 100%

## v0.4 关键文件
- `docs/plans/2026-05-04-autoclip-design.md` — 完整设计 2282 行（Part IV §21-§23 为最新）
- `docs/legal/user-agreement-v0.1.md` — 用户协议 v0.1 草稿

## v0.4 关键决策记录
- **§21.1 ADR-004 三度修订**：ASR 改本地 faster-whisper + large-v3（移除 OSS / 阿里云 NLS / 网络依赖）
- **§22 ADR-009 新增**：MVP 角色信息走 LLM 文本推断（路径 2），不做声纹；ASRSentence.speaker 仍保持 None

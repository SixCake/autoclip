# M4 — E2E + 风格扩展 + 自评分 + 多片回归（Week 5）

> **隶属于**: [`../2026-05-04-autoclip-plan.md`](../2026-05-04-autoclip-plan.md)
> **设计依据**: [`../2026-05-04-autoclip-design.md`](../2026-05-04-autoclip-design.md) §17.1（风格预设）/ §17.2（AI 自评分）/ §18.2（KPI）/ §19.3（路线图）

## 🎯 Milestone 目标
打通端到端真实场景验收 — 在 3 部不同类型作品上完整跑流水线；扩展风格预设到 3 种（剧情速览 / 吐槽 / 严肃影评）；上线 AI 自评分 + 一键重生成；完善错误兜底；最终验证 11 项 KPI 全部达标。

## ✅ Milestone 验收
- [ ] 3 部不同类型作品（实拍剧情 / 实拍动作 / 动漫）完整 E2E 跑通，剪映可打开
- [ ] 用户主观评分 **K4 ≥ 4/5**（自评 + 1-2 个真实创作者朋友盲评）
- [ ] 人工调优时间 **K5 ≤ 1h/部**（在剪映里调到"愿意发布"水平）
- [ ] 端到端耗时 **K6 ≤ 16min/90min 视频**
- [ ] 3 种风格预设都能产出合理 timeline.json
- [ ] AI 自评分功能可用（4 维度评分 + 每个维度文字反馈）
- [ ] 一键重生成在前端可用
- [ ] 任意 stage 失败有清晰错误提示 + 部分结果可下载

## 📊 关联 KPI
- **K1, K2, K3**（算法 KPI）：M2b 已达标，M4 多片回归再次验证（避免单部作品偶然成功）
- **K4**（用户主观评分 ≥ 4/5）— P1 KPI，本里程碑核心
- **K5**（人工调优时间 ≤ 1h/部）— P1 KPI
- **K6**（端到端耗时 ≤ 16min/90min）— P1 KPI
- 全部 11 项 KPI 最终验收

## 🔗 依赖
- **前置**: M3 全部完成
- **阻塞下游**: 无（最后一个 milestone）

---

## 任务清单（5 个）

### M4.1 — 3 部作品 E2E 端到端跑通

**目标**: 选定 3 部代表性短片，完整跑流水线，记录性能数据和质量观察。

**关键设计决策**:
- **作品选择**（5min 短片优先以控制 LLM cost）:
  - **实拍剧情**: 一部对白密集、情节清晰的电影片段（如某经典电影开场 5min）
  - **实拍动作**: 一部对白稀疏、镜头切换频繁的动作片段（验证镜头切分鲁棒性）
  - **动漫**: 一部日漫/国漫片段（验证 PySceneDetect 阈值在动漫场景的表现 — 可能需要 threshold=30+）
- **测试矩阵**:
  | 作品 | target_duration | style | 关注指标 |
  |---|---|---|---|
  | 剧情 | 60s + 180s | plot_summary | K1, K2, K3, K6 |
  | 动作 | 90s | plot_summary | 镜头切换密集场景的绑定准确率 |
  | 动漫 | 90s | plot_summary | PySceneDetect threshold 调优 |
- **数据收集**:
  - 自动: 每个 stage 的耗时（从 state.json 时间戳算）
  - 手动: 剪映打开后的"调优时长" — 用秒表计时调到自己满意为止
  - 写入: `data/jobs/{id}/e2e_report.json`
- **CLI 工具**: `python -m scripts.e2e_run --video {path} --duration 60 --style plot_summary`
  - 包装 POST /api/jobs + 轮询 + 等待完成 + 收集报告

**涉及文件**:
- Create: `scripts/e2e_run.py`
- Create: `tests/fixtures/README.md`（说明 3 部 fixture 的来源、版权情况、如何获取）
- Create: `data/e2e_reports/`（runtime，gitignore）

**测试策略**:
- 不写自动化测试（这是手工 E2E）
- 用 scripts/e2e_run 收集数据，输出到 markdown 总结

**验收标准**:
- [ ] 3 部作品都能跑完不报错
- [ ] 每部 e2e_report.json 包含 stage 耗时 / 总耗时 / 调优时长
- [ ] 总耗时 ≤ 16min/90min（按比例换算 5min ≤ 53s + 调优时长不计）

**关联 KPI**: K6 / K7（resume 实战检验）
**依赖**: M3 完成 → **阻塞**: M4.2 / M4.5（依赖 e2e_report 数据）
**预估工时**: 1d（含寻找合适作品 + 调试）

---

### M4.2 — 用户主观评分（自评 + 朋友盲评）

**目标**: 通过结构化盲评收集用户主观评分（K4），验证产品体验是否达到 MVP 发布门槛。

**关键设计决策**:
- **评分维度**（5 分制，design.md §17.2 参考）:
  1. **解说稿质量**：句子是否通顺、剧情还原度、是否有错别字
  2. **镜头匹配度**：句子和画面内容是否对应（与 K1 不同 — K1 是技术准确率，这里是用户感知）
  3. **节奏感**：解说速度是否舒适、句长是否合适、停顿合理
  4. **整体可发布性**：如果是你自己创作的，你愿意原封不动发到 B 站吗？
- **评分流程**:
  1. 自评: 跑完 M4.1 的 3 部作品后，自己看完成片打分
  2. 朋友盲评（盲意味着不告知是 AI 生成的）: 找 1-2 个真实做二创的创作者朋友，发剪映草稿请他们过一遍
  3. 取所有评分平均，写入总控文档第 4 节
- **评分模板**: `scripts/score_form.md`（标准化问卷）
- **隐私保护**: 朋友盲评时不上传原片，仅发剪映草稿包让对方在本地剪映打开

**涉及文件**:
- Create: `scripts/score_form.md`（评分问卷模板）
- Create: `data/e2e_reports/scores.md`（runtime，gitignore；汇总评分）

**测试策略**:
- 不写自动化测试（人工评分）

**验收标准**:
- [ ] 至少 1 部作品 K4 ≥ 4/5
- [ ] 3 部作品平均 K4 ≥ 3.5/5（妥协线 — 全部 ≥ 4 是理想，平均 3.5 是 MVP 接受边界）
- [ ] 总控文档 KPI 表已更新

**关联 KPI**: K4 — **本 milestone 核心 P1 验收**
**依赖**: M4.1 → **阻塞**: M4.5（验收阶段）
**预估工时**: 0.5d 自评 + 1-3d 朋友评（异步等待，不计入纯工作日）

---

### M4.3 — 风格预设扩展到 3 种（humor_roast + serious_review）

**目标**: 在 M2a.3 已有的 plot_summary 基础上，扩展 humor_roast（吐槽）和 serious_review（严肃影评）两种风格，让用户可在前端切换。

**关键设计决策**（design.md §17.1 P1-1）:
- **风格 2: humor_roast（吐槽风）**:
  - 文件: `prompts/style_presets/humor_roast.py`
  - STYLE_DESCRIPTION:
    - 第一人称口语化（"我跟你说"/"这家伙"）
    - 适度幽默：吐槽人物或剧情逻辑漏洞
    - 单句 12-25 字（比 plot_summary 长，承载吐槽）
    - 可用感叹号、反问句、网络流行语（适度）
    - 避免低俗、人身攻击
  - FEW_SHOT_EXAMPLES: 3 个例子（电影/电视剧/动漫各 1）
- **风格 3: serious_review（严肃影评）**:
  - 文件: `prompts/style_presets/serious_review.py`
  - STYLE_DESCRIPTION:
    - 第三人称分析视角（"导演通过此处镜头..."）
    - 关注：导演手法、镜头语言、表演、隐喻
    - 单句 15-30 字（书面化）
    - 引用电影理论或同类作品对比
  - FEW_SHOT_EXAMPLES: 3 个例子
- **prompt builder 扩展**:
  - `build_narrative_ir_messages(..., style_preset="humor_roast")` 自动加载对应模块
  - 三种风格的 system prompt 模板差异通过 STYLE_DESCRIPTION 注入
- **前端集成**:
  - upload.html 的 style select 新增两个 option
  - 每个 option 旁加 1 句话简介（hover tooltip 显示完整风格说明）
- **API 校验**: POST /api/jobs 校验 style_preset ∈ {plot_summary, humor_roast, serious_review}，否则 400

**涉及文件**:
- Create: `src/autoclip/prompts/style_presets/{humor_roast,serious_review}.py`
- Modify: `src/autoclip/prompts/narrative_ir.py`（dispatch 三种风格）
- Modify: `src/autoclip/api/jobs.py`（style_preset 枚举校验）
- Modify: `src/autoclip/web/templates/upload.html`（select options）
- Create: `tests/unit/test_style_presets.py`

**测试策略**:
- 单元: 三种风格 builder 都能产出合法 messages / API 校验非法 style 返回 400
- 集成（手跑）: 同一短片用 3 种风格各跑一次，肉眼对比风格差异明显

**验收标准**:
- [ ] 3 种风格都有 ≥ 3 few-shot 例子
- [ ] 同一短片 3 种风格输出明显不同（至少 50% 句子文本不一样）
- [ ] 前端 select 体验正常

**关联 KPI**: K4（风格丰富度提升用户评分）
**依赖**: M2a.3 → **阻塞**: M4.5（多风格在 M4 验收里展示）
**预估工时**: 1d

---

### M4.4 — AI 自评分 + 一键重生成

**目标**: 在 Render 完成后自动调 LLM 对成品做 4 维度评分，结果展示在 result.html；用户可一键重生成（不重新跑 ingest/index）。

**关键设计决策**（design.md §17.2 P1-2）:
- **AI 自评分**:
  - 触发时机：Render stage 成功后自动触发（同步，不是新 stage）
  - 评分维度（与 M4.2 人工评分对齐，方便对比）:
    1. 解说稿质量（1-5）
    2. 镜头匹配度（1-5）
    3. 节奏感（1-5）
    4. 整体可发布性（1-5）
  - LLM 输入: timeline.json 的 plot_outline + sentences + binding_stats（不传原视频/音频，控制 token）
  - LLM 输出 schema:
    ```
    {
      "scores": {"script_quality": 4, "visual_match": 3, "rhythm": 4, "publishable": 3},
      "feedback": {
        "script_quality": "整体通顺，但第3、7句有冗余",
        "visual_match": "第5句和镜头不太对应（fallback触发）",
        ...
      },
      "overall": 3.5,
      "suggestion": "建议重新生成或在剪映里调整第5、7句"
    }
    ```
  - 落盘: `data/jobs/{id}/self_evaluation.json`
- **一键重生成**:
  - result.html 显示自评分 + "重新生成解说稿"按钮
  - 点击后: `POST /api/jobs/{id}/regenerate`
  - 后端逻辑:
    - 不重跑 ingest/index（直接复用现有 shots.json + asr.json）
    - 删除 timeline.json + assembly.json + output/
    - state.json 把 script/assembly/render 三个 stage 重置为 PENDING
    - 启动新子进程 PipelineRunner(resume=True)
    - 因为 ingest+index 已 DONE，会自动从 script 开始
  - 限制: 同一 job 最多重生成 3 次（防止 LLM cost 失控）
- **Prompt 文件**: `prompts/self_evaluate.py`

**涉及文件**:
- Create: `src/autoclip/prompts/self_evaluate.py`
- Modify: `src/autoclip/pipeline/render.py`（成功后调 self-evaluate）
- Modify: `src/autoclip/api/jobs.py`（POST /api/jobs/{id}/regenerate）
- Modify: `src/autoclip/web/templates/result.html`（显示 scores + 重生成按钮）
- Modify: `src/autoclip/models/job.py`（新增 regenerate_count 字段）
- Create: `tests/unit/test_self_evaluate_parse.py`
- Create: `tests/integration/test_regenerate.py`

**测试策略**:
- 单元: self_evaluate JSON 解析 / 缺字段降级 / overall 自动计算
- 集成: regenerate 后 ingest/index 不重跑 / regenerate_count 累加 / 第 4 次 regenerate 返回 429

**验收标准**:
- [ ] 自评分 JSON 落盘正确
- [ ] result.html 显示评分 + feedback 文字
- [ ] 重生成功能可用且不重跑 ingest/index（验证耗时显著缩短）
- [ ] regenerate_count = 3 时再点击返回错误

**关联 KPI**: K4（用户可主动改善）/ K5（重生成减少手工调优时间）
**依赖**: M3.5 + M3.7 → **阻塞**: M4.5
**预估工时**: 1.5d

---

### M4.5 — 错误兜底完善 + 最终 KPI 验收

**目标**: 完善任意 stage 失败的错误提示和部分结果可下载逻辑；跑全量 11 项 KPI 验证，输出最终验收报告。

**关键设计决策**:
- **错误兜底完善**:
  - 每个 stage 失败时 state.json 的 error 字段必须包含:
    - 失败 stage 名
    - 错误类型（HTTPError / ParseError / TimeoutError / ValidationError）
    - 用户可读的中文提示（不是 raw stack trace）
    - 建议的下一步操作（"重试" / "联系开发者" / "更换更短的视频"）
  - **部分结果可用**: 即使 Render 失败，用户也能下载已生成的 timeline.json + 已合成的 TTS wav 包（zip）
    - result.html 的下载区分两种状态：
      - 完整成功 → 显示剪映草稿包
      - 部分成功 → 显示"部分结果"折叠区，列出可下载的中间产物
  - 错误友好化映射: `src/autoclip/utils/error_messages.py`，把异常类型 → 中文提示
- **最终 KPI 验收**:
  - 跑 `scripts/run_all_kpi.py` 自动汇总所有 11 项 KPI 数据:
    - K1, K2, K3 来自 M2b benchmark 输出（基于 M4.1 的 3 部作品 + M4.3 的 3 种风格 = 9 次跑的均值）
    - K4 来自 M4.2 的 scores.md
    - K5 来自 M4.1 的 e2e_report.json（手动调优时长字段）
    - K6 来自 M4.1 的 e2e_report.json（端到端耗时）
    - K7 跑 1 次 resume 集成测试验证
    - K8 跑 `pytest --cov` 拿覆盖率
    - K9, K10, K11 跑 `tests/integration/test_zero_knowledge.py` + `test_agreement_block.py`
  - 输出: `data/e2e_reports/final_kpi_report.md`，每项 KPI 对应一行（指标 / 目标 / 实测 / 状态 ✅/⚠️/❌）
  - **门禁**: P0 KPI（K1,K2,K3,K9,K10,K11）任一不达标 → MVP **不能发布**，进入 Week 6 buffer
- **更新总控文档**: 把所有 KPI 实测值写入 `2026-05-04-autoclip-plan.md` 第 4 节

**涉及文件**:
- Create: `src/autoclip/utils/error_messages.py`
- Modify: `src/autoclip/pipeline/runner.py`（失败时调 error_messages 转换）
- Modify: `src/autoclip/web/templates/result.html`（部分成功折叠区）
- Modify: `src/autoclip/api/jobs.py`（GET /api/jobs/{id}/partial-results 返回可下载的中间产物列表）
- Create: `scripts/run_all_kpi.py`
- Modify: `docs/plans/2026-05-04-autoclip-plan.md`（KPI 表填实测值）
- Create: `data/e2e_reports/final_kpi_report.md`（runtime 输出）

**测试策略**:
- 单元: error_messages 映射全覆盖（每种异常类型都有中文）
- 集成: 模拟 Render 失败，部分结果接口返回 timeline.json + tts/ 列表

**验收标准**:
- [ ] 6 个常见错误场景都有友好中文提示
- [ ] 部分结果接口返回正确
- [ ] **MVP 最终发布门禁**: P0 KPI（K1,K2,K3,K9,K10,K11）全部 ✅
- [ ] P1 KPI（K4-K8）至少 4 项 ✅，1 项 ⚠️ 可接受

**关联 KPI**: 全部 11 项最终验收
**依赖**: M4.1 + M4.2 + M4.3 + M4.4 → **阻塞**: 无（最终任务）
**预估工时**: 1.5d

---

## M4 总工时估算
| 任务 | 工时 |
|---|---|
| M4.1 3 部 E2E | 1.0d |
| M4.2 用户评分 | 0.5d（+异步等待朋友评） |
| M4.3 风格扩展 | 1.0d |
| M4.4 自评分+重生成 | 1.5d |
| M4.5 错误兜底+KPI 验收 | 1.5d |
| **总计** | **5.5d**（控制在 W5 内）|

## M4 完成时的 PR 描述模板
```
✨feat: M4 - E2E + style expansion + self-evaluation + KPI verification
    - T4.1 3-film E2E run with e2e_report collection
    - T4.2 User subjective scoring (self + blind friend review)
    - T4.3 Style presets expanded to 3 (plot_summary / humor_roast / serious_review)
    - T4.4 AI self-evaluation + one-click regenerate
    - T4.5 Error friendly messages + partial results download + final KPI report
    - All 11 KPIs verified: P0 100% green, P1 X/5 green
```

## ⚠️ M4 失败兜底
- **K4 < 4**：分析具体维度，对症调 prompt（plot_summary 退化 → 加强 few-shot；rhythm 差 → 强化"单句 8-15 字"约束）
- **K5 > 1h**：分析调优集中在哪个环节（绑定准确率？句子文本？时长漂移？），针对性回炉
- **K6 > 16min**：profiling 找瓶颈（通常是 ASR 或 LLM 调用），考虑并行化或缓存

## 🎉 Week 6 — Buffer 用途（M4 之后）
- **优先级 1**: 修复任何 P0 KPI 不达标的问题
- **优先级 2**: 修复 M4 暴露的 P1 问题
- **优先级 3**: 剪映兼容性边界场景（不同剪映版本测试）
- **优先级 4**: 性能调优（如果 K6 ⚠️）
- **优先级 5**: 文档收尾（README / 部署指南 / 用户手册）

## 🚀 MVP 正式发布前的 checklist
- [ ] 11 项 KPI 表全部实测填写
- [ ] P0 KPI 全部 ✅
- [ ] 总控文档 v0.2 + design.md v0.4（如有变更）
- [ ] 用户协议 v0.1 草稿走过法务（如已商业化预期）
- [ ] README 含部署指南 + .env 配置说明
- [ ] git tag `v0.1.0-mvp`

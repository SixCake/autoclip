# AutoClip Plan 索引（v0.4 多文档结构）

> 完整文档：[`../docs/plans/2026-05-04-autoclip-plan.md`](../docs/plans/2026-05-04-autoclip-plan.md) — **主控文档**（220 行）
>
> 子文档（按需读取）：
> - M1 `../docs/plans/tasks/M1-infrastructure.md`（8 任务，354 行）
> - M2a `../docs/plans/tasks/M2a-scripting-main.md`（6 任务，491 行）
> - **M2a-fix `../docs/plans/tasks/M2a-fix-narrative-style.md`（5 任务，372 行；v0.7 新增，6.7d，含 Q1-Q8 + 19 项 P0 修正）**
> - M2b `../docs/plans/tasks/M2b-scripting-robust.md`（v0.7 拆分后仅条件启动，0/4d；M2b-light 已并入 M2a-fix.5）
> - M3 `../docs/plans/tasks/M3-render-web-compliance.md`（9 任务，466 行）
> - M4 `../docs/plans/tasks/M4-e2e-validation.md`（5 任务，320 行）

## 当前阶段
**executing 阶段（M1.5 启动前 adhoc 修订完成）**。M1.1-M1.4 已完成（4/8 任务），下一步执行 M1.5 LocalWhisperProvider 实现。

**v0.2 plan 微调（2026-05-04 15:20 adhoc）**:
- ASR 默认从阿里云 NLS 切换为本地 faster-whisper + large-v3（design.md Part IV §21）
- MVP 阶段新增 LLM 角色推断（§22 ADR-009 路径 2，不做声纹）
- M1.5 工期 1.0d → 0.5d；总工期 -0.5d
- 受影响子文档：M1-infrastructure.md (M1.5 重写) + M2a-scripting-main.md (M2a.2/M2a.3 prompt 增强)

## 文档定位
- **主控文档**：进度总览 / 任务索引 / KPI 跟踪表 / 导航规则 / 风险登记
- **子文档**：每个 task 的「关键设计版」— 接口签名、数据结构、算法选择、文件清单、测试策略、验收标准、KPI 关联、依赖、工时（**不含实现代码**）
- **执行阶段才写代码**：subagent / 工程师按当时上下文实现，遵循子文档的关键设计

## v0.4 关键变化（vs v0.3 的预期）
- 旧：单文件 plan.md 含完整实现代码（3847 行）
- 新：主控（220）+ 5 子文档（共 1696 行）= 1916 行总量
  - 缩减 50%
  - 按需加载，避免上下文爆炸
  - 关键设计明确，实现交给执行阶段

## Pre-conditions（plan.md 启动前提）— 全部完成
- [x] design.md v0.1 完成
- [x] 3 个开放问题（Q1/Q2/Q3）已回答
- [x] design.md v0.2 完成（剪映草稿对接）
- [x] design.md v0.3 完成（多角度评审 12 项修订）
- [x] plan.md v0.4 完成（多文档重构）
- [ ] 用户 review v0.4 通过 → 进入 executing-plans

## 路线图速览
- **W1**: M1（基础设施 + Ingest + Index，8 任务，~7d）
- **W2**: M2a（Scripting 主链路，6 任务，~5.5d）
- **W3**: M2b（Scripting 鲁棒性 + KPI K1-K3 验证，5 任务，~6d）
- **W4**: M3（Render + Web + 零知识架构，9 任务，~10d → 并行后 ~7d）
- **W5**: M4（E2E + 风格扩展 + 自评分 + KPI K4-K6 验证，5 任务，~5.5d）
- **W6**: Buffer（KPI 验收 + 关键修复）

## KPI 验证依据
按 design.md §18.2 + 主控文档第 4 节 11 项 KPI 矩阵作为最终验收门禁。
P0（K1,K2,K3,K9,K10,K11）任一不达标 → MVP 不发布。

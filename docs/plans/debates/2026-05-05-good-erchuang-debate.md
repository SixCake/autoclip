# Multi-Role Debate: 什么是好的二创内容？如何系统性构建？

> **Date**: 2026-05-05  
> **Topic**: 什么是"好的二创内容"最核心的定义？如何系统性构建（而不是打补丁式修复）？  
> **Trigger**: autoclip v0.7 解说稿被用户判定"打地鼠式补丁、没有方向性"，要求先回答"什么是好二创"再动代码  
> **Skill**: `multi-role-debate`（重型档：5 角色 / high=4 round / med=3 round / 总 ≈ 50K tokens）  
> **Stage artifacts**:  
> - Stage 1: `2026-05-05-good-erchuang-stage1.json`  
> - Stage 2a: `2026-05-05-good-erchuang-stage2a.json`  
> - Stage 2b: `2026-05-05-good-erchuang-stage2b.json`  
> - Stage 2c: `2026-05-05-good-erchuang-stage2c.json`  
> - Stage 3a: `2026-05-05-good-erchuang-stage3a.json`  
> - Stage 3b: `2026-05-05-good-erchuang-stage3b.json`

---

## TL;DR — 给赶时间的你

**"好二创"的工程隔离定义**（chair 仲裁 P0-5）：
> 好二创 ≠ 描述句堆砌；好二创最低门槛 = **至少 1 个判断式钩子（前 5 句内）+ 段落主体的判断句占比 > 描述句占比**；其余事后看反例库 + 锚点案例。
> ⚠️ 此定义只能出现在 design.md 与 docs/anchors/README.md，**不得进入任何 prompt 文件、不得进入任何 evaluator 评分公式**（防退化条款）。

**核心范式转移**（5 角色一致 U6）：
> autoclip v0.8 任务从"一次性生成完整稿"→ **Stage1（钩子+骨架，独立可交付）→ Stage2（按推断人格生成判断句序列，失败优雅降级到 Stage1）**。

**判断句 vs 描述句**（5 角色一致 U5）——这是 AI 二创的语言学根因：
> 把句子加上"XX（作者名）认为"前缀仍成立 = 判断句 = 好二创内核；陈述事实/动作/画面 = 描述句 = AI 味根因。autoclip 当前输出 100% 描述句。

**人格库**（5 角色一致 U7）：
> 5-8 种封闭人格库（毒舌中年 / 治愈大姐 / 考古学家 / 暴躁老哥 / 共情学姐 / ...，含 ≥1 种"冒犯型"），每条人格在 `docs/personas/` 落 markdown 文件，含 5-10 条真人 reference 台词供 LLM RAG 引用。

---

## 1. 角色阵容

| # | 角色 | 来源 | 在辩论中的关键作用 |
|---|---|---|---|
| 1 | **B 站百万二创 UP 主**（5 年从业、单条 800 万播放） | adapted | 提出"人格在场" + "三步骤强依赖（人格→价值观→技巧）" + 人格库提议（C1-R3）|
| 2 | **B 站资深内容 PM**（5 年中视频/影视区） | adapted | 提出"4 类二创分类（信息/情绪/观点/身份）" + 目标用户痛点优先 + 目标分 75/85 分层 |
| 3 | **25 岁重度二创消费者**（80+ UP 关注、3 秒划走判官） | adapted | 提出"判断句 vs 描述句"语言学锚点 + "XX 认为前缀法" + ≥1 冒犯型人格 |
| 4 | **Devil's Advocate**（系统性反对者） | library | 引证 3 个失败案例（今日头条/简书/抖音工厂）+ 主张缩小任务边界 + 防"评估器反向蒸馏 prompt" |
| 5 | **Future Self**（6 个月后维护 autoclip 的我） | library | 引证 autoclip v0.5→v0.7 已积累 3 套并存系统 + 强制 sunset 条件 + 工程隔离条款 |

**故意排除**：Senior Engineer（用户指示先讨论"好二创"本身，不议工程边界）。  
**未覆盖维度**：法务/版权、CFO 单位经济学（不在本议题范围）。

---

## 2. Stage 1 — 5 角色独立立场（精炼版）

| 角色 | stance | "好二创"一句话定义 | 对"建方法论"态度 |
|---|---|---|---|
| UP 主 | 反对（反模式过滤路线）| 让观众感受屏幕背后有"具体的人"在用 ta 的视角重讲——**人格在场** | 应建，但先定人格+价值观再谈技巧 |
| PM | 有保留 | **没有单一定义**——必须先选 4 类（信息/情绪/观点/身份）中的 1-2 类作为定位 | 可建，但目标用户痛点要先定 |
| 消费者 | 反对（当前内容质量）| **句句是判断不是描述**——"XX 认为"前缀仍成立 | 不懂方法论，只看每句能否还原为判断 |
| Devil | 反对（建方法论本身）| "好二创"是回顾性判断，前瞻性配方不存在——这是**错问题** | **不要建，要缩小任务边界** |
| Future Self | 有保留 | **可被否决的最简定义**：让特定读者群 ≥30% 产生 1 个具体情绪反应 | 可建，但今天必须落字 3 件事（定义/锚点/sunset）|

> 完整 5 角色 JSON（含 concerns + evidence + answer_to_topic）见 `2026-05-05-good-erchuang-stage1.json`

---

## 3. Stage 2 — 7 个冲突 + bounded back-and-forth 解决记录

| ID | type | severity | rounds | resolution | 关键产出 |
|---|---|---|---|---|---|
| **C1** | explicit | high | 3 | ✅ resolved | 好二创 = 判断式钩子（前 5s）+ 判断句序列 + 5-8 人格库（含 ≥1 冒犯型） |
| **C2** | explicit | high | 4 | ⚠️ stalemate → chair | design.md 是否允许"前瞻性定义" |
| **C3** | priority | high | 3 | ✅ resolved | autoclip v0.8 = Stage1 独立可交付 + Stage2 优雅降级 + 目标分 75 |
| **C4** | path | med | 2 | ✅ resolved | R1-R6 改作用域为 Stage1 floor check + 每 R 带 sunset + 废 K-style-1 hard gate |
| **C5** | assumption | high | 4 | ⚠️ stalemate → chair | open_question 措辞是否含"pivot 成本可控" |
| **C6** | priority | med | 1 | ✅ resolved | 4 件并列产出，无优先级争议 |
| **C7** | assumption | high | 2 | ✅ resolved | 人格库 + 5-10 条真人 few-shot reference + RAG |

> 完整轮次记录（每轮发言+让步/反驳轨迹）见 `2026-05-05-good-erchuang-stage2c.json`

---

## 4. Stage 3a — 10 项 Unanimous 一致结论

### 诊断共识（4 项）

- **U1**：R1-R6 反模式过滤是"下限保护"，不是"上限突破"；hit_rate ≤ 10% hard gate **必须废止**
- **U2**：autoclip 输出"旁白热情欢迎小朋友，今天要学四种动物叫声" = 公认反例（4 个 AI 味标志同时出现：上帝视角 + 套话情绪 + 教学口气 + 陈述事实零钩子）
- **U3**：autoclip 输出"反差，绝了！猫的声带是被牛借走了吗？" = "刚达标但仍是 AI 味"（堆 B 站黑话词，技术合规但价值空洞）
- **U4**：autoclip v0.5→v0.7 已积累 3 套并存的"风格描述系统"，**规则系统已饱和**（每加 1 条规则 0.7 天内出现 1 次回滚）

### 定义共识（2 项）

- **U5**：**判断句 vs 描述句是 AI 二创的核心区分维度**——把句子加"XX 认为"前缀仍成立 = 判断句；当前 autoclip 100% 描述句
- **U7**：人格 = 5-8 种封闭人格库 + 每条配 5-10 条真人 few-shot reference + 含 ≥1 种冒犯型

### 架构共识（2 项）

- **U6**：autoclip v0.8 任务架构 = **Stage1（钩子+骨架，独立可交付）→ Stage2（判断句+人格，失败优雅降级到 Stage1）**
- **U8**：废 K-style-1 hit_rate hard gate；新过线标准 = "反例库零命中 + 钩子是判断式（人工或独立 LLM 评判）"；R1-R6 模块改名为 `stage1_floor_check.py`

### 交付共识（2 项）

- **U9**：建立 `docs/anchors/`：good_examples.md（≥3 条具体台词锚点：木鱼水心《大话西游》、刘老师《情书》、LKs 开场公式）+ anti_examples.md（U2 + U3 入库）
- **U10**：4 件并列产出无优先级争议（反例库 / personas / anchors / 每 R sunset）

---

## 5. Stage 3b — Chair 仲裁结论（处理 C2 + C5 stalemate）

### 仲裁 C2（design.md 是否允许"前瞻性定义"）→ **adopt_with_modification**

**决议**：保留"反向定义 + 反例库"，但**强制工程隔离**：定义不进任何 prompt 文件、不进任何 evaluator 评分公式，仅进 `docs/anchors/README.md`（人工 review checklist）。

**最终定义文本**：
> 好二创 ≠ 描述句堆砌；好二创最低门槛 = 至少 1 个判断式钩子（前 5 句内）+ 段落主体的判断句占比 > 描述句占比；其余事后看反例库 + 锚点案例。

**理由**：
- Future Self（C2-R4）"必须有反向定义"是维护性硬约束（6 个月后无法判断 patch 是升级成规则还是丢掉）
- Devil（C2-R2）"任何前瞻性定义都会被工程师转化为约束"是真实历史规律（autoclip v0.5→v0.7 已发生 3 次描述→约束退化）
- Chair 决议通过"工程隔离条款"两全：定义存在但物理位置和评分体系隔离

**支持**：Future Self / UP 主 / PM  
**保留异议**：Devil's Advocate（仍主张"仅反例库无定义"，但接受工程隔离作为防退化兜底）

### 仲裁 C5（open_question 措辞）→ **adopt**（采纳 Devil 版本）

**决议**：open_question 措辞 = "当 v1.0 前用户使用率 < X% 时，重新评估 autoclip 目标用户假设（创作者侧 vs 消费者侧）"——**删除 PM 提议的"pivot 成本可控"乐观陈述**，但补加 P2-1 任务（独立的 pivot 成本评估）让 PM 实质关切落地。

**理由**：Devil（C5-R3）"没数据不要写让人放心的数字"是 GLOBAL_MUST_NOT 第 6 条（NO 编造证据）的直接应用。

**保留异议**：PM（仍认为"pivot 成本可控"是必要现实判断）

---

## 6. Corrections — 11 条可执行修正（按优先级排序）

> 全部 corrections 都可追溯到 unanimous 或 chair_decided（NO chair-invented corrections）。

### P0（6 条，必须做）

| ID | desc | owner | source |
|---|---|---|---|
| **P0-1** | 重写 design.md §17.6 为两阶段 LLM v2 架构（Stage1 独立可交付 + Stage2 优雅降级 + Stage1 必须有产品 UI 体现）| PM + Future Self | unanimous (U6) |
| **P0-2** | 删除 K-style-1 hard gate (hit_rate ≤ 10%)；R1-R6 模块改名 `stage1_floor_check.py`，作用域限定 Stage1，零容忍命中 | Future Self | unanimous (U1+U8) |
| **P0-3** | 新建 `docs/personas/` + 5-8 种封闭人格库（每个 .md 含人格描述 + 5-10 真人 reference + 适用题材 + 失败信号 + ≥1 冒犯型）| UP 主 | unanimous (U7) |
| **P0-4** | 新建 `docs/anchors/` + good_examples.md（≥3 条：木鱼水心/刘老师/LKs）+ anti_examples.md（U2+U3）| 消费者 + Future Self | unanimous (U9) |
| **P0-5** | 在 design.md 写入"好二创工程隔离定义" + 禁入约束（CI 检查 `grep 'judgment ratio' src/autoclip/prompts/` 必须为空）| Future Self | chair_decided (C2) |
| **P0-6** | 为 R1-R6 每条规则在 `stage1_floor_check.py` 文件头强制写 sunset 注释 + CI 检查（新规则缺 sunset 即 lint fail）| Future Self | unanimous (U8) |

### P1（3 条，强烈推荐）

| ID | desc | owner | source |
|---|---|---|---|
| **P1-1** | 新建 `src/autoclip/algo/persona_inferer.py`：Stage1 LLM 输入=ASR+视觉关键帧，输出=推荐人格 + 钩子候选 ≥3 + 段落骨架 | Future Self + UP 主 | unanimous (U6+U7) |
| **P1-2** | 新建 `docs/anchors/README.md`：写入 P0-5 定义 + 人工 review checklist（每段 ≥1 判断句 / 钩子是判断式 / 套人格 / 触发反例库）| 消费者 + Future Self | chair_decided (C2) |
| **P1-3** | 在 design.md §17.x 写入目标分三档：Stage1 单独 = 75 分（素人怕丢人）；Stage1+Stage2 = 85 分；Stage2 失败降级仍须 ≥75 | PM | unanimous (U6) |

### P2（2 条，nice-to-have）

| ID | desc | owner | source |
|---|---|---|---|
| **P2-1** | v1.0 前的 pivot 成本评估独立任务（评估 v0.8 共识对"消费者侧 autoclip"的复用率）| PM | chair_decided (C5) |
| **P2-2** | v0.8 季度 review 机制：每 3 月扫一次 R 规则的 sunset 条件触发情况，到期则废止 | Future Self | unanimous (U4+U8) |

---

## 7. Open Questions — 需要你决策的 2 个问题

### OQ1：是否在 v1.0 前留"目标用户假设重评估"trigger？

| 选项 | 支持角色 | trade-off |
|---|---|---|
| A. 保留为 v1.0 前 trigger（按用户使用率阈值触发 review）| Devil / Future Self | 防止沦为 5 年来失败的 AI 二创工具行列；代价是有"pivot 风险"背景音 |
| B. 锁定创作者侧不再 review（直至 v1.0 后）| PM | 团队聚焦不分心；代价是 6 个月后真要 pivot 时所有 v0.8 共识需推翻 |
| C. 现在并行做"消费者侧 autoclip"低成本 spike（≤2 周 + 仅 prompt 实验）| Devil（隐含）| 打消顾虑且小成本；代价是稀释 v0.8 注意力 |

**Decision required by**：v0.8 启动前

### OQ2：v0.8 P0 工作流的起手顺序？

| 选项 | 支持角色 | trade-off |
|---|---|---|
| A. 数据先行（personas + anchors → Stage1/Stage2 重构）| Future Self / UP 主 | 代码端可见进度推迟 1-2 周；新架构启动时已有 ground truth |
| B. 架构先行（Stage1/Stage2 + 兜底降级，personas 用最小可用集）| PM | 用户最快感知改动；代价是 personas 在 v0.8 内是次品 |
| C. 并行（数据组 + 架构组同时启动）| —— | 最快但需协调成本；适合 1+ 工程师 |

**Decision required by**：executing-plans 启动前

---

## 8. 元数据 + 成本审计

| 项 | 值 |
|---|---|
| stage1_tokens（5 角色独立立场）| ~22K（每角色 ~4.4K，重型档 ~3K out + 1.5K in） |
| stage2a_tokens（rule-based）| 0（纯 Python） |
| stage2b_tokens（M2 prompt）| ~4K |
| stage2c_tokens（28 round-utterance）| ~22K |
| stage3a_tokens（rule-based）| 0（纯扫描） |
| stage3b_tokens（M4 chair）| ~6K |
| **总计** | **~54K tokens（接近重型档预算 50K，可接受）** |
| LLM call count | 5 + 1 + ~28 + 1 = **35 调用** |

---

## 9. Hand-off — 建议的下一步

按 SKILL.md Step 5（hand off 决策树）：

### 路径 A（推荐）：先决策 OQ1+OQ2，然后 `executing-plans`

1. **你回答 OQ1 + OQ2**（约 2 分钟决策）
2. 我用 `writing-plans` skill 把 11 条 corrections + 你的 2 个决策合并为一份 v0.8 实施 plan（替代当前 `docs/plans/2026-05-04-autoclip-plan.md` 的 M2a-fix.2-fix.5）
3. 切换 `executing-plans` skill 按 batch 执行（建议每批 3 条 corrections）

### 路径 B：先二次 `brainstorming`

如果 OQ1 你倾向选项 C（"并行做消费者侧 spike"），那目标用户假设就需要在动 P0 工作前再开一轮 brainstorming，避免 P0 实施完成后才发现产品方向变了。

### 路径 C：暂停一切代码工作，先建数据资产（personas + anchors）

如果 OQ2 你选 A（数据先行），那 v0.8 第一周就只做 P0-3 + P0-4 两件，连 design.md 重写都暂缓——这是 Future Self 倾向的最稳路径。

---

## 10. 给你的元层反思

回到你的原始批评："你现在的操作只看表面，没有根本解决问题，二创内容应该从情感、价值等多方面因素考虑。"

这场 debate 的核心收获**不是**"找到了二创的 N 维度方法论"——恰恰相反，5 个角色一致拒绝了"加新维度"的诱惑：

1. **Devil 论证**：方法论化 = 规则化 = 平均化（今日头条 / 简书 / 抖音工厂三个失败案例）
2. **Future Self 论证**：5 维度（情感/价值/结构/视角/触达）会在 3 个月内坍缩为 2 维度，徒增维护成本
3. **UP 主 + 消费者**：好二创只有 1 个内核——**判断句 / 人格在场**，其他都是这个内核的外围效应

所以你的"打地鼠"批评的真正答案，**不是建立更高抽象层的方法论**（那只是更高层的打地鼠），而是：
- ✅ **任务边界缩小**（Stage1 独立可交付，不再追求"一次性生成完整稿"这个不可达目标）
- ✅ **语言学锚点**（判断句 vs 描述句这一条比 R1-R6 全套都管用）
- ✅ **数据资产先行**（人格库 + 锚点案例集 + 反例库，不靠规则靠样本）
- ✅ **工程隔离条款**（防止任何"好定义"被反向蒸馏成 prompt 约束）

这是 5 个角色经过 7 轮 conflict、35 次 LLM 调用辩出来的方向——**比任何单角度的"5 维度方法论"都更对得起你那句批评**。


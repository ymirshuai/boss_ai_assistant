# Agent 模式设计文档（BOSS 直聘 AI 助手）

> 状态：设计定稿（待实施）
> 目标：把"用户在 BOSS 直聘上的常见求职目标"映射到"Agent 可调用工具"，并定义安全模型与架构接法。
> 基础代码：`agent_mode.py`（FnCallAgent + AgentContext）、`agent_tools.py`（6 个已有工具）、`main.py:run_campaign`（已解耦的主循环）、`airtest_connector.py:handle_common_exception`（回到主页）。

---

## 1. 目标体系（G1–G5 + 安全约束）

| 类别 | 用户目标 | 说明 |
|---|---|---|
| **G1 海投获客** | 主动找岗位、批量打招呼、扩大曝光 | 搜索 / 浏览岗位 |
| **G2 跟进转化** | 回复 HR、发简历/微信、约面试，推进沟通 | 查消息 + 回消息 |
| **G3 信息沉淀与复盘** | 记录 HR 信息、查/导出数据、**聚合分析**（共性/回复率/话术效果） | 存、查、析 |
| **G4 策略配置** | 调匹配规则/人设、设置运行策略（岗位/数量/时段）、拉黑不合适公司 | 用户侧给 agent 下指令 |
| **G5 准备与练习（独立目标）** | 模拟 HR 提问 → 用户回答 → 落库；模拟面试题 → 用户预演 | 给 G1/G2 攒"弹药" |
| **安全约束（非目标）** | 限流 / 自暂停 / 异常熔断 / 强制停止 | 运行时健壮性，单列硬规则 |

---

## 2. 安全模型（核心决策）

**不做任何二次确认。** 取而代之两条硬规则：

1. **任意时刻可强制停止**
   - `AgentContext` 持有 `stop_requested` 标志；用户点"停止"即置位。
   - 所有**触屏工具**在循环内持续检查该标志，置位立即中止，并调用 `handle_common_exception()` 回到主页。
   - 复用现有 Web UI 停止按钮（`self.running=False` + 可中断睡眠）作为底座；agent 工具读同一标志。
2. **触屏工具在开始与结束时必调 `handle_common_exception()`（`airtest_connector.py:153`）回到主页**
   - 保证任何异常/半截状态都不会停留在奇怪页面，下一轮从干净主页开始。

> 设计取舍：用户信任 agent 直接执行，但永远握着"急停"和"回家"两张牌。比"逐动作确认"更顺、更适合真机无人值守片段。

---

## 3. 工具清单总览（12 个）

- **已有 6 个**（其中 2 个本次新增"是否打招呼"开关）：`search_jobs`、`browse_jobs`、`view_messages`、`db_operation`、`modify_prompt`、`save_info`
- **新增 6 个**：`analyze_jobs`、`run_campaign`、`blocklist`、`view_resume`、`mock_hr_questions`、`mock_interview_questions`
- **修改 2 个**：`search_jobs` / `browse_jobs` 增加 `greet: bool` 开关

| 目标 | 工具 | 触屏 | 状态 |
|---|---|---|---|
| G1 | `search_jobs(keyword, greet=False)` | ✅ | 改（加开关） |
| G1 | `browse_jobs(greet=False)` | ✅ | 改（加开关） |
| G2 | `view_messages()` | ✅ | 已有 |
| G3 | `save_info(items)` | ❌ | 已有 |
| G3 | `db_operation(operation, params)` | ❌ | 已有 |
| G3 | `analyze_jobs(...)` | ❌ | **新** |
| G4 | `modify_prompt(action, name, text)` | ❌ | 已有 |
| G4 | `blocklist(company_or_job)` | ❌ | **新** |
| G4 | `run_campaign(keyword, target_greet_count, duration, search_enabled)` | ✅ | **新**（复用 main.py 已解耦函数） |
| G5 | `view_resume()` | ❌ | **新** |
| G5 | `mock_hr_questions(resume_text, count=5)` | ❌ | **新**（由 mock_hr_qa 拆出） |
| G5 | `mock_interview_questions(target_job_jd, count=5)` | ❌ | **新**（由 mock_hr_qa 拆出） |

---

## 4. 工具详细签名

### 4.1 已有工具（含本次改动）

**`search_jobs(keyword="", greet=False)`** — G1
- 触屏 ✅；开始/结束调 `handle_common_exception()`。
- `greet=False`：纯搜索+浏览，不触屏打招呼；`greet=True`：浏览中顺带打招呼。
- 返回：`{"browsed": int, "greeted": int, "stopped_by_user": bool, "error": str|null}`

**`browse_jobs(greet=False)`** — G1
- 同 `search_jobs` 的开关语义；浏览主页推荐岗位。
- 返回：同上结构。

**`view_messages()`** — G2
- 触屏 ✅；检查红点 → 读消息 → 用 `MessageReplier` 回复。
- 返回：`{"checked": int, "replied": int, "stopped_by_user": bool, "error": str|null}`

**`db_operation(operation, params)`** — G3（已有，不改签名）
- 操作：`list_jobs` / `get_job` / `get_chat_history` / `get_daily_summary` / `export`。
- 不触屏。

**`modify_prompt(action, name, text)`** — G4（已有，不改签名）
- `action=get|update`；改系统提示/匹配规则/人设。不触屏。

**`save_info(items)`** — G3（已有，不改签名）
- 把结构化信息（HR 透露的、用户在 mock 中补充的）写入资料库。不触屏。

### 4.2 新增工具

**`analyze_jobs(scope="today", metric=None)`** — G3（聚合分析，补"析"的缺口）
- 不触屏。
- 入参：`scope`（today/all/keyword）、`metric`（common_traits / reply_rate / wording_effect，缺省全给）。
- 返回：`{"common_traits": [...], "reply_rate": float, "top_wording": [...], "summary": str}`
- 数据源：`db_operation` 导出的 `data_backup.json` / 资料库。

**`run_campaign(keyword, target_greet_count, duration, search_enabled)`** — G4
- 触屏 ✅；复用 `main.py` 已解耦的 `run_campaign`。
- **规范行为**：浏览岗位并打招呼，**同时每浏览 2 个岗位查看并回复新消息**；受**数量 + 时长**限定；**结束回传结果给 agent**。
- 开始/结束调 `handle_common_exception()`；循环内检查 `stop_requested`。
- 返回：
  ```json
  {
    "ok": bool,
    "stopped_by_user": bool,
    "error": str|null,
    "summary": "一句话结论",
    "this_run": { "browsed": int, "greeted": int, "replied": int },
    "today":    { "browsed": int, "greeted": int, "replied": int }
  }
  ```
  > 去除"检测到的消息数"字段；浏览/打招呼/回复三类指标各自分"本次"与"今日"双计数。

**`blocklist(company_or_job)`** — G4
- 不触屏（写一份 blocklist 配置/表）。
- 入参：公司名或岗位标识；`action=add|remove|list`。
- 返回：`{"ok": bool, "blocked": [...], "error": str|null}`
- 生效点：`search_jobs`/`browse_jobs` 在浏览时跳过 blocklist 命中项。

**`view_resume()`** — G5
- 不触屏；读取 `资料库/` 下当前用户简历（如 `罗帅简历_AI应用开发_优化版.md`）。
- 返回：`{"resume_text": str, "name": str, "file": str}`

### 4.3 拆分后的 mock 双工具（G5）

> 原 `mock_hr_qa` 拆为两个独立工具；**简历 + 目标岗位均为必须**。JD 来源由 agent 自决（见 5.2）。

**`mock_hr_questions(resume_text, count=5)`** — G5
- 不触屏。
- 基于简历，**专挑资料库里没有的个人信息 / 经历 / 离职原因 / 期望**来提问。
- 返回：
  ```json
  { "hr_questions": [ { "q": str, "suggested_answer": str, "gap": "该信息资料库是否缺失" }, ... ],
    "saved": bool }
  ```
- 流程：工具产出"题+参考答案" → agent 抛给用户收集真实回答 → 确认后 `save_info` 回填资料库（`saved=true`）。

**`mock_interview_questions(target_job_jd, count=5)`** — G5
- 不触屏。
- 基于**目标岗位详细 JD**，出**技术类 / 具体工作情况（场景题）**面试题。
- 返回：
  ```json
  { "interview_questions": [ { "q": str, "category": "技术|工作情况", "suggested_answer": str }, ... ] }
  ```
- 目的：帮用户预演可能遇到的面试问题（不直接落库，仅供练习）。

---

## 5. mock 工具与 JD 来源

### 5.1 HR 问题 vs 面试问题（两类目的不同）

| 类型 | 问题方向 | 输入来源 | 目的 |
|---|---|---|---|
| HR 问题 | 经历、个人信息、离职原因、期望 | 简历（找缺口） | **补充资料库里没有的信息** |
| 面试问题 | 技术类、具体工作情况/场景题 | 目标岗位详细 JD | **帮用户了解可能遇到的面试题** |

### 5.2 JD 来源由 agent 自决（可搜库 / 可搜岗）

`mock_interview_questions` 只收 `target_job_jd` 参数（纯生成，不自己触屏）。JD 怎么来，**agent 自己决定**：
- **搜库**：调 `db_operation(list_jobs)` / `get_job` 取已记录的岗位 JD；
- **搜岗**：调 `search_jobs(keyword, greet=False)` / `browse_jobs(greet=False)` 实时抓目标岗位 JD 文本，再喂给 `mock_interview_questions`。

> 这保持"mock 工具不触屏、职责单一、可测试"，也符合"只有触屏工具才调 `handle_common_exception()`"的边界。

---

## 6. Agent 架构与接法

### 6.1 基础（已存在，`agent_mode.py`）
- `FnCallAgent` + `function_list=tools` + `system_message`（来自 `get_system_prompt()`）。
- 工具通过 `AgentContext` 包装业务模块（`JobBrowser` / `MessageReplier` / `RAGEngine` / `data_store` …），agent **不直接操作屏幕坐标**。
- 主循环 `run_agent_mode(ctx, initial_message, max_rounds=30)` 迭代 `bot.run(messages)` 直到模型不再调工具或达轮次上限。

### 6.2 本次需扩展的点
1. **注册新工具**：`build_agent` 的 `tools` 列表补 `analyze_jobs / run_campaign / blocklist / view_resume / mock_hr_questions / mock_interview_questions`；`AgentContext` 补对应方法（含 `stop_requested` 标志与 `handle_common_exception()` 调用）。
2. **强制停止贯通**：`AgentContext.stop_requested`；所有触屏 ctx 方法（`search_jobs`/`browse_jobs`/`view_messages`/`run_campaign`）循环内检查，置位即中止并回家。Web UI 停止按钮写同一标志。
3. **目标态（goals）**：维护一份目标进度（G1–G5 哪些已完成 / 进行中），供 agent 决策"下一步该调哪个工具"与向用户汇报。
4. **`run_campaign` 桥接**：agent 调 `run_campaign` 即唤起主循环；结束拿回 `this_run/today` 结果，用于汇报与更新 goals。

### 6.3 Web UI 消息框接法（预留的第 4 面板）
- 已有 `POST /api/agent/chat`（占位）。改为：接收用户消息 → 追加进 `bot.run(messages)` 继续对话 → 以 SSE / 流式回传 agent 回复与工具调用日志（复用 `log_broadcast`）。
- "停止"按钮 → `AgentContext.stop_requested = True` + `BOSSAssistant.running = False`。
- 目标面板：前端读 `GET /api/agent/goals` 展示 G1–G5 进度；`run_campaign` 进行时读 `GET /api/campaign/status` 展示最新 `this_run/today` 与截图。

---

## 7. 实施分期

- **Phase 1（工具层）**
  - 新增 6 工具 + `AgentContext` 方法；`search_jobs`/`browse_jobs` 加 `greet` 开关。
  - `AgentContext` 加 `stop_requested`；触屏方法接通强制停止 + `handle_common_exception()`。
  - `blocklist` 在 `search_jobs`/`browse_jobs` 中生效。
  - 单测：每个工具签名 + 委托 + 停止标志响应。
- **Phase 2（对话 + UI）**
  - `/api/agent/chat` 流式对话；目标面板；`run_campaign` 进度实时展示。
  - `analyze_jobs` 聚合实现（读 `data_backup.json`）。
- **Phase 3（深化）**
  - goals 自动推进与建议；`mock_*` 与 `save_info` 闭环；`analyze_jobs` 反哺 `modify_prompt`（话术调优）。

---

## 8. 开放约定（已拍板，留作实现约束）
- 不做二次确认；只做强制停止 + 回家不变量。
- `run_campaign` 回传拆分"本次/今日"三类计数，无"检测消息数"字段。
- `mock_hr_qa` 已拆为 `mock_hr_questions`（简历必填）+ `mock_interview_questions`（JD 必填，来源 agent 自决）。
- 无定时跑（`schedule_campaign` 不实现）。

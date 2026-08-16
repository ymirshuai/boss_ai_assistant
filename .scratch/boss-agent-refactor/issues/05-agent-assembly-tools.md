# 05 — Agent 装配：三工具注册 + agent_mode 循环

**What to build:** 在 Qwen-Agent 中注册三个粗粒度工具 `search_jobs` / `browse_jobs` / `view_messages`，每个工具内部完成一条完整子流程（如 browse_jobs：识别字段 → 判匹配 → 打招呼）。`agent_mode` 循环驱动：LLM 读屏幕状态后决策调用哪个工具，工具跑通业务动作；Agent 不直接操作屏幕坐标。端到端跑通一次"浏览岗位"全流程。

**Blocked by:** 02 — 统一模型调用；03 — 本地 OCR 主路径 + 多维度兜底；04 — 本地知识库检索（资料库/）

**Status:** resolved

- [x] Qwen-Agent 注册 `search_jobs` / `browse_jobs` / `view_messages` 三工具
- [x] `agent_mode` 循环驱动：LLM 读状态 → 决策调工具 → 工具跑通完整子流程
- [ ] 端到端跑通一次浏览（识别 → 判匹配 → 打招呼）

## Resolution
- 新增 `agent_tools.py`：三个 `BaseTool` 子类（`search_jobs`/`browse_jobs`/`view_messages`，显式 `name`），
  经注入的 `ctx`（接口 `search_jobs(keyword)`/`browse_jobs()`/`view_messages()`）编排完整子流程；
  import-light，不触发 `airtest_connector` 的 `auto_setup`，便于单测。
- 新增/重写 `agent_mode.py`：`build_agent(ctx)` 用 `FnCallAgent` 注册三工具 + 系统提示词（离线可构造）；
  `run_agent_mode()` 驱动循环（默认指令「先查看消息再浏览岗位」，max_rounds 护栏）；
  `_build_default_ctx()` 复用现有业务模块（注意：真实运行才触发设备 `auto_setup`，单测注入假 ctx）。
- `job_browser.py` 新增 `search(keyword)`（从 `main.py` 的 `search_job_or_not` 抽出来复用）。
- 测试：`tests/test_agent_tools.py`（6 项：三工具编排、build_agent 离线注册、run 循环 mock）。
- **开放项**：`端到端跑通一次浏览` 需已连接安卓设备 + 可用 MaaS 网关（联网），沙箱无法验证；
  但工具各自调用的子流程（`JobBrowser.browse` / `MessageReplier.reply` / `JobBrowser.search`）与 agent 循环已通过 mock 验证。
  下一步可接 code-review，并在真机跑一次 `BOSS_MODE=agent python main.py` 做冒烟。

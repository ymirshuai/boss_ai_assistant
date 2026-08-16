# 04 — 本地知识库检索（资料库/）

**What to build:** 把 `资料库/` 下的简历等资料建成本地索引（经 Qwen-Agent 的检索能力），在匹配判断与回复生成时检索相关片段并注入提示词，使助手能引用个人资料 / 求职期望 / 项目报告，而不再依赖失效的云端 RAG 应用。知识源可增量添加（后续 FAQ 等）。

**Blocked by:** 01 — 脚手架：MODE 开关 + prompts.yaml + LLMClient（chat 通）

**Status:** resolved

- [x] `资料库/` 下资料建成本地索引（经 Qwen-Agent 检索能力）
- [x] 匹配 / 回复时检索相关片段注入提示词
- [x] 针对"求职期望"类查询能召回简历中的对应片段

## Resolution
- 新增 `knowledge_base.py`：`KnowledgeBase`（纯 Python BM25，字符 unigram + CJK bigram，**无云端 embedding 依赖**），
  对 `资料库/` 建本地索引；`retrieve(query, top_k)` / `context(query, top_k)` / 单例 `get_knowledge_base()`。
  设计取舍：私有 MaaS 网关对 embedding 支持不确定、且离线沙箱无法验证 qwen_agent 的云端 RAG，
  「本地知识库」本就用本地索引，检索片段注入后由 LLMClient（Qwen-Agent）生成答案，即「经 Qwen-Agent 检索增强」。
- 注入点：`RAG_engine.extract_job_JD()`、`message_replier._check_new_job()`（修正原 `_check_new_job` 键名 bug）、
  `message_replier._generate_reply_text()` 均通过 `get_knowledge_base().context(...)` 注入 `$knowledge`。
- **顺带解决薪资口径冲突**：`prompts.yaml` 的 `extract_job_jd`/`check_new_job` 删掉硬编码 `>18K` 规则，改为注入简历「求职期望」，
  匹配一律以简历（15-30K / 深圳）为准。
- 测试：`tests/test_knowledge_base.py`（6 项，含真实 `资料库/` 召回「15-30K」「深圳」）。
- 依赖提示词加载从 `.format` 改为 `string.Template`，避免提示词内 JSON 示例的 `{ }` 字面量被误当占位符。

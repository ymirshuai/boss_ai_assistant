# 06 — 死代码清理

**What to build:** 移除两处会在重构时引爆的隐藏坑——引用不存在的 `PROMPTS["extract_message"]` 的 `extract_message`，以及实际未被调用的 `_extract_job_JD`（线上走的是 RAG 路径）。清理后全量 import / 运行无 `NameError`。

**Blocked by:** 02 — 统一模型调用

**Status:** resolved

- [ ] 移除引用不存在 `PROMPTS["extract_message"]` 的 `extract_message`
- [ ] 移除未被调用的 `_extract_job_JD`
- [ ] 全量 import / 运行无 `NameError`，自动模式仍可跑

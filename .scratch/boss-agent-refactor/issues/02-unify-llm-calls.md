# 02 — 统一模型调用：OCREngine/RAGEngine 改走 LLMClient，删 app_id

**What to build:** 把原先两个互不一致、各自带容错的模型入口（直连 `dashscope` VL 的 `OCREngine`、带 `app_id` 的 `RAGEngine`）统一收口到 `LLMClient`（`vision` / `chat`）。删除已失效的云端 RAG 应用调用。字段抽取与匹配/回复判断行为与原先一致，但底层只走 Qwen-Agent 一个出口。

**Blocked by:** 01 — 脚手架：MODE 开关 + prompts.yaml + LLMClient（chat 通）

**Status:** resolved

- [ ] `OCREngine` 字段抽取改经 `LLMClient.vision`（复用统一重试/JSON 抽取）
- [ ] 原 `RAGEngine` 的匹配/回复生成改经 `LLMClient.chat`；移除带 `app_id` 的失效云端 RAG 调用
- [ ] 给定同一张截屏，字段抽取与匹配判断结果与改造前可比（行为不退化）

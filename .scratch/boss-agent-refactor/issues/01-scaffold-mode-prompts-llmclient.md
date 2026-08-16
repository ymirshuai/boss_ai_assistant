# 01 — 脚手架：MODE 开关 + prompts.yaml + LLMClient（chat 通）

**What to build:** 让助手在 `auto` 与原写死循环、以及新的 `agent` 入口之间用配置切换；把所有提示词外置到 `prompts.yaml` 并支持系统提示词可配置；建立一个统一的模型调用层 `LLMClient`，其 `chat` 方法经 Qwen-Agent 真实出字，并自带重试、超时、JSON 抽取与结构化日志。原自动模式行为保持不变（零回归）。

**Blocked by:** None — can start immediately

**Status:** resolved

- [ ] `config.MODE` 存在且取 `auto` / `agent`；`main.py` 顶层按值分派（auto 走原循环、agent 走新入口桩）
- [ ] `prompts.yaml` 被加载，系统提示词可配置（含求职期望/个人资料占位段）
- [ ] `LLMClient.chat(prompt)` 经 Qwen-Agent 真实返回文本；统一重试 / 超时 / JSON 抽取 / 日志就位
- [ ] `auto` 模式运行零回归（原有行为不变、无报错）

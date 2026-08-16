# 03 — 本地 OCR 主路径 + 多维度兜底

**What to build:** 将 `LocalOCREngine`（PaddleOCR，GPU 可选）作为详情识别的主路径接入；新增 `OCRService` 做多维度校验（抛异常 / 关键字段 job_title·company·salary 缺失或"未识别到" / 字段平均置信度 < 0.6 / 多图结构异常），任一命中即切换 `LLMClient.vision` 大模型兜底，并把兜底结果回填，保证下游始终拿到结构化字段。

**Blocked by:** 01 — 脚手架：MODE 开关 + prompts.yaml + LLMClient（chat 通）

**Status:** resolved

- [ ] `LocalOCREngine(GPU)` 作为详情识别主路径接入主流程
- [ ] `OCRService` 多维度校验实现；任一维度命中即切 `LLMClient.vision` 兜底
- [ ] 兜底结果回填结构化字段；有意构造的"空/低置信/异常"样例能正确触发兜底

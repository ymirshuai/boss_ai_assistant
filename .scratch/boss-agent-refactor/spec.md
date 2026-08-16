# Spec: BOSS 直聘助手 — Agent 模式与架构重构

> Status: ready-for-agent
> Feature slug: `boss-agent-refactor`
> Tracker: local-markdown (`.scratch/boss-agent-refactor/`)

## Problem Statement

现在的 BOSS 直聘助手只有一条用 Airtest 写死的"自动模式"循环（检测消息 → 浏览岗位 → 打招呼），所有状态机逻辑都硬编码在 `main.py` 里，没有大模型参与决策。用户（开发者）面临四个具体痛点：

1. **流程不灵活**：想让助手"先查消息再浏览""只回复不主动打招呼"等组合，只能改代码，无法由对话/模型动态编排。
2. **模型调用不统一**：OCR 字段抽取（`OCREngine`，直连 `dashscope` VL）和"匹配判断/回复生成"（`RAGEngine`，带 `app_id` 的 RAG 应用）是两个互不一致、各自带一套容错的入口，难维护、难复用。
3. **OCR 无兜底、无 GPU 利用**：本地 GPU 版 OCR（`local_ocr_engine.py`）早已写好却没接线；线上仍跑云端千问 VL，慢且贵。本地 OCR 即便"未识别到"也当作成功返回，错误被静默吞掉。
4. **提示词散落**：6 个内联字符串散在 `config.PROMPTS`，外加一个 `system_prompt.txt`，改一处要翻两处，且无法按环境切换。

## Solution

在**保留原自动模式**的前提下，新增一个 **Agent 模式**，由 Qwen-Agent 驱动：LLM 读屏幕状态后决定"下一步调哪个工具"，工具是粗粒度的完整业务动作。同时做三件地基工作：

- **统一模型调用层**：抽一个 `LLMClient`，对外暴露 `vision` / `chat` / `rag` 三个方法，统一重试、超时、JSON 抽取、错误日志；Qwen-Agent 作为唯一模型入口，去掉失效的 `app_id` RAG 调用。
- **本地 OCR 作主路径 + 大模型兜底**：`LocalOCREngine`（PaddleOCR，GPU）先跑；多维度判定失败才切 Qwen-Agent 视觉模型兜底。
- **提示词外置**：所有提示词收进 `prompts.yaml`，系统提示词可配置（含本地知识库内容，如简历/求职期望）。

知识库（个人资料/求职期望/项目报告）经 Qwen-Agent 在本地重建检索，不再依赖失效的云端 RAG 应用。

## User Stories

1. As a 开发者, I want 在 `config.MODE` 里切 `auto` / `agent`, so that 两种模式互不干扰、可随时回退且 auto 模式零回归风险。
2. As a 开发者, I want `auto` 模式继续走原 Airtest 写死循环, so that 老用户/回归测试不受影响。
3. As a 助手, I want Agent 模式下由 LLM 决定调用 `search_jobs` / `browse_jobs` / `view_messages`, so that 流程可按对话动态编排而非写死。
4. As a 助手, I want `search_jobs` 工具按写死关键词搜索岗位, so that 不会让 LLM 乱搜、浪费 token。
5. As a 助手, I want `browse_jobs` 工具内部完成"识别字段 → 判匹配 → 打招呼"完整子流程, so that Agent 只需在高层规划、不直接点屏。
6. As a 助手, I want `view_messages` 工具内部完成"读信 → 判意图 → 回复/发简历微信"完整子流程, so that 消息处理是一条可控链路。
7. As a 助手, I want 本地 OCR（GPU）作为识别字段主路径, so that 识别快、不花云端额度。
8. As a 助手, I want 当本地 OCR 抛异常时切换大模型视觉兜底, so that 异常不会中断流程。
9. As a 助手, I want 当关键字段（岗位名/公司/薪资）全为"未识别到"或空时切换兜底, so that 空结果不污染匹配判断。
10. As a 助手, I want 当字段平均置信度低于阈值（如 0.6）时切换兜底, so that 低质量识别被及时纠正。
11. As a 助手, I want 当多图解析结构异常时切换兜底, so that 布局变化时不被卡死。
12. As a 开发者, I want 所有模型调用经统一 `LLMClient`（vision/chat/rag）, so that 重试/超时/JSON 抽取逻辑只写一遍。
13. As a 开发者, I want 去掉带 `app_id` 的失效 RAG 入口, so that 不再调用已不可用的云端应用。
14. As a 助手, I want 本地重建知识库检索（经 Qwen-Agent）, so that 匹配判断能引用个人资料/求职期望/项目报告。
15. As a 开发者, I want 把简历等资料放进 `资料库/` 并由 RAG 检索, so that 知识源可增量维护（后续加 FAQ 等）。
16. As a 开发者, I want 所有提示词收进 `prompts.yaml` 且系统提示词可配置, so that 改提示词不必动代码。
17. As a 助手, I want 浏览页"两张卡片同框"时默认用 LLM 视觉主、本地 OCR 兜底, so that 弱解析场景不漏岗位。
18. As a 开发者, I want 每次模型调用和 OCR 兜底切换都有结构化日志, so that 出问题能追溯是哪一步、哪张图。
19. As a 开发者, I want Agent 模式按阶段（P0–P4）落地且每阶段 auto 仍可跑, so that 重构过程可随时停、可回退。
20. As a 助手, I want 匹配判断基于"求职期望"而非硬编码阈值, so that 期望变化时只改配置、不改逻辑。
21. As a 开发者, I want 清理现有死代码（引用不存在 `PROMPTS["extract_message"]` 的 `extract_message`、未被调用的 `_extract_job_JD`）, so that 重构不被隐藏 bug 绊倒。

## Implementation Decisions

- **双模式并存，config 开关**：`config.MODE` 取 `auto` 或 `agent`。`main.py` 顶层只做一件事——读 `MODE` 后分派到原循环或新 `agent_mode` 入口。两条路径共享底层设备/数据库/工具函数，互不打断。
- **Agent 模式由 Qwen-Agent 驱动**：注册粗粒度工具 `search_jobs` / `browse_jobs` / `view_messages`。Agent 负责"下一步调哪个"，工具内部编排感知与执行；Agent 不直接操作屏幕坐标。
- **统一模型调用层 `LLMClient`**：对外三方法——`vision(image, prompt)`（视觉字段抽取/兜底）、`chat(prompt)`（生成/判断）、`rag(query, docs)`（本地知识检索后作答）。封装统一重试、超时、JSON 抽取、错误日志。Qwen-Agent 的 model 对象是唯一模型出口。
- **移除失效 RAG 入口**：删除带 `app_id` 的云端 RAG 应用调用；"匹配判断/回复生成"改走 `LLMClient.chat` + 本地检索注入。
- **本地 OCR 主路径 + 多维度兜底**：`LocalOCREngine`（PaddleOCR，GPU 可选）先识别；校验函数对四个维度判定（异常 / 关键字段缺失 / 平均置信度 < 0.6 / 结构异常），任一命中即调用 `LLMClient.vision` 兜底。兜底结果回填，保证下游始终拿到结构化字段。
- **本地知识库检索（经 Qwen-Agent）**：`资料库/` 下的简历等作为语料建本地索引；匹配/回复时由 Qwen-Agent 检索相关片段注入提示词。知识源可增量添加（FAQ 等后续资料）。
- **提示词外置 `prompts.yaml`**：替代散落的 `config.PROMPTS` 与 `system_prompt.txt`；系统提示词可配置，并内联"求职期望/个人资料"等知识，使匹配判断基于配置而非硬编码。
- **两个明确拍板的边界**（可推翻）：
  - 搜索关键词写死在配置（如 `search_job`），Agent 暂不自定，避免乱搜。
  - 浏览页"两张卡片同框"本地 OCR 解析弱，`extract_card_list` 默认 LLM 视觉主、本地兜底。
- **死代码清理**：移除引用不存在 `PROMPTS["extract_message"]` 的 `extract_message`；移除未被实际调用的 `_extract_job_JD`（实际走的是 RAG 路径）。
- **开放问题（需用户定夺）**：简历写"期望 15–30K、深圳"，而 `config` 硬编码 ">18K"。两者冲突，影响匹配判断口径——以哪份为准待用户确认（建议以简历/`prompts.yaml` 的求职期望为准，config 阈值改为可配置）。

## Testing Decisions

- **好测试的定义**：只测外部行为（给定一张截图，工具产出正确字段/决策；给定一段消息，工具产出正确回复意图），不测内部实现细节（不测某个私有函数怎么拼 prompt）。
- **重点测的模块**：
  - `LLMClient`：用 mock 替代 `dashscope`/Qwen-Agent，验证重试、超时、JSON 抽取在坏响应下的行为。
  - `OCRService` 的多维度校验函数：构造"全空字段""低置信度""结构异常"等样例，验证兜底触发条件。
  - 本地 RAG 检索：用样例 query 验证能召回简历中的求职期望片段。
  - 工具编排（search/browse/view_messages）：mock 设备与模型，验证子流程顺序与决策分支正确。
  - 模式分派：验证 `MODE=auto` 走原循环、`MODE=agent` 走 Agent 入口。
- **测试底座**：代码库当前无测试，新增 `pytest` 与最小 fixtures（样例截图、样例消息 JSON）。优先在 `LLMClient` 与 `OCRService` 校验这两个最高 seam 上建测试，因为它们是跨模块共享、最该锁住的契约。

## Out of Scope

- 彻底删除/替换自动模式（本方案保留它）。
- 搭建超出本地文档的 RAG 基础设施（向量数据库服务、远程索引）——本期只做本地文件检索。
- 多账号、多平台（只面向 BOSS 直聘微信小游戏场景内的现有流程）。
- 云端部署、CI/CD 流水线搭建（本地运行与本地追踪器为主）。
- 搜索关键词的自适应生成（Agent 暂不自定搜索词）。

## Further Notes

### 测试 Seam（最高层、最少的跨码面）
- **Seam 1 — 模式分派**：`main.py` 顶层只按 `MODE` 分派，是回归测试唯一的入口缝。
- **Seam 2 — `LLMClient` 接口**：`vision/chat/rag` 三方法是所有模型行为的契约缝，mock 即可隔离屏幕与网络。
- **Seam 3 — `OCRService` 校验**：多维度判定是"本地 OCR ↔ 大模型兜底"的切换缝，纯函数、最易测。
- **Seam 4 — 工具编排**：三个粗粒度工具是 Agent 与屏幕之间的缝，mock 设备即可端到端验证流程。

（按技能流程，seam 已在此列出；拆分工单时会在 `to-tickets` 阶段向你确认粒度，不在此阻塞。）

### 推荐落地阶段（供 to-tickets 参考，非强制）
- **P0 脚手架**：`prompts.yaml` + `LLMClient` + 模式分派；auto 模式零改动可跑。
- **P1 统一调用**：`OCREngine`/`RAGEngine` 改走 `LLMClient`，删 `app_id` 入口。
- **P2 本地 OCR 接线 + 兜底**：`LocalOCREngine` 接入主路径，多维度校验 + 大模型兜底。
- **P3 本地 RAG**：`资料库/` 检索接入匹配/回复。
- **P4 Agent 装配**：Qwen-Agent 注册三工具，端到端跑通；清死代码。

### 已知事实（落地前已核实）
- 真实运行环境是项目根 `.venv`（Python 3.10.11）；`paddleocr 2.7.3` + `paddlepaddle-gpu 2.6.2`（GPU 已验证可用）+ `dashscope 1.26.2` 已在；`qwen-agent` 待装（T0 依赖，本次已后台重装）。
- `PyYAML 6.0.2` 已存在，写 `prompts.yaml` 零额外依赖。
- 本地 OCR 详情识别实测约 98% / 约 0.3s 每张，适合作主路径。

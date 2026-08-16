# BOSS 直聘助手 — 修改方案（Agent 模式 + 架构重构）

> 状态：方案待确认（grilling 已收敛 5 个关键分叉，未开始改代码）
> 目标环境：项目根 `.venv`（Python 3.10.11）、Windows + RTX 4070 / CUDA 12.0 + cuDNN 8.x
> 已具备：paddleocr 2.7.3、paddlepaddle-gpu 2.6.2（GPU 可用）、dashscope 1.26.2、PyYAML 6.0.2
> 待安装：qwen-agent

---

## 0. Grilling 收敛的决策（方案基石）

| # | 分叉 | 结论 |
|---|------|------|
| 1 | Agent 与自动模式共存方式 | **双模式并存**，`config.MODE` 开关切换；auto 走原脚本循环，agent 走 Qwen-Agent |
| 2 | 工具粒度 | **粗粒度**：每个工具 = 一个完整业务动作（内部含识别→判匹配→执行） |
| 3 | 大模型调用统一 | **去掉带 app_id 的 RAG 入口**（已失效）；**全走 Qwen-Agent**；新增可配置系统提示词 |
| 4 | 知识库（个人资料/求职期望/项目报告） | **本地重建 RAG**（经 Qwen-Agent 的检索能力），不再依赖云端 app |
| 5 | OCR 兜底触发条件 | **多维度判定**：异常 / 关键字段缺失 / 置信度过低 / 结构异常，任一命中即切 Qwen-Agent 视觉模型 |

> 你原始 4 点 + 第 6 点（优化提示词）全部覆盖；编号里的"5"你跳过了，这里按 1/2/3/4/6 落地。

---

## 1. 目标架构

```
                          config.MODE
                       ┌─────────────────┐
                       │  "auto" │ "agent"│
                       └────────┬─────────┘
                 auto           │           agent
   ┌─────────────────────┐      │     ┌──────────────────────────────┐
   │ main.py 现有 while  │      │     │ agent_mode.py (Qwen-Agent)    │
   │ 循环（保持不变）     │      │     │  Assistant/FnCallAgent        │
   └─────────────────────┘      │     │  system_prompt 来自 prompts.yaml │
                                │     │  goal: 查消息/浏览/匹配/打招呼   │
                                │     └───────┬───────────┬────────────┘
                                           工具层（粗粒度，每个=完整子流程）
                                ┌──────────────┼───────────────┐
                          search_jobs    browse_jobs     view_messages
                          (现有          (JobBrowser     (MessageReplier
                           search_job_    .browse 重构)   .reply 重构)
                           or_not 重构)
                                │                │                │
                                └────────┬───────┴────────────────┘
                                       ▼
                          ┌────────────────────────────┐
                          │  OCRService（统一入口）       │
                          │  ① LocalOCREngine(GPU) 主    │
                          │  ② 多维度校验               │
                          │  ③ 失败→ LLMClient.vision() │
                          └────────────┬───────────────┘
                                       ▼
                          ┌────────────────────────────┐
                          │  LLMClient（统一模型调用层） │
                          │  基于 Qwen-Agent            │
                          │  · chat()   文本/语义判断    │
                          │  · vision() 多模态 OCR 兜底  │
                          │  · rag()   本地知识库检索     │
                          │  统一：重试/超时/JSON抽取/日志│
                          └────────────────────────────┘
```

**关键边界**
- Agent 看不到屏幕，**工具**封装所有"感知+执行"。Agent 只做规划：先 `view_messages` 还是先 `browse_jobs`，根据工具返回决定下一步。
- 所有模型调用（OCR 兜底、匹配判断、回复生成、RAG 检索）**只**经 `LLMClient`，`LLMClient` 底层是 Qwen-Agent。原 `OCREngine._call_vl` / `RAGEngine._call_rag_image(app_id=...)` 两个分散入口被取缔。
- 业务动作（打招呼、发简历、发微信、返回）仍是确定性的 Airtest 屏幕操作，留在工具内部，**不让 LLM 直接点屏**。

---

## 2. 文件变更清单

### 新增
| 文件 | 职责 |
|------|------|
| `prompts.yaml` | 所有提示词 + `system` 系统提示词 + `knowledge` 知识（或指向知识文件路径）+ 模型/agent 配置。**替代 `config.PROMPTS` 与 `system_prompt.txt`** |
| `llm_client.py` | 统一模型调用层（Qwen-Agent 封装）：`chat()` / `vision()` / `rag()` + `extract_json()` + 重试/超时/错误日志 |
| `agent_mode.py` | 构建 Qwen-Agent Agent，从 `prompts.yaml` 载入系统提示词，注册 3 个工具，运行 agent 循环（带 max_iter / 超时护栏） |
| `ocr_service.py` | OCR 统一入口：先 `LocalOCREngine`，多维度校验，失败调 `LLMClient.vision` 兜底；对外暴露 `extract_card_list` / `extract_job_detail` / `extract_chat_header` |
| `local_rag.py` | 基于 Qwen-Agent 的本地知识库：建索引（资料 md/json）、`retrieve(query)` / `rag_answer(prompt)` |
| `tools/__init__.py` + `tools/job_tools.py` | 3 个粗粒度工具函数（`search_jobs` / `browse_jobs` / `view_messages`），内部复用现有业务方法 + `OCRService` + `LLMClient` |

### 重构
| 文件 | 改动 |
|------|------|
| `config.py` | 删除 `PROMPTS` 字典；新增 `MODE`、`AGENT_MODEL`、`OCR_USE_GPU`、`OCR_FALLBACK_MODEL`、`RAG_` 配置、知识库路径；保留 `DEVICE_CONFIG` / `BEHAVIOR_CONFIG` |
| `main.py` | 启动处读 `MODE`：auto→原循环；agent→`agent_mode.run()`；两个分支互斥、互不干扰 |
| `job_browser.py` | `browse()` 改用 `OCRService.extract_job_detail` + `LLMClient.chat`（匹配判断），去除对 `RAGEngine` 直连依赖 |
| `message_replier.py` | `reply()` / `_check_new_job()` / `_generate_reply_text()` 改用 `OCRService` + `LLMClient`，去掉 `RAGEngine` 直连；删 `extract_message` 死代码 |
| `ocr_engine.py` | 降级为"视觉兜底实现"，其 `_call_vl` 逻辑并入 `LLMClient.vision`；原文件可标记 deprecated 或删除 |
| `RAG_engine.py` | 删除 `app_id` 调用，改为调用 `local_rag`；或整体删除、逻辑迁入 `local_rag.py` |
| `local_ocr_engine.py` | 新增**置信度/有效性校验**：`validate(result)` 实现多维度判定（异常/关键字段缺失/平均 score<阈值/结构异常）；`extract_job_info_from_screenshots` 额外回传置信度估计 |
| `requirements.txt` | 增加 `qwen-agent`；`paddleocr`/`paddlepaddle-gpu`/`dashscope` 已满足 |

### 删除（确认后）
- `RAG_engine.py` 的 `app_id` 调用路径
- `ocr_engine.extract_message`（引用不存在的 `PROMPTS["extract_message"]`，死代码带 bug）
- `config.PROMPTS`、`system_prompt.txt`（内容迁入 `prompts.yaml`）

---

## 3. OCR 本地化 + 兜底（第 3 点）详细设计

**主路径**：`LocalOCREngine(use_gpu=True)` 已实测 ~0.31–0.44s/张、字段 ~98%。

**多维度"失败"判定（落在 `LocalOCREngine.validate` / `OCRService`）**：
1. 调用抛异常；
2. 关键字段 `job_title` / `company` / `salary` 全为 `"未识别到"` 或空；
3. 字段平均 OCR 置信度 `< 0.6`（需先让引擎回传 block score，当前只回文字——本方案补上）；
4. 结构异常（返回 dict 缺必需 key、JSON 无法解析）。

任一命中 → `LLMClient.vision(prompt=LLM兜底提示词, images=截图)` 重新抽取字段；若 LLM 也失败 → 记日志 + `call_master` 人工 + 跳过该岗位。

**范围注意（重要）**：本地 OCR 引擎是为"岗位详情多图"设计的（返回单岗位完整字段），对"浏览页两张卡片同框"的卡片列表解析较弱。建议：
- `extract_job_detail`（详情）→ 本地 GPU 主、LLM 兜底（已验证强）；
- `extract_card_list`（浏览页两卡）→ 先用 LLM 视觉主、本地 OCR 兜底，或后续扩展本地解析器；
- `extract_chat_header`（聊天顶部公司/HR）→ 本地 GPU 主、LLM 兜底。

这样既不削弱现有能力，又能把最稳的详情识别切到本地 GPU。

---

## 4. 提示词改造（第 4 + 6 点）设计

**结构（prompts.yaml）**：
```yaml
model:
  agent: qwen-max        # 规划/语义
  vision: qwen-vl-max    # OCR 兜底
  embedding: text-embedding-v3  # 本地 RAG 用
system: |
  你是罗帅的求职助手……（原 system_prompt.txt 内容，扩充为可配置）
knowledge:               # 本地 RAG 语料
  - assets/profile.md
  - 项目运行逻辑与实现方案报告.md
prompts:
  ocr_fallback_detail: |   # 仅 LLM 兜底时用
    ...
  match_job: |             # 语义判断（核心）
    请依据下方<求职期望>判断岗位是否匹配……
    返回 JSON: {"is_match":bool,"reason":str,"message":str}
  reply_message: |        # 回复生成（核心）
    ...
```

**优化要点**：
1. **职责拆分**：原 `extract_job_jd` / `_check_new_job` 把"判断匹配"和"生成打招呼文案"揉在一起 → 拆成 `match_job`（纯判断+理由）与 `generate_greet`（仅匹配时生成文案），降低模型跑偏。
2. **统一输出契约**：每个提示词显式给 JSON schema + "只返回 JSON，不要解释" + "字段缺失填'未识别到'"，复用 `job_reader.parse_ai_reply` 的容错。
3. **系统提示词可配置**：求职期望/个人资料从硬编码移入 `prompts.yaml` 的 `system`/`knowledge`，改期望不用动代码。
4. **清理死提示词**：`extract_job_info`（2 卡列表）、`match_job`、死掉的 `extract_message` 一并规整，避免与本地 OCR 路径重复。
5. **知识走本地 RAG**：`match_job` / `reply_message` 检索本地知识库注入上下文，替代失效的云端 app。

---

## 5. 分阶段实施（每阶段保持 auto 模式可跑，降低回归风险）

- **P0 脚手架**：装 `qwen-agent` 到 `.venv`；新增 `prompts.yaml` 加载器；写 `LLMClient` 骨架（`chat`/`vision`/`rag` + `extract_json` + 重试）。旧调用路径暂不动。
- **P1 统一调用**：`OCREngine`/`RAGEngine` 改调 `LLMClient`；删除 `app_id` 调用；落地 `local_rag`（Qwen-Agent 检索）。跑通 auto 模式回归。
- **P2 OCR 本地化+兜底**：`OCRService` 接线 `LocalOCREngine(GPU)` + 多维度校验 + `LLMClient.vision` 兜底；`JobBrowser`/`MessageReplier` 改用 `OCRService`。跑通 auto 模式回归 + GPU 推理日志。
- **P3 Agent 模式**：`agent_mode.py` + 3 工具 + `main.py` 的 `MODE` 开关。Agent 循环加 `max_iter`/超时护栏。
- **P4 提示词收尾**：全部迁入 `prompts.yaml` 并优化；删除 `config.PROMPTS`/`system_prompt.txt`/死代码。

每阶段结束都验证：auto 模式主流程不退化、OCR 字段准确率、LLM 调用集中到 `LLMClient`。

---

## 6. 风险与待确认

- **Qwen-Agent RAG API**：未安装，具体 `Assistant`/`knowledge`/`Retrieval` 接口以安装后实际版本为准，P1 时再钉。
- **本地 OCR 对卡片列表弱**：`extract_card_list` 默认 LLM 主、本地兜底（见 §3）。
- **Agent 护栏**：必须限制单轮工具调用次数与总时长，防止 LLM 无限循环点屏/打招呼超频（沿用 `BEHAVIOR_CONFIG` 的每日/每小时上限）。
- **开放问题**：Agent 模式下"搜索岗位"的 `keyword` 从哪来（写死 `config.search_job` 还是让 Agent 自己决定）？建议先用 `config.search_job`，后续再放开。

---

## 7. 下一步

确认本方案后，我按 P0→P4 顺序实施，每阶段给你可运行结果。若要调整任一决策（如工具粒度、RAG 方案、OCR 范围），现在说。

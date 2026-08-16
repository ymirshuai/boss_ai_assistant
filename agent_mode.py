"""
Agent 模式入口（T05）

用 Qwen-Agent 的 FnCallAgent 把三个粗粒度工具注册进去，
由大模型「读状态 → 决策调用哪个工具 → 工具跑通完整子流程」地驱动工作。
Agent 不直接操作屏幕坐标，只通过工具编排业务模块。

运行：设 BOSS_MODE=agent 后 `python main.py`，main() 会分派到 run_agent_mode()。
真实运行需要已连接的安卓设备 + 可用的 MaaS 网关（联网）。
"""
import logging

from qwen_agent.agents import FnCallAgent

from agent_tools import (
    search_jobs,
    browse_jobs,
    view_messages,
    db_operation,
    modify_prompt,
    save_info,
)
from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL
from logger import setup_logging
from prompts_loader import get_system_prompt

logger = logging.getLogger("agent_mode")

DEFAULT_INITIAL_MESSAGE = (
    "请开始今日工作：先查看新消息，再浏览岗位；"
    "如需找特定方向的岗位，可调用搜索工具。"
)


def _ensure_gateway():
    """私有 MaaS 网关端点（qwen_agent 底层走 dashscope）。"""
    if not QWEN_BASE_URL:
        return
    try:
        import dashscope

        dashscope.base_http_api_url = QWEN_BASE_URL
    except Exception as e:  # 不影响后续（LLMClient 也会设置）
        logger.warning("设置 dashscope 网关失败：%s", e)


def build_agent(ctx):
    """构造 FnCallAgent 并注册全部工具。离线可构造（不触发网络）。"""
    _ensure_gateway()
    tools = [
        search_jobs(ctx),
        browse_jobs(ctx),
        view_messages(ctx),
        db_operation(ctx),
        modify_prompt(ctx),
        save_info(ctx),
    ]
    bot = FnCallAgent(
        function_list=tools,
        llm={"model": QWEN_MODEL, "api_key": QWEN_API_KEY},
        system_message=get_system_prompt(),
    )
    return bot


def _build_default_ctx():
    """生产上下文：复用现有业务模块（不导入 main，避免其 import-time 的 auto_setup 副作用）。

    注意：本函数会触发 airtest_connector 的 auto_setup（连接真实设备），
    仅在真实运行（run_agent_mode 且无注入 ctx）时调用。单测中直接注入假 ctx。
    """
    from device import DeviceManager
    from airtest_connector import SnapshotManager
    from logger import Logger
    from ocr_engine import OCREngine
    from RAG_engine import RAGEngine
    from job_browser import JobBrowser
    from message_replier import MessageReplier

    logger_ = Logger()
    setup_logging(logger_.session_id)
    device = DeviceManager()
    sm = SnapshotManager()
    ocr = OCREngine(logger=logger_, sm=sm)
    rag = RAGEngine(logger=logger_, sm=sm)
    job_browser = JobBrowser(device=device, logger=logger_, ocr=ocr, rag=rag)
    message_replier = MessageReplier(
        device=device, logger=logger_, sm=sm, ocr=ocr, rag=rag
    )

    class AgentContext:
        def search_jobs(self, keyword=""):
            return job_browser.search(keyword)

        def browse_jobs(self):
            return job_browser.browse()

        def view_messages(self):
            return message_replier.reply()

        def db_operation(self, operation, params):
            import data_store as ds

            params = params or {}
            if operation == "list_jobs":
                return ds.get_all_jobs()
            if operation == "get_job":
                return ds.get_job_by_company_hr(
                    params.get("company"), params.get("hr_name")
                )
            if operation == "get_chat_history":
                return ds.get_chat_history(params.get("job_id"))
            if operation == "get_daily_summary":
                return ds.get_daily_summary(params.get("date"))
            if operation == "export":
                ds.export_to_json()
                return "已导出 data_backup.json"
            return {"error": f"未知操作: {operation}"}

        def modify_prompt(self, action, name, text):
            from prompts_loader import get_prompt, get_system_prompt, update_prompt

            if action == "get":
                if name == "system":
                    return get_system_prompt()
                return get_prompt(name)
            if action == "update":
                return update_prompt(name, text)
            return False, f"未知 action: {action}"

        def save_info(self, items):
            import data_store as ds

            return ds.save_user_info(items)

    return AgentContext()


def run_agent_mode(ctx=None, initial_message=DEFAULT_INITIAL_MESSAGE, max_rounds=30):
    """Agent 主循环：把初始指令交给 FnCallAgent，迭代到模型不再调用工具或达到轮次上限。"""
    setup_logging()
    if ctx is None:
        ctx = _build_default_ctx()
    bot = build_agent(ctx)
    messages = [{"role": "user", "content": initial_message}]
    final = messages
    rounds = 0
    logger.info("Agent 模式启动 | 初始指令: %s", initial_message)
    for resp in bot.run(messages):
        final = resp
        rounds += 1
        # 记录本轮末条内容，便于回溯 LLM 的决策 / 工具结果
        try:
            last = resp[-1]
            content = last.get("content") if isinstance(last, dict) else getattr(last, "content", "")
            logger.info("Agent 第 %d 轮完成 | 末条预览: %s", rounds, str(content)[:300])
        except Exception:
            logger.info("Agent 第 %d 轮完成", rounds)
        if rounds >= max_rounds:
            logger.warning("达到最大轮次 %d，停止。", max_rounds)
            break
    logger.info("Agent 模式结束，共 %d 轮。", rounds)
    return final

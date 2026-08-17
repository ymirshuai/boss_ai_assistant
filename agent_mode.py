"""
Agent 模式入口（T05）

用 Qwen-Agent 的 FnCallAgent 把工具注册进去，
由大模型「读状态 → 决策调用哪个工具 → 工具跑通完整子流程」地驱动工作。
Agent 不直接操作屏幕坐标，只通过工具编排业务模块。

运行：设 BOSS_MODE=agent 后 `python main.py`，main() 会分派到 run_agent_mode()。

安全模型（见 agent_mode_design.md）：
  - 不做任何二次确认；只做「强制停止」+「触屏工具开始/结束必回主页」。
  - 所有触屏工具在开始与结束都调用 handle_common_exception()（airtest_connector.py）。
  - AgentContext.stop_requested 为强制停止标志，触屏方法循环内检查，置位即中止。

设备惰性化（Phase 2）：
  - 构造 AgentContext **不连接真机**；非触屏工具（读简历 / 聚合分析 / 查库 /
    mock 出题 / 拉黑 / 改提示词 / 存信息）在没插手机时也能正常用。
  - 触屏工具首次调用时才 _ensure_touch() 初始化设备；失败返回带 error 的结构化
    结果而不抛异常，Web UI 对话不会因此中断。
"""
import json
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path

from qwen_agent.agents import FnCallAgent

from agent_tools import (
    search_jobs,
    browse_jobs,
    view_messages,
    db_operation,
    modify_prompt,
    save_info,
    analyze_jobs,
    run_campaign,
    blocklist,
    view_resume,
    mock_hr_questions,
    mock_interview_questions,
)
from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL, PROJECT_ROOT, BEHAVIOR_CONFIG
from logger import setup_logging
from prompts_loader import get_system_prompt

logger = logging.getLogger("agent_mode")

# 拉黑公司名单持久化文件（agent blocklist 工具落地处）
_BLOCKLIST_PATH = PROJECT_ROOT / "blocklist.json"


def load_blocklist():
    """读取拉黑公司/岗位名单（JSON 数组）。"""
    try:
        if _BLOCKLIST_PATH.exists():
            return json.load(open(_BLOCKLIST_PATH, encoding="utf-8")) or []
    except Exception:
        pass
    return []


def save_blocklist(items):
    """写回拉黑名单。"""
    _BLOCKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    json.dump(list(items), open(_BLOCKLIST_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def go_home():
    """回到 BOSS 主页（触屏工具的「回家不变量」）。

    惰性导入 airtest_connector：该模块在 import 时就会 auto_setup 连接设备，
    因此绝不能放在模块顶层，否则无真机环境下 import agent_mode 会阻塞。
    """
    try:
        from airtest_connector import handle_common_exception

        handle_common_exception()
        return True
    except Exception as e:
        logger.warning("回主页失败：%s", e)
        return False


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
        # 新增（Phase 1）
        analyze_jobs(ctx),
        run_campaign(ctx),
        blocklist(ctx),
        view_resume(ctx),
        mock_hr_questions(ctx),
        mock_interview_questions(ctx),
    ]
    bot = FnCallAgent(
        function_list=tools,
        llm={"model": QWEN_MODEL, "api_key": QWEN_API_KEY},
        system_message=get_system_prompt(),
    )
    return bot


class AgentContext:
    """Agent 工具的业务上下文（工具 → 业务模块的唯一入口）。

    构造本类不连接设备；触屏能力惰性初始化，见类文档与 _ensure_touch()。
    """

    def __init__(self, logger_=None, llm=None):
        self.stop_requested = False
        self._logger = logger_
        self._llm = llm
        # 触屏依赖（惰性）
        self._touch_ready = False
        self._touch_error = None
        self._device = None
        self._job_browser = None
        self._message_replier = None

    # ---------------- 惰性依赖 ----------------
    @property
    def logger(self):
        if self._logger is None:
            from logger import Logger

            self._logger = Logger()
            setup_logging(self._logger.session_id)
        return self._logger

    @property
    def llm(self):
        if self._llm is None:
            from llm_client import LLMClient

            self._llm = LLMClient()
        return self._llm

    def _ensure_touch(self) -> bool:
        """惰性初始化触屏依赖（会连接真机）。True 表示可用。"""
        if self._touch_ready:
            return True
        try:
            from device import DeviceManager
            from airtest_connector import SnapshotManager
            from ocr_engine import OCREngine
            from RAG_engine import RAGEngine
            from job_browser import JobBrowser
            from message_replier import MessageReplier

            lg = self.logger
            device = DeviceManager()
            sm = SnapshotManager()
            ocr = OCREngine(logger=lg, sm=sm)
            rag = RAGEngine(logger=lg, sm=sm)
            self._device = device
            self._job_browser = JobBrowser(device=device, logger=lg, ocr=ocr, rag=rag)
            self._message_replier = MessageReplier(
                device=device, logger=lg, sm=sm, ocr=ocr, rag=rag
            )
            self._touch_ready = True
            self._touch_error = None
        except Exception as e:
            self._touch_error = f"设备未就绪（{e}）——请确认手机已连接并打开 BOSS 直聘"
            logger.warning("触屏依赖初始化失败：%s", e)
        return self._touch_ready

    def touch_available(self) -> bool:
        """只读探测：触屏依赖是否已初始化（不触发初始化）。"""
        return self._touch_ready

    # ---------------- G1 海投获客（触屏）----------------
    def search_jobs(self, keyword="", greet=False):
        if not self._ensure_touch():
            return {"ok": False, "browsed": 0, "greeted": 0,
                    "stopped_by_user": False, "error": self._touch_error}
        go_home()
        try:
            self._job_browser.set_blocklist(load_blocklist())
            self._job_browser.search(keyword)
            if greet:
                b = self._job_browser.browse(greet=True)
                return {"ok": True, "browsed": b["browsed"], "greeted": b["greeted"],
                        "stopped_by_user": self.stop_requested, "error": None}
            return {"ok": True, "browsed": 0, "greeted": 0,
                    "stopped_by_user": self.stop_requested, "error": None}
        except Exception as e:
            return {"ok": False, "browsed": 0, "greeted": 0,
                    "stopped_by_user": self.stop_requested, "error": str(e)}
        finally:
            go_home()

    def browse_jobs(self, greet=False):
        if not self._ensure_touch():
            return {"browsed": 0, "greeted": 0,
                    "stopped_by_user": False, "error": self._touch_error}
        go_home()
        try:
            self._job_browser.set_blocklist(load_blocklist())
            b = self._job_browser.browse(greet=greet)
            return {"browsed": b["browsed"], "greeted": b["greeted"],
                    "stopped_by_user": self.stop_requested, "error": None}
        except Exception as e:
            return {"browsed": 0, "greeted": 0,
                    "stopped_by_user": self.stop_requested, "error": str(e)}
        finally:
            go_home()

    # ---------------- G2 跟进转化（触屏）----------------
    def view_messages(self):
        if not self._ensure_touch():
            return {"checked": 0, "replied": 0,
                    "stopped_by_user": False, "error": self._touch_error}
        go_home()
        try:
            checked = replied = 0
            for _ in range(20):  # 上限保护，避免无限
                if self.stop_requested:
                    break
                r = self._message_replier.reply()
                if r == "success":
                    checked += 1
                    replied += 1
                else:
                    break
            return {"checked": checked, "replied": replied,
                    "stopped_by_user": self.stop_requested, "error": None}
        except Exception as e:
            return {"checked": 0, "replied": 0,
                    "stopped_by_user": self.stop_requested, "error": str(e)}
        finally:
            go_home()

    # ---------------- G3 信息沉淀与复盘 ----------------
    def analyze_jobs(self, scope="today", metric=None):
        from data_store import get_all_jobs, get_chat_history

        try:
            jobs = get_all_jobs()
            from collections import Counter

            companies = Counter(j.get("company") for j in jobs if j.get("company"))
            salaries = [j.get("salary") for j in jobs if j.get("salary")]
            hr_msgs = me_msgs = 0
            for j in jobs:
                for c in get_chat_history(j["id"]):
                    if c["sender"] == "hr":
                        hr_msgs += 1
                    elif c["sender"] == "me":
                        me_msgs += 1
            reply_rate = round(hr_msgs / me_msgs, 3) if me_msgs else 0.0
            summary = (f"共记录 {len(jobs)} 个岗位；HR 回复数 {hr_msgs}，"
                       f"我的消息 {me_msgs}，回复率 {reply_rate}。")
            return {
                "total_jobs": len(jobs),
                "top_companies": companies.most_common(5),
                "salaries": salaries[:10],
                "hr_messages": hr_msgs,
                "my_messages": me_msgs,
                "reply_rate": reply_rate,
                "summary": summary,
            }
        except Exception as e:
            return {"error": str(e)}

    # ---------------- G4 策略配置 ----------------
    def run_campaign(self, keyword=None, target_greet_count=None,
                     duration=None, search_enabled=True):
        """浏览岗位并打招呼，同时每浏览约 2 个岗位查看并回复新消息。
        受数量/时长限定；结束回传 this_run/today 双计数结果给 agent。"""
        from data_store import get_today_greet_count

        if not self._ensure_touch():
            return {"ok": False, "stopped_by_user": False, "error": self._touch_error,
                    "summary": self._touch_error,
                    "this_run": {"browsed": 0, "greeted": 0, "replied": 0},
                    "today": {"browsed": 0, "greeted": 0, "replied": 0}}
        self.stop_requested = False
        self._job_browser.set_blocklist(load_blocklist())
        target = target_greet_count or BEHAVIOR_CONFIG["greet_per_day"]
        deadline = (time.time() + float(duration)) if duration else None
        kw = keyword or ""
        this_run = {"browsed": 0, "greeted": 0, "replied": 0}
        error = None
        try:
            go_home()  # 回家起点
            while not self.stop_requested:
                if deadline and time.time() > deadline:
                    self.logger.log("已到设定运行时长，停止 campaign", "INFO")
                    break
                today_greets = get_today_greet_count()
                if today_greets >= target:
                    self.logger.log(f"今日打招呼已达目标 {target}，停止", "INFO")
                    break
                if search_enabled and kw:
                    self._job_browser.search(kw)
                b = self._job_browser.browse(greet=True)
                this_run["browsed"] += b["browsed"]
                this_run["greeted"] += b["greeted"]
                if self.stop_requested:
                    break
                # 每浏览约 2 个岗位，查看并回复新消息
                r = self.view_messages()
                this_run["replied"] += r.get("replied", 0)
                if self.stop_requested:
                    break
        except Exception:
            error = traceback.format_exc()
            self.logger.log_error("run_campaign 异常", error)
        finally:
            go_home()
        today = {
            "browsed": self.logger.stats["browse_count"],
            "greeted": get_today_greet_count(),
            "replied": self.logger.stats["reply_count"],
        }
        return {
            "ok": error is None,
            "stopped_by_user": self.stop_requested,
            "error": error,
            "summary": (
                f"本轮 浏览 {this_run['browsed']} / 打招呼 {this_run['greeted']} / "
                f"回复 {this_run['replied']}；今日累计 浏览 {today['browsed']} / "
                f"打招呼 {today['greeted']} / 回复 {today['replied']}。"
            ),
            "this_run": this_run,
            "today": today,
        }

    def blocklist(self, action="list", company_or_job=None):
        items = load_blocklist()
        if action == "add" and company_or_job:
            if company_or_job not in items:
                items.append(company_or_job)
            save_blocklist(items)
            return {"ok": True, "blocked": items, "action": action}
        if action == "remove" and company_or_job:
            items = [x for x in items if x != company_or_job]
            save_blocklist(items)
            return {"ok": True, "blocked": items, "action": action}
        return {"ok": True, "blocked": items, "action": "list"}

    # ---------------- G5 准备与练习 ----------------
    def view_resume(self):
        kb_dir = PROJECT_ROOT / "资料库"
        candidates = sorted(kb_dir.glob("*.md")) if kb_dir.exists() else []
        resume_file = None
        for f in candidates:
            if "简历" in f.name:
                resume_file = f
                break
        if resume_file is None and candidates:
            resume_file = candidates[0]
        if resume_file is None:
            return {"resume_text": "", "name": "", "file": ""}
        return {
            "resume_text": resume_file.read_text(encoding="utf-8"),
            "name": resume_file.stem,
            "file": str(resume_file),
        }

    def mock_hr_questions(self, resume_text, count=5):
        """基于简历生成 HR 提问，专挑资料库缺口（简历+目标岗位双必须之简历侧）。"""
        from llm_client import LLMClient
        from data_store import get_user_info

        try:
            existing = get_user_info()
            existing_fields = [u["field_name"] for u in existing]
        except Exception:
            existing_fields = []
        prompt = (
            f"你是一名资深 HR。以下是候选人的简历：\n\n{resume_text}\n\n"
            f"资料库中已记录的信息字段：{existing_fields}\n\n"
            f"请生成 {count} 道 HR 常见提问，专门补资料库里没有的个人信息/经历/"
            f"离职原因/期望。只输出 JSON 数组，每项 "
            f"{{'q': 问题, 'suggested_answer': 基于简历的参考回答, "
            f"'gap': '该项是否资料库缺失(是/否)'}}。"
        )
        try:
            raw = self.llm.chat(prompt, system="你是求职模拟助手，只输出 JSON。")
            questions = LLMClient.extract_json(raw)
            if not isinstance(questions, list):
                questions = []
            return {"hr_questions": questions, "saved": False}
        except Exception as e:
            return {"hr_questions": [], "saved": False, "error": str(e)}

    def mock_interview_questions(self, target_job_jd, count=5):
        """基于目标岗位详细 JD 生成面试题（技术类 + 工作情况）。JD 来源由 agent 自决。"""
        from llm_client import LLMClient

        prompt = (
            f"你是技术面试官。以下是目标岗位的详细 JD：\n\n{target_job_jd}\n\n"
            f"请生成 {count} 道面试题，覆盖「技术类」与「具体工作情况/场景题」两类。"
            f"只输出 JSON 数组，每项 {{'q': 问题, 'category': '技术'或'工作情况', "
            f"'suggested_answer': 参考回答}}。"
        )
        try:
            raw = self.llm.chat(prompt, system="你是面试模拟助手，只输出 JSON。")
            questions = LLMClient.extract_json(raw)
            if not isinstance(questions, list):
                questions = []
            return {"interview_questions": questions}
        except Exception as e:
            return {"interview_questions": [], "error": str(e)}

    # ---------------- 既有（不改签名）----------------
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


def _build_default_ctx():
    """生产上下文（保留原函数名以兼容既有调用）。

    与旧实现的差别：**不再在构造时连接设备**。触屏依赖首次调用触屏方法时才初始化。
    """
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

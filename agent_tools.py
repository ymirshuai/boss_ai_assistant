"""
Agent 工具（T05）

三个粗粒度工具，注册进 Qwen-Agent 的 FnCallAgent：
  - search_jobs   搜索岗位（按关键词发起搜索，留空则浏览首页推荐）
  - browse_jobs   浏览岗位（识别字段 → 判匹配 → 符合则自动打招呼）
  - view_messages 查看消息（识别 HR 新消息 → 回复 / 发简历 / 发微信 / 约面试）

设计要点：
  - 每个工具内部跑通「一条完整子流程」，复用现有业务模块（JobBrowser / MessageReplier）。
  - 工具不直接操作屏幕坐标，只编排业务模块；设备 / LLM 等通过注入的 ctx 提供，
    因此本模块 import-light，不触发 airtest_connector 的 auto_setup 副作用，便于单测。
  - ctx 约定接口：search_jobs(keyword="") / browse_jobs() / view_messages()。
"""
import json
import logging
from typing import Any, Dict

from qwen_agent.tools.base import BaseTool

logger = logging.getLogger("agent_tools")


def _parse_params(params):
    """统一解析工具入参：字符串 JSON → dict，dict 原样返回，其余回 {}。"""
    try:
        if isinstance(params, str):
            return json.loads(params) if params.strip() else {}
        if isinstance(params, dict):
            return params
    except Exception:
        pass
    return {}


class search_jobs(BaseTool):
    name = "search_jobs"
    description = (
        "搜索岗位：按关键词在 BOSS 直聘发起搜索（留空则浏览首页推荐岗位）。"
        "greet=true 时搜索后顺带浏览并自动打招呼；greet=false 时只搜索/浏览不招呼。"
        "当用户想找特定方向（如 AI 应用开发）的岗位时调用。"
    )
    parameters = [
        {
            "name": "keyword",
            "description": "要搜索的岗位关键词，例如「AI 应用开发」「测试主管」；留空则浏览首页推荐",
            "required": False,
            "type": "string",
        },
        {
            "name": "greet",
            "description": "是否在浏览到的岗位中自动打招呼；false=只搜索/浏览不招呼",
            "required": False,
            "type": "boolean",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用 | params=%s", self.name, params)
        p = _parse_params(params)
        keyword = (p or {}).get("keyword") or ""
        greet = bool((p or {}).get("greet", False))
        try:
            res = self.ctx.search_jobs(keyword, greet=greet)
            label = keyword or "首页推荐"
            return f"搜索岗位已完成（关键词={label}，打招呼={greet}），结果：{res}"
        except Exception as e:
            logger.exception("search_jobs 执行失败")
            return f"搜索岗位失败：{e}"


class browse_jobs(BaseTool):
    name = "browse_jobs"
    description = (
        "浏览岗位：对当前岗位流识别字段、判断是否符合求职期望。"
        "greet=true 时符合则自动打招呼；greet=false 时只浏览/保存岗位信息不招呼。"
        "返回本次浏览与打招呼数量。用于主动发掘并接触匹配岗位。"
    )
    parameters = [
        {
            "name": "greet",
            "description": "是否在浏览到的岗位中自动打招呼；false=只浏览不招呼",
            "required": False,
            "type": "boolean",
        }
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        greet = bool((p or {}).get("greet", False))
        try:
            res = self.ctx.browse_jobs(greet=greet)
            return (f"浏览岗位完成（打招呼={greet}）：本次浏览 {res.get('browsed', 0)} 个，"
                    f"打招呼 {res.get('greeted', 0)} 个。")
        except Exception as e:
            logger.exception("browse_jobs 执行失败")
            return f"浏览岗位失败：{e}"


class view_messages(BaseTool):
    name = "view_messages"
    description = (
        "查看消息：进入消息列表，对 HR 的新消息进行识别与回复"
        "（含发简历 / 发微信 / 约面试处理）。返回处理结果。用于跟进已有沟通。"
    )
    parameters = []

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        try:
            result = self.ctx.view_messages()
            return f"查看消息完成，处理结果：{result}。"
        except Exception as e:
            logger.exception("view_messages 执行失败")
            return f"查看消息失败：{e}"


class db_operation(BaseTool):
    name = "db_operation"
    description = (
        "数据库操作：查询 / 导出本地 SQLite 数据（岗位、聊天记录、每日统计）。"
        "operation 可选：list_jobs（列出全部岗位）、get_job（按 公司+HR 查岗位）、"
        "get_chat_history（某岗位聊天记录，需 job_id）、get_daily_summary（每日运行统计，date 可选）、"
        "export（导出全部数据为 data_backup.json 备份）。"
        "当用户想查看或备份已采集的数据时调用。"
    )
    parameters = [
        {
            "name": "operation",
            "description": "操作名：list_jobs / get_job / get_chat_history / get_daily_summary / export",
            "required": True,
            "type": "string",
        },
        {
            "name": "params",
            "description": "操作参数对象，如 get_job 需 {company, hr_name}，get_chat_history 需 {job_id}",
            "required": False,
            "type": "string",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        params = self._parse(params)
        operation = (params or {}).get("operation") or ""
        sub = (params or {}).get("params") or {}
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except Exception:
                sub = {}
        try:
            result = self.ctx.db_operation(operation, sub or None)
            return f"数据库操作[{operation}]结果：{json.dumps(result, ensure_ascii=False)}"
        except Exception as e:
            logger.exception("db_operation 执行失败")
            return f"数据库操作失败：{e}"

    @staticmethod
    def _parse(params):
        try:
            if isinstance(params, str):
                return json.loads(params) if params.strip() else {}
            if isinstance(params, dict):
                return params
        except Exception:
            pass
        return {}


class modify_prompt(BaseTool):
    name = "modify_prompt"
    description = (
        "提示词修改：读取或更新 prompts.yaml 中的提示词（含系统提示词）。"
        "action=get 读取指定提示词；action=update 更新并持久化到文件，立即生效。"
        "name 可为 system（系统人设）或某个具体提示词键（如 extract_job_jd、check_new_job、generate_reply）。"
        "当用户希望查看或调整助手的话术 / 匹配规则 / 系统人设时调用。"
    )
    parameters = [
        {
            "name": "action",
            "description": "'get' 读取 / 'update' 更新",
            "required": True,
            "type": "string",
        },
        {
            "name": "name",
            "description": "提示词键，如 system / extract_job_jd / check_new_job",
            "required": True,
            "type": "string",
        },
        {
            "name": "text",
            "description": "action=update 时提供的新提示词内容",
            "required": False,
            "type": "string",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        params = self._parse(params)
        p = params or {}
        action = p.get("action") or "get"
        name = p.get("name") or ""
        text = p.get("text") or ""
        try:
            result = self.ctx.modify_prompt(action, name, text)
            if isinstance(result, tuple):
                ok, msg = result
                return f"[{'成功' if ok else '失败'}] {msg}"
            return str(result)
        except Exception as e:
            logger.exception("modify_prompt 执行失败")
            return f"提示词修改失败：{e}"

    @staticmethod
    def _parse(params):
        try:
            if isinstance(params, str):
                return json.loads(params) if params.strip() else {}
            if isinstance(params, dict):
                return params
        except Exception:
            pass
        return {}


class save_info(BaseTool):
    name = "save_info"
    description = (
        "信息保存：把模拟 HR 对话中提取到的用户（候选人）信息持久化到本地数据库（user_info 表）。"
        "info 可为 {字段名: 值} 的字典（如 {期望薪资: 20-30K, 当前城市: 深圳}），"
        "或 [{category, field_name, field_value, source}] 的结构化列表。"
        "用于记录 HR 询问到的候选人期望、技能、联系方式等。当用户在对话中确认要保存某条用户信息时调用。"
    )
    parameters = [
        {
            "name": "info",
            "description": "{字段名: 值} 或 结构化列表；如 {期望薪资: 20-30K, 当前城市: 深圳}",
            "required": True,
            "type": "string",
        },
        {
            "name": "category",
            "description": "归类标签，默认「HR对话信息」",
            "required": False,
            "type": "string",
        },
        {
            "name": "source",
            "description": "信息来源，默认「HR对话模拟」",
            "required": False,
            "type": "string",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        params = self._parse(params)
        p = params or {}
        info = p.get("info") or {}
        category = p.get("category") or "HR对话信息"
        source = p.get("source") or "HR对话模拟"
        items = []
        if isinstance(info, list):
            for it in info:
                if isinstance(it, dict) and it.get("field_name"):
                    items.append(
                        {
                            "category": it.get("category", category),
                            "field_name": it["field_name"],
                            "field_value": str(it.get("field_value", "")),
                            "source": it.get("source", source),
                        }
                    )
        elif isinstance(info, dict):
            for k, v in info.items():
                items.append(
                    {
                        "category": category,
                        "field_name": str(k),
                        "field_value": str(v),
                        "source": source,
                    }
                )
        if not items:
            return "没有可保存的用户信息（info 为空或格式不正确）。"
        try:
            result = self.ctx.save_info(items)
            return f"已保存 {len(items)} 条用户信息（{result}）。"
        except Exception as e:
            logger.exception("save_info 执行失败")
            return f"信息保存失败：{e}"

    @staticmethod
    def _parse(params):
        try:
            if isinstance(params, str):
                return json.loads(params) if params.strip() else {}
            if isinstance(params, dict):
                return params
        except Exception:
            pass
        return {}


# ===================== Phase 1 新增工具 =====================

class analyze_jobs(BaseTool):
    name = "analyze_jobs"
    description = (
        "岗位分析：对本地已采集的岗位/聊天/每日统计做聚合分析，"
        "输出岗位总数、高频公司、薪资分布、HR 回复率等，帮助复盘哪类岗位/话术更有效。"
        "当用户想复盘求职数据、了解投递概况时调用。"
    )
    parameters = [
        {
            "name": "scope",
            "description": "统计范围：today=今日汇总 / all=全部历史（默认 today）",
            "required": False,
            "type": "string",
        },
        {
            "name": "metric",
            "description": "聚焦指标：common_traits/reply_rate/wording_effect，缺省全给",
            "required": False,
            "type": "string",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        scope = (p or {}).get("scope") or "today"
        metric = (p or {}).get("metric")
        try:
            res = self.ctx.analyze_jobs(scope=scope, metric=metric)
            return "岗位分析完成：" + json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("analyze_jobs 执行失败")
            return f"岗位分析失败：{e}"


class run_campaign(BaseTool):
    name = "run_campaign"
    description = (
        "启动一轮主动求职：浏览岗位并打招呼，同时每浏览约 2 个岗位查看并回复新消息。"
        "受数量（target_greet_count）与时长（duration 秒）限定；结束回传本轮与今日累计结果。"
        "当用户要开始一轮海投+跟进时调用。（触屏操作，可在任意时刻被强制停止）"
    )
    parameters = [
        {
            "name": "keyword",
            "description": "搜索岗位关键词；留空则浏览 BOSS 主页推荐岗位",
            "required": False,
            "type": "string",
        },
        {
            "name": "target_greet_count",
            "description": "目标打招呼数量（达到即暂停本轮）",
            "required": False,
            "type": "integer",
        },
        {
            "name": "duration",
            "description": "最长运行秒数；留空则一直运行直到手动停止或达每日上限",
            "required": False,
            "type": "integer",
        },
        {
            "name": "search_enabled",
            "description": "是否执行「搜索指定岗位」；false=直接浏览主页推荐岗位",
            "required": False,
            "type": "boolean",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        keyword = (p or {}).get("keyword") or None
        target = (p or {}).get("target_greet_count")
        duration = (p or {}).get("duration")
        search_enabled = (p or {}).get("search_enabled", True)
        if isinstance(search_enabled, str):
            search_enabled = search_enabled.lower() not in ("false", "0", "no")
        try:
            res = self.ctx.run_campaign(
                keyword=keyword,
                target_greet_count=target,
                duration=duration,
                search_enabled=search_enabled,
            )
            return "campaign 结束：" + json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("run_campaign 执行失败")
            return f"campaign 执行失败：{e}"


class blocklist(BaseTool):
    name = "blocklist"
    description = (
        "拉黑管理：把不合适的公司/岗位加入黑名单（之后浏览/搜索会跳过），"
        "也可移除或列出当前黑名单。当用户要屏蔽某家公司、避免再投时调用。"
    )
    parameters = [
        {
            "name": "action",
            "description": "操作：list(列出) / add(加入) / remove(移除)，默认 list",
            "required": False,
            "type": "string",
        },
        {
            "name": "company_or_job",
            "description": "要加入/移除的公司名或岗位标识（add/remove 时必填）",
            "required": False,
            "type": "string",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        action = (p or {}).get("action") or "list"
        item = (p or {}).get("company_or_job") or None
        try:
            res = self.ctx.blocklist(action=action, company_or_job=item)
            return "拉黑管理：" + json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("blocklist 执行失败")
            return f"拉黑管理失败：{e}"


class view_resume(BaseTool):
    name = "view_resume"
    description = (
        "读取当前用户简历全文（资料库目录下简历 markdown）。"
        "用于模拟 HR 提问、了解自身背景。通常作为 mock_hr_questions 的前置步骤。"
    )
    parameters = []

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        try:
            res = self.ctx.view_resume()
            if not res.get("resume_text"):
                return "未找到简历文件（资料库目录下无简历 markdown）。"
            return f"简历《{res.get('name', '')}》：\n{res.get('resume_text', '')}"
        except Exception as e:
            logger.exception("view_resume 执行失败")
            return f"读取简历失败：{e}"


class mock_hr_questions(BaseTool):
    name = "mock_hr_questions"
    description = (
        "模拟 HR 提问：基于用户简历，生成专补资料库缺口的 HR 常见题"
        "（经历 / 个人信息 / 离职原因 / 期望），供用户练习并补录信息。简历为必须参数。"
        "当用户想提前准备 HR 沟通、或补充资料库缺失信息时调用。"
    )
    parameters = [
        {
            "name": "resume_text",
            "description": "用户简历全文（通常先调 view_resume 获取）",
            "required": True,
            "type": "string",
        },
        {
            "name": "count",
            "description": "生成题目数量，默认 5",
            "required": False,
            "type": "integer",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        resume_text = (p or {}).get("resume_text") or ""
        count = (p or {}).get("count") or 5
        if not resume_text:
            return "缺少简历文本（resume_text），请先调用 view_resume 获取简历。"
        try:
            res = self.ctx.mock_hr_questions(resume_text, count=count)
            return "HR 模拟提问：" + json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("mock_hr_questions 执行失败")
            return f"HR 模拟提问失败：{e}"


class mock_interview_questions(BaseTool):
    name = "mock_interview_questions"
    description = (
        "模拟面试题：基于目标岗位详细 JD，生成技术类与工作情况/场景题，"
        "帮助用户预演可能遇到的面试问题。JD 为必须参数（可由 db_operation 搜库或 search_jobs 搜岗获取）。"
        "当用户想准备目标岗位面试时调用。"
    )
    parameters = [
        {
            "name": "target_job_jd",
            "description": "目标岗位的详细 JD 文本",
            "required": True,
            "type": "string",
        },
        {
            "name": "count",
            "description": "生成题目数量，默认 5",
            "required": False,
            "type": "integer",
        },
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        p = _parse_params(params)
        jd = (p or {}).get("target_job_jd") or ""
        count = (p or {}).get("count") or 5
        if not jd:
            return ("缺少目标岗位 JD（target_job_jd）。可先通过 db_operation 搜库"
                    "或 search_jobs 搜岗获取 JD 文本。")
        try:
            res = self.ctx.mock_interview_questions(jd, count=count)
            return "面试模拟提问：" + json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.exception("mock_interview_questions 执行失败")
            return f"面试模拟提问失败：{e}"

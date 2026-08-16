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


class search_jobs(BaseTool):
    name = "search_jobs"
    description = (
        "搜索岗位：按关键词在 BOSS 直聘发起搜索（留空则浏览首页推荐岗位），"
        "返回搜索是否发起成功。当用户想找特定方向（如 AI 应用开发）的岗位时调用。"
    )
    parameters = [
        {
            "name": "keyword",
            "description": "要搜索的岗位关键词，例如「AI 应用开发」「测试主管」；留空则浏览首页推荐",
            "required": False,
            "type": "string",
        }
    ]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用 | params=%s", self.name, params)
        try:
            if isinstance(params, str):
                params = json.loads(params) if params.strip() else {}
            elif not isinstance(params, dict):
                params = {}
        except Exception:
            params = {}
        keyword = (params or {}).get("keyword") or ""
        try:
            ok = self.ctx.search_jobs(keyword)
            label = keyword or "首页推荐"
            return f"搜索岗位已完成（关键词={label}），结果：{ok}"
        except Exception as e:
            logger.exception("search_jobs 执行失败")
            return f"搜索岗位失败：{e}"


class browse_jobs(BaseTool):
    name = "browse_jobs"
    description = (
        "浏览岗位：对当前岗位流识别字段、判断是否符合求职期望、符合则自动打招呼。"
        "返回本次打招呼的岗位数量。用于主动发掘并接触匹配岗位。"
    )
    parameters = []

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    def call(self, params: Any, **kwargs) -> str:
        logger.info("→ 工具 %s 被调用", self.name)
        try:
            count = self.ctx.browse_jobs()
            return f"浏览岗位完成，本次打招呼 {count} 个岗位。"
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

"""
Phase 1 工具层测试（离线，注入 FakeCtx，不触屏/不联网）。

覆盖：
  - build_agent 注册全部 12 个工具
  - search_jobs / browse_jobs 的 greet 开关解析与委托
  - analyze_jobs / run_campaign / blocklist / view_resume 委托与返回结构
  - mock_hr_questions / mock_interview_questions 的「简历/JD 必填」与 JSON 解析
  - stop_requested 强制停止契约
"""
import json

import pytest

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


class _FakeLLM:
    """极简 LLM 替身：按 prompt 关键字返回对应 JSON 字符串。"""

    def chat(self, prompt, system=None, temperature=0.7):
        if "HR" in prompt:
            return json.dumps(
                [{"q": "你的期望薪资？", "suggested_answer": "18K以上", "gap": "是"}],
                ensure_ascii=False,
            )
        return json.dumps(
            [{"q": "讲讲 TCP 三次握手", "category": "技术", "suggested_answer": "SYN/SYN-ACK/ACK"}],
            ensure_ascii=False,
        )


class FakeCtx:
    """实现 AgentContext 的全部方法契约，记录调用参数供断言。"""

    def __init__(self):
        self.stop_requested = False
        self.llm = _FakeLLM()
        self.calls = []

    # G1
    def search_jobs(self, keyword="", greet=False):
        self.calls.append(("search_jobs", keyword, greet))
        return {"ok": True, "browsed": 3, "greeted": 1,
                "stopped_by_user": self.stop_requested, "error": None}

    def browse_jobs(self, greet=False):
        self.calls.append(("browse_jobs", greet))
        return {"browsed": 2, "greeted": 1 if greet else 0,
                "stopped_by_user": self.stop_requested, "error": None}

    # G2
    def view_messages(self):
        self.calls.append(("view_messages",))
        return {"checked": 1, "replied": 1,
                "stopped_by_user": self.stop_requested, "error": None}

    # G3
    def analyze_jobs(self, scope="today", metric=None):
        self.calls.append(("analyze_jobs", scope, metric))
        return {"total_jobs": 5, "reply_rate": 0.4, "summary": "ok"}

    # G4
    def run_campaign(self, keyword=None, target_greet_count=None,
                     duration=None, search_enabled=True):
        self.calls.append(("run_campaign", keyword, target_greet_count,
                           duration, search_enabled))
        # 强制停止契约：置位后立即返回 stopped_by_user=True
        return {
            "ok": True,
            "stopped_by_user": self.stop_requested,
            "error": None,
            "summary": "done",
            "this_run": {"browsed": 4, "greeted": 2, "replied": 1},
            "today": {"browsed": 4, "greeted": 2, "replied": 1},
        }

    def blocklist(self, action="list", company_or_job=None):
        self.calls.append(("blocklist", action, company_or_job))
        if not hasattr(self, "_bl"):
            self._bl = []
        if action == "add" and company_or_job:
            if company_or_job not in self._bl:
                self._bl.append(company_or_job)
        elif action == "remove" and company_or_job:
            self._bl = [x for x in self._bl if x != company_or_job]
        return {"ok": True, "blocked": list(self._bl), "action": action}

    # G5
    def view_resume(self):
        self.calls.append(("view_resume",))
        return {"resume_text": "姓名：罗帅\n期望薪资：18K以上", "name": "罗帅简历", "file": "x.md"}

    def mock_hr_questions(self, resume_text, count=5):
        self.calls.append(("mock_hr_questions", resume_text, count))
        if not resume_text:
            return {"hr_questions": [], "saved": False, "error": "no resume"}
        return {"hr_questions": [{"q": "期望薪资？", "suggested_answer": "18K以上", "gap": "是"}],
                "saved": False}

    def mock_interview_questions(self, target_job_jd, count=5):
        self.calls.append(("mock_interview_questions", target_job_jd, count))
        if not target_job_jd:
            return {"interview_questions": [], "error": "no jd"}
        return {"interview_questions": [{"q": "TCP？", "category": "技术", "suggested_answer": "x"}]}

    # 既有
    def db_operation(self, operation, params):
        self.calls.append(("db_operation", operation, params))
        return {"op": operation}

    def modify_prompt(self, action, name, text):
        self.calls.append(("modify_prompt", action, name, text))
        return "ok"

    def save_info(self, items):
        self.calls.append(("save_info", items))
        return (len(items), 0)


# ------------------------- build_agent 注册 -------------------------
def test_build_agent_registers_all_12_tools():
    from agent_mode import build_agent
    bot = build_agent(FakeCtx())
    names = set(bot.function_map.keys())
    expected = {
        "search_jobs", "browse_jobs", "view_messages", "db_operation",
        "modify_prompt", "save_info", "analyze_jobs", "run_campaign",
        "blocklist", "view_resume", "mock_hr_questions", "mock_interview_questions",
    }
    assert expected.issubset(names), f"缺失工具: {expected - names}"
    assert len(names) == 12, f"工具数量应为 12，实际 {len(names)}"


# ------------------------- greet 开关 -------------------------
def test_search_jobs_greet_true_false():
    ctx = FakeCtx()
    out_true = search_jobs(ctx).call(json.dumps({"keyword": "AI", "greet": True}))
    out_false = search_jobs(ctx).call(json.dumps({"keyword": "AI", "greet": False}))
    assert ("search_jobs", "AI", True) in ctx.calls
    assert ("search_jobs", "AI", False) in ctx.calls
    assert "打招呼=True" in out_true and "打招呼=False" in out_false


def test_browse_jobs_greet_parsing():
    ctx = FakeCtx()
    browse_jobs(ctx).call(json.dumps({"greet": True}))
    browse_jobs(ctx).call(json.dumps({"greet": False}))
    assert ("browse_jobs", True) in ctx.calls
    assert ("browse_jobs", False) in ctx.calls


# ------------------------- 委托与结构 -------------------------
def test_analyze_jobs_delegation():
    ctx = FakeCtx()
    out = analyze_jobs(ctx).call(json.dumps({"scope": "all"}))
    assert "岗位分析完成" in out
    assert ("analyze_jobs", "all", None) in ctx.calls


def test_run_campaign_shape_and_delegation():
    ctx = FakeCtx()
    out = run_campaign(ctx).call(
        json.dumps({"keyword": "AI应用开发", "target_greet_count": 10, "duration": 60,
                    "search_enabled": True})
    )
    assert "campaign 结束" in out
    assert ("run_campaign", "AI应用开发", 10, 60, True) in ctx.calls
    # 返回结构含 this_run / today 双计数
    parsed = json.loads(out.split("campaign 结束：", 1)[1])
    assert set(parsed["this_run"].keys()) == {"browsed", "greeted", "replied"}
    assert set(parsed["today"].keys()) == {"browsed", "greeted", "replied"}


def test_blocklist_add_then_list():
    ctx = FakeCtx()
    out_add = blocklist(ctx).call(json.dumps({"action": "add", "company_or_job": "某某公司"}))
    out_list = blocklist(ctx).call(json.dumps({"action": "list"}))
    assert "某某公司" in out_add
    assert "某某公司" in out_list


def test_view_resume_delegation():
    ctx = FakeCtx()
    out = view_resume(ctx).call("{}")
    assert "罗帅" in out
    assert "18K以上" in out


# ------------------------- mock 工具必填 + JSON -------------------------
def test_mock_hr_questions_requires_resume():
    ctx = FakeCtx()
    out_empty = mock_hr_questions(ctx).call(json.dumps({}))
    assert "缺少简历" in out_empty
    out_ok = mock_hr_questions(ctx).call(json.dumps({"resume_text": "简历内容", "count": 3}))
    assert "HR 模拟提问" in out_ok
    parsed = json.loads(out_ok.split("HR 模拟提问：", 1)[1])
    assert parsed["hr_questions"][0]["gap"] == "是"


def test_mock_interview_questions_requires_jd():
    ctx = FakeCtx()
    out_empty = mock_interview_questions(ctx).call(json.dumps({}))
    assert "缺少目标岗位 JD" in out_empty
    out_ok = mock_interview_questions(ctx).call(json.dumps({"target_job_jd": "JD内容", "count": 2}))
    assert "面试模拟提问" in out_ok
    parsed = json.loads(out_ok.split("面试模拟提问：", 1)[1])
    assert parsed["interview_questions"][0]["category"] == "技术"


# ------------------------- 强制停止契约 -------------------------
def test_stop_requested_contract():
    ctx = FakeCtx()
    ctx.stop_requested = True
    out = run_campaign(ctx).call(json.dumps({"keyword": "AI"}))
    parsed = json.loads(out.split("campaign 结束：", 1)[1])
    assert parsed["stopped_by_user"] is True
    # 既有工具调用也带 stopped_by_user（search/browse/view_messages 返回结构）
    sctx = FakeCtx()
    sctx.stop_requested = True
    r = search_jobs(sctx).call(json.dumps({"keyword": "AI", "greet": True}))
    assert "True" in r

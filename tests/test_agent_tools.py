"""Agent 工具与装配测试（离线，不依赖设备 / 网络）。

覆盖：
  - 三个工具的 call 正确编排 ctx 的子流程并返回结构化文案
  - build_agent 能离线构造 FnCallAgent 并注册三个工具
  - run_agent_mode 的循环逻辑（mock 掉真实 bot）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_mode  # noqa: E402
from agent_tools import (  # noqa: E402
    browse_jobs,
    db_operation,
    modify_prompt,
    save_info,
    search_jobs,
    view_messages,
)


class FakeCtx:
    def __init__(self):
        self.search_calls = []
        self.browse_count = 2
        self.view_result = "success"
        self.db_calls = []
        self.prompt_calls = []
        self.saved_items = None

    def search_jobs(self, keyword=""):
        self.search_calls.append(keyword)
        return "ok"

    def browse_jobs(self):
        return self.browse_count

    def view_messages(self):
        return self.view_result

    def db_operation(self, operation, params):
        self.db_calls.append((operation, params))
        return {"op": operation}

    def modify_prompt(self, action, name, text):
        self.prompt_calls.append((action, name, text))
        if action == "get":
            return f"[{name}] content"
        return True, f"updated {name}"

    def save_info(self, items):
        self.saved_items = items
        return f"saved {len(items)}"


def test_search_jobs_tool_orchestrates_ctx():
    ctx = FakeCtx()
    tool = search_jobs(ctx)
    out = tool.call('{"keyword": "AI 应用开发"}')
    assert "搜索岗位已完成" in out
    assert ctx.search_calls == ["AI 应用开发"]


def test_search_jobs_tool_empty_keyword():
    ctx = FakeCtx()
    tool = search_jobs(ctx)
    out = tool.call("{}")
    assert "搜索岗位已完成" in out
    assert ctx.search_calls == [""]


def test_browse_jobs_tool_orchestrates_ctx():
    ctx = FakeCtx()
    tool = browse_jobs(ctx)
    out = tool.call("")
    assert "浏览岗位完成" in out
    assert "2 个岗位" in out


def test_view_messages_tool_orchestrates_ctx():
    ctx = FakeCtx()
    tool = view_messages(ctx)
    out = tool.call("")
    assert "查看消息完成" in out
    assert "success" in out


def test_build_agent_registers_three_tools():
    ctx = FakeCtx()
    bot = agent_mode.build_agent(ctx)
    assert isinstance(bot, agent_mode.FnCallAgent)
    fm = getattr(bot, "function_map", None)
    if fm is not None:
        assert set(fm.keys()) >= {
            "search_jobs", "browse_jobs", "view_messages",
            "db_operation", "modify_prompt", "save_info",
        }


def test_db_operation_tool_orchestrates_ctx():
    ctx = FakeCtx()
    tool = db_operation(ctx)
    out = tool.call('{"operation": "get_job", "params": {"company": "X", "hr_name": "张三"}}')
    assert ctx.db_calls == [("get_job", {"company": "X", "hr_name": "张三"})]
    assert "get_job" in out


def test_modify_prompt_get_and_update():
    ctx = FakeCtx()
    tool = modify_prompt(ctx)
    out_get = tool.call('{"action": "get", "name": "system"}')
    assert "[system] content" in out_get
    out_upd = tool.call('{"action": "update", "name": "check_new_job", "text": "新规则"}')
    assert "成功" in out_upd and "updated check_new_job" in out_upd
    assert ctx.prompt_calls == [
        ("get", "system", ""),
        ("update", "check_new_job", "新规则"),
    ]


def test_save_info_from_dict():
    ctx = FakeCtx()
    tool = save_info(ctx)
    out = tool.call('{"info": {"期望薪资": "20-30K", "当前城市": "深圳"}}')
    assert "已保存 2 条" in out
    assert ctx.saved_items == [
        {"category": "HR对话信息", "field_name": "期望薪资", "field_value": "20-30K", "source": "HR对话模拟"},
        {"category": "HR对话信息", "field_name": "当前城市", "field_value": "深圳", "source": "HR对话模拟"},
    ]


def test_save_info_from_structured_list():
    ctx = FakeCtx()
    tool = save_info(ctx)
    payload = '{"info": [{"category": "技能", "field_name": "Python", "field_value": "熟悉", "source": "HR对话"}]}'
    out = tool.call(payload)
    assert "已保存 1 条" in out
    assert ctx.saved_items[0]["field_name"] == "Python"


def test_save_info_empty_is_safe():
    ctx = FakeCtx()
    tool = save_info(ctx)
    out = tool.call('{"info": {}}')
    assert "没有可保存" in out


def test_run_agent_mode_loop(monkeypatch):
    ctx = FakeCtx()

    class FakeBot:
        def run(self, messages):
            yield [
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": "done"},
            ]

    monkeypatch.setattr(agent_mode, "build_agent", lambda c: FakeBot())
    final = agent_mode.run_agent_mode(ctx=ctx, initial_message="go", max_rounds=5)
    assert final[-1]["content"] == "done"

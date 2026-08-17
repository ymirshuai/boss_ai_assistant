"""agent_session 单例的只读 API 冒烟测试（不触屏、不调 LLM）。

只覆盖「受理/状态/目标/重置」这类安全、确定性的接口；
不发送非空消息，避免后台线程真去构造 FnCallAgent 并调用大模型。
"""

from agent_session import session, AgentSession


def test_empty_message_rejected():
    ok, msg = session.send("   ")
    assert ok is False
    assert "空" in msg


def test_status_shape():
    s = session.status()
    assert "busy" in s
    assert "initialized" in s
    assert "touch_ready" in s
    assert "tool_usage" in s
    # 尚未发过消息，应未初始化且不忙
    assert s["busy"] is False


def test_goals_structure():
    g = session.goals()
    assert "date" in g
    assert "goals" in g
    ids = [x["id"] for x in g["goals"]]
    assert ids == ["G1", "G2", "G3", "G4", "G5"]
    for goal in g["goals"]:
        assert "name" in goal and "desc" in goal
        assert "metrics" in goal and isinstance(goal["metrics"], list)
        assert "state" in goal


def test_reset_is_safe():
    # 清空不应抛异常；单例仍可用
    assert session.reset() is True
    assert session.history() == []


def test_fresh_instance_goals():
    # 独立实例（不污染全局单例）也应能产出目标结构
    fresh = AgentSession()
    g = fresh.goals()
    assert len(g["goals"]) == 5

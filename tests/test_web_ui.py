"""Web UI 端点冒烟测试（不依赖真机）。"""

import web_ui
from web_ui import app


def test_index_page():
    c = app.test_client()
    rv = c.get("/")
    assert rv.status_code == 200
    assert "BOSS" in rv.get_data(as_text=True)


def test_status_when_idle():
    c = app.test_client()
    rv = c.get("/api/campaign/status")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["running"] is False
    assert "status" in data


def test_notes_endpoint():
    c = app.test_client()
    rv = c.get("/api/notes")
    assert rv.status_code == 200
    assert "注意事项" in rv.get_data(as_text=True)


def test_agent_chat_accepts():
    c = app.test_client()
    rv = c.post("/api/agent/chat", json={"message": "你好"})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert data["accepted"] is True
    assert "msg" in data


def test_agent_chat_empty_rejected():
    c = app.test_client()
    rv = c.post("/api/agent/chat", json={"message": "   "})
    assert rv.status_code == 400
    data = rv.get_json()
    assert data["accepted"] is False


def test_agent_goals_returns_g1_g5():
    c = app.test_client()
    rv = c.get("/api/agent/goals")
    assert rv.status_code == 200
    data = rv.get_json()
    goals = data.get("goals", [])
    ids = [g["id"] for g in goals]
    assert ids == ["G1", "G2", "G3", "G4", "G5"]


def test_agent_status_json():
    c = app.test_client()
    rv = c.get("/api/agent/status")
    assert rv.status_code == 200
    data = rv.get_json()
    assert "busy" in data and "initialized" in data


def test_agent_stop_and_reset():
    c = app.test_client()
    r1 = c.post("/api/agent/stop")
    assert r1.get_json()["ok"] is True
    r2 = c.post("/api/agent/reset")
    assert r2.get_json()["ok"] is True


def test_logs_stream_route_registered():
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert "/api/logs/stream" in rules
    assert "/api/screenshot" in rules
    assert "/api/campaign/start" in rules
    assert "/api/campaign/stop" in rules
    # Phase 2 新增端点
    assert "/api/agent/chat" in rules
    assert "/api/agent/stream" in rules
    assert "/api/agent/goals" in rules
    assert "/api/agent/history" in rules
    assert "/api/agent/status" in rules
    assert "/api/agent/stop" in rules
    assert "/api/agent/reset" in rules

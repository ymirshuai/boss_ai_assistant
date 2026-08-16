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


def test_agent_chat_stub():
    c = app.test_client()
    rv = c.post("/api/agent/chat", json={"message": "你好"})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert "开发" in data["reply"]


def test_logs_stream_route_registered():
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert "/api/logs/stream" in rules
    assert "/api/screenshot" in rules
    assert "/api/campaign/start" in rules
    assert "/api/campaign/stop" in rules

"""本地 Web 交互界面（Flask + SSE）。

提供：
- 设置输入：岗位名称、目标打招呼数、运行时长（可选）
- 注意事项按钮、开始自动打招呼/回消息按钮、停止按钮
- 运行日志面板（SSE 实时推送）
- 最新截图展示
- 预留与 Agent 对话的消息框

启动方式：
    python web_ui.py
或
    BOSS_MODE=ui python main.py
"""

import base64
import json
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)

import log_broadcast

app = Flask(__name__, template_folder="templates")

# 当前运行中的 assistant 与线程（进程内单例）
_current = {"assistant": None, "thread": None, "lock": threading.Lock()}

NOTES_FILE = Path(__file__).parent / "notes.md"
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMCAQDJ/3pUAAAAAElFTkSuQmCC"
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_app() -> Flask:
    return app


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/campaign/status")
def campaign_status():
    with _current["lock"]:
        a = _current["assistant"]
    if a is None:
        return jsonify({
            "running": False,
            "status": "空闲",
            "keyword": None,
            "target": None,
            "today_greet_count": 0,
            "latest_screenshot": None,
            "session_id": None,
        })
    return jsonify(a.status())


@app.route("/api/screenshot")
def screenshot():
    with _current["lock"]:
        a = _current["assistant"]
    path = a.latest_screenshot_path if a else None
    if path and Path(path).exists():
        return send_file(path, mimetype="image/png")
    return Response(_PLACEHOLDER_PNG, mimetype="image/png")


@app.route("/api/campaign/start", methods=["POST"])
def start_campaign():
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword") or None
    target = data.get("target_greet_count")
    duration = data.get("duration")

    with _current["lock"]:
        if _current["assistant"] and _current["assistant"].running:
            return jsonify({"ok": False, "msg": "已有 campaign 在运行，请先停止"}), 409

    def _run():
        try:
            import main  # 懒加载：触发 Airtest 设备初始化（仅真机环境）
            a = main.BOSSAssistant()
            with _current["lock"]:
                _current["assistant"] = a
            a.run_campaign(keyword=keyword, target_greet_count=target, duration=duration)
        except Exception as e:
            log_broadcast.broadcast({
                "ts": _now(), "level": "ERROR",
                "msg": f"campaign 启动/运行异常：{e}", "sid": "ui",
            })
            with _current["lock"]:
                if _current["assistant"]:
                    _current["assistant"].running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    with _current["lock"]:
        _current["thread"] = t
    return jsonify({"ok": True, "msg": "已启动 campaign"})


@app.route("/api/campaign/stop", methods=["POST"])
def stop_campaign():
    with _current["lock"]:
        a = _current["assistant"]
    if a:
        a.stop()
        return jsonify({"ok": True, "msg": "已发送停止信号"})
    return jsonify({"ok": True, "msg": "当前无运行中的 campaign"})


@app.route("/api/logs/stream")
def logs_stream():
    q = log_broadcast.subscribe()

    def gen():
        yield "retry: 3000\n\n"
        # 先补播历史缓冲
        for entry in log_broadcast.drain_buffer():
            yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    entry = q.get(timeout=30)
                except Exception:
                    yield ": ping\n\n"  # 心跳保持连接
                    continue
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        finally:
            log_broadcast.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream")


@app.route("/api/notes")
def notes():
    if NOTES_FILE.exists():
        return Response(NOTES_FILE.read_text(encoding="utf-8"),
                        mimetype="text/plain; charset=utf-8")
    return Response("（暂无注意事项）", mimetype="text/plain; charset=utf-8")


@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    """预留：与 Agent 对话的接口，尚未接入实际 Agent 逻辑。"""
    data = request.get_json(silent=True) or {}
    msg = data.get("message", "")
    return jsonify({
        "ok": True,
        "reply": "（Agent 对话模块开发中，暂未接入。此消息框已预留，后续可让助手查看简历、"
                 "搜索岗位、统计共性并给出方向建议，或唤起循环模式批量打招呼。）",
        "echo": msg,
    })


def run_ui(host="0.0.0.0", port=5000):
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_ui()

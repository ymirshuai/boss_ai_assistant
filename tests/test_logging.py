"""
验证日志可回溯改动（T日志）：
  - setup_logging 能把标准库 logging 写入日志文件（带时间戳/级别/会话ID）
  - 自定义 Logger.log / log_error 行内携带 session_id
"""
import logging
import sys

import pytest

# 不触发 airtest_connector 的 auto_setup：用假模块占位
sys.modules.setdefault("airtest_connector", type(sys)("airtest_connector"))

import config  # noqa: E402
from logger import Logger, setup_logging  # noqa: E402


@pytest.fixture
def log_paths(monkeypatch, tmp_path):
    """把日志路径重定向到临时目录（避免触碰真实 logs/ 与 safe-delete 拦截），并重置状态。"""
    import logger as logger_mod

    monkeypatch.setitem(config.FILE_PATHS, "stats_log", str(tmp_path / "stats.log"))
    monkeypatch.setitem(config.FILE_PATHS, "error_log", str(tmp_path / "error.log"))
    monkeypatch.setattr(logger_mod, "_LOGGING_CONFIGURED", False)
    monkeypatch.setattr(logger_mod, "RUN_SESSION_ID", "")
    monkeypatch.setattr(logger_mod, "_RUN_STATS_LOG_PATH", None)
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)
    return tmp_path


def _find_stats_log(log_paths):
    """本次运行写入的是带时间戳的 stats_<ts>.log，用 glob 找到它。"""
    logs = list(log_paths.glob("stats_*.log"))
    assert logs, "未生成带时间戳的 stats 日志文件"
    return logs[0]


def test_logger_log_carries_session_id(log_paths):
    lg = Logger()
    sid = lg.session_id
    assert sid
    lg.log("测试消息", "INFO")
    content = _find_stats_log(log_paths).read_text(encoding="utf-8")
    assert sid[:8] in content
    assert "测试消息" in content


def test_setup_logging_writes_stdlib_to_file(log_paths):
    sid = "abc12345-0000-0000-0000-000000000000"
    setup_logging(sid)
    logging.getLogger("llm_client").info("模型调用成功 | 响应预览=hello")
    content = _find_stats_log(log_paths).read_text(encoding="utf-8")
    assert "模型调用成功" in content
    assert "hello" in content
    assert "llm_client" in content
    assert sid[:8] in content


def test_setup_logging_idempotent(log_paths):
    setup_logging("sid-one")
    n1 = len(logging.getLogger().handlers)
    setup_logging("sid-two")  # 重复调用不应再添加 handler
    n2 = len(logging.getLogger().handlers)
    assert n2 == n1
    logging.getLogger("x").info("第二次调用")
    lines = _find_stats_log(log_paths).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # 只落盘一次，无重复写入


def test_stats_log_is_timestamped_per_run(log_paths):
    """每次运行应生成带启动时间戳的独立 stats 文件。"""
    lg = Logger()
    lg.log("运行开始", "INFO")
    log_file = _find_stats_log(log_paths)
    import re

    assert re.match(r"stats_\d{8}_\d{6}\.log$", log_file.name), log_file.name
    assert "运行开始" in log_file.read_text(encoding="utf-8")


def test_log_error_carries_session_id(log_paths):
    lg = Logger()
    sid = lg.session_id[:8]
    lg.log_error("主循环异常", "boom")
    content = (log_paths / "error.log").read_text(encoding="utf-8")
    assert "主循环异常" in content
    assert "boom" in content
    assert f"sid:{sid}" in content

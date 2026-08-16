"""
日志统计模块
负责日志记录和统计面板显示
"""

import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from config import FILE_PATHS
import log_broadcast

# ---------------------------------------------------------------------------
# 标准库 logging 统一接入（修复「隐形日志」问题）
# agent_mode / llm_client / ocr_service / agent_tools 使用标准库 logging，
# 但项目原本从未配置 handler，导致这些日志既不落盘、INFO 级还直接丢失。
# setup_logging 把它们也写到 logs/stats.log（与自定义 Logger 同一文件）。
# ---------------------------------------------------------------------------
_LOGGING_CONFIGURED = False
_LOGGING_LOCK = threading.Lock()
RUN_SESSION_ID = ""

# 本次运行的 stats 日志路径（带启动时间戳，进程内只生成一次）。
# 文件名形如 logs/stats_20260816_142829.log，每次运行独立成文件，便于按时间回溯某一次运行。
_RUN_STATS_LOG_PATH = None
_RUN_STATS_LOG_LOCK = threading.Lock()


def resolve_stats_log_path() -> str:
    """返回本次运行的 stats 日志路径（进程内只生成一次）。

    基于 FILE_PATHS["stats_log"]（logs/stats.log）派生出带启动时间戳的文件名，
    例如 logs/stats_20260816_142829.log。每次运行（进程）独立成文件。
    """
    global _RUN_STATS_LOG_PATH
    if _RUN_STATS_LOG_PATH is None:
        with _RUN_STATS_LOG_LOCK:
            if _RUN_STATS_LOG_PATH is None:
                base = Path(FILE_PATHS["stats_log"])
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                _RUN_STATS_LOG_PATH = str(base.parent / f"stats_{ts}.log")
    return _RUN_STATS_LOG_PATH


class _SessionFilter(logging.Filter):
    def filter(self, record):
        record.session_id = RUN_SESSION_ID
        return True


def setup_logging(session_id: str = "", level: int = logging.INFO) -> None:
    """配置标准库 logging：写入 logs/stats.log + stderr，带时间戳/级别/会话ID。

    Args:
        session_id: 本次运行会话 ID，注入到每条日志便于跨重启关联。
        level: 根日志级别（默认 INFO）。
    """
    global _LOGGING_CONFIGURED, RUN_SESSION_ID
    if session_id:
        RUN_SESSION_ID = session_id
    if _LOGGING_CONFIGURED:
        return
    with _LOGGING_LOCK:
        if _LOGGING_CONFIGURED:
            return
        log_file = resolve_stats_log_path()
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s [%(session_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(_SessionFilter())
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.addFilter(_SessionFilter())
        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(fh)
        root.addHandler(sh)
        _LOGGING_CONFIGURED = True


class Logger:
    """日志类"""
    
    def __init__(self):
        self.start_time = time.time()
        self.session_id = str(uuid.uuid4())
        self.stats = {
            "browse_count": 0,
            "greet_count": 0,
            "skip_count": 0,
            "reply_count": 0,
            "resume_sent": 0,
            "wechat_sent": 0,
            "error_count": 0,
        }
        self.error_log = FILE_PATHS["error_log"]
        self.stats_log = resolve_stats_log_path()
    
    def log(self, msg, level="INFO"):
        """打印日志（带时间戳）
        
        Args:
            msg: 日志内容
            level: 日志级别（INFO/SUCCESS/WARNING/ERROR）
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = {
            "INFO": "ℹ️ ",
            "SUCCESS": "✅",
            "WARNING": "⚠️ ",
            "ERROR": "❌",
        }.get(level, "ℹ️ ")
        
        formatted_msg = f"[{timestamp}] {prefix} [{self.session_id[:8]}] {msg}"
        print(formatted_msg)

        # 写入日志文件
        with open(self.stats_log, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")

        # 广播给 Web UI 等订阅方（进程内，无设备也不影响）
        log_broadcast.broadcast({
            "ts": timestamp,
            "level": level,
            "msg": msg,
            "sid": self.session_id[:8],
        })
    
    def log_error(self, error_type, error_msg, screenshot_path=None):
        """记录错误
        
        Args:
            error_type: 错误类型
            error_msg: 错误信息
            screenshot_path: 截图路径
        """
        self.stats["error_count"] += 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {error_type}: {error_msg} [sid:{self.session_id[:8]}]\n"
        if screenshot_path:
            log_msg += f"  截图：{screenshot_path}\n"
        log_msg += "-" * 50 + "\n"

        with open(self.error_log, "a", encoding="utf-8") as f:
            f.write(log_msg)

        # 广播错误（级别 ERROR），便于 UI 实时高亮
        log_broadcast.broadcast({
            "ts": timestamp,
            "level": "ERROR",
            "msg": f"{error_type}: {error_msg}",
            "sid": self.session_id[:8],
        })
    
    def update_stats(self, key, value=1):
        """更新统计数据
        
        Args:
            key: 统计项名称
            value: 增加的值（默认 1）
        """
        if key in self.stats:
            self.stats[key] += value
    
    def print_stats(self):
        """打印统计面板"""
        elapsed = time.time() - self.start_time
        elapsed_min = int(elapsed / 60)
        elapsed_hour = int(elapsed / 3600)
        
        print("\n" + "=" * 50)
        print("📊 运行统计")
        print("=" * 50)
        print(f"⏱️  运行时长：{elapsed_hour} 小时 {elapsed_min % 60} 分钟")
        print(f"👀 浏览岗位：{self.stats['browse_count']} 个")
        print(f"👋 成功打招呼：{self.stats['greet_count']} 个")
        print(f"⏭️  跳过（不匹配）：{self.stats['skip_count']} 个")
        print(f"💬 回复消息：{self.stats['reply_count']} 条")
        print(f"📄 发送简历：{self.stats['resume_sent']} 次")
        print(f"📱 发送微信：{self.stats['wechat_sent']} 次")
        print(f"❌ 异常次数：{self.stats['error_count']} 次")
        print("=" * 50 + "\n")

        # 保存统计数据到数据库（按天统计）
        self.save_stats_to_db(elapsed)

    def save_stats_to_db(self, elapsed=None):
        """将当前统计快照保存到数据库 daily_stats 表（在调用 print_stats 时触发）

        Args:
            elapsed: 累计运行时长（秒）；为空时自动计算
        """
        if elapsed is None:
            elapsed = time.time() - self.start_time
        try:
            from data_store import save_daily_stats
            save_daily_stats(self.session_id, self.stats, elapsed)
        except Exception as e:
            # 数据库保存失败不应中断主流程
            self.log(f"统计数据入库失败：{e}", "WARNING")

    def save_stats(self):
        """保存统计数据到文件"""
        import json
        
        stats_data = {
            "start_time": self.start_time,
            "end_time": time.time(),
            "stats": self.stats
        }
        
        with open(self.stats_log.replace(".log", ".json"), "w", encoding="utf-8") as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)

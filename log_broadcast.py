"""进程内事件广播（发布/订阅，支持多通道）。

用于把运行日志、Agent 对话事件实时推送给 Web UI 的 SSE 流，不依赖任何外部组件。

两条通道：
- `logs`（默认通道）：运行日志。`Logger.log` / `Logger.log_error` 调用模块级
  `broadcast()` 推送；Web UI `/api/logs/stream` 订阅。
- `agent`：Agent 对话事件（用户消息、助手增量、工具调用与结果、结束/异常）。
  `agent_session` 推送；Web UI `/api/agent/stream` 订阅。

模块级 `subscribe/unsubscribe/broadcast/drain_buffer` 保持原有语义（等价于操作
`logs` 通道），保证既有调用方无需改动。
"""

import collections
import queue
import threading


class Channel:
    """一个独立的发布/订阅通道，带固定长度历史缓冲。"""

    def __init__(self, name: str, maxlen: int = 300):
        self.name = name
        self._subscribers = []
        self._buffer = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def subscribe(self):
        """返回一个新订阅队列（queue.Queue）。"""
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def broadcast(self, entry: dict):
        """广播一条事件，并写入历史缓冲。"""
        self._buffer.append(entry)
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(entry)
            except queue.Full:
                pass

    def drain_buffer(self):
        """返回当前历史缓冲快照（供新订阅者补播）。"""
        return list(self._buffer)

    def clear_buffer(self):
        """清空历史缓冲（重置会话时用）。"""
        self._buffer.clear()

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


# 运行日志通道（默认）与 Agent 事件通道
logs = Channel("logs")
agent = Channel("agent", maxlen=500)


# ---- 向后兼容的模块级 API（等价于操作 logs 通道）----
def subscribe():
    return logs.subscribe()


def unsubscribe(q):
    logs.unsubscribe(q)


def broadcast(entry: dict):
    """广播一条日志条目。

    entry 形如 {"ts": "...", "level": "INFO", "msg": "...", "sid": "..."}
    """
    logs.broadcast(entry)


def drain_buffer():
    return logs.drain_buffer()

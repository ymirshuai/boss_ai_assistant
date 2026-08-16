"""进程内日志广播（发布/订阅）。

用于把运行日志实时推送给 Web UI 的 SSE 流，不依赖任何外部组件。
- Logger.log / Logger.log_error 调用 broadcast() 推日志。
- Web UI 的 SSE 端点通过 subscribe() 订阅，drain_buffer() 可取历史 backlog。
"""

import collections
import queue
import threading

_subscribers = []
_buffer = collections.deque(maxlen=300)
_lock = threading.Lock()


def subscribe():
    """返回一个新订阅队列（queue.Queue）。"""
    q = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q):
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def broadcast(entry: dict):
    """广播一条日志条目，并写入历史缓冲。

    entry 形如 {"ts": "...", "level": "INFO", "msg": "...", "sid": "..."}
    """
    _buffer.append(entry)
    with _lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(entry)
            except queue.Full:
                pass


def drain_buffer():
    """返回当前历史缓冲快照（供新订阅者补播）。"""
    return list(_buffer)

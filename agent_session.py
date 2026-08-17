"""Agent 对话会话（进程内单例）。

把 `agent_mode` 的 FnCallAgent 包装成「可多轮对话 + 事件流式回传 + 可强制停止」的会话，
供 Web UI 第 4 面板（与 Agent 对话）使用。

设计要点：
- **懒构造**：模块 import 时不碰 `agent_mode`（它会连真机），首次发消息才构造 ctx/bot。
- **流式事件**：`bot.run()` 每次 yield 的是本轮累计的新消息列表，逐次 diff 后以事件形式
  推到 `log_broadcast.agent` 通道：
    user / assistant_delta / tool_call / tool_result / done / error / stopped / reset
- **强制停止**（安全模型，见 agent_mode_design.md）：`stop()` 同时置位
  `AgentContext.stop_requested`（触屏工具循环内检查）与本会话 `stop_requested`（中断迭代）。
- **无二次确认**：工具直接执行，用户永远握着"急停"。
"""

import json
import threading
import traceback
from datetime import datetime

import log_broadcast

# 历史消息上限（防止上下文无限膨胀）；裁剪时保证从 user 消息开始，不切断 assistant/function 配对
MAX_HISTORY_MESSAGES = 40
# 聚合分析结果缓存秒数（goals 面板轮询较频繁，避免每次全表扫聊天记录）
_AGGREGATE_TTL = 20.0


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _as_text(content) -> str:
    """把消息 content 归一成纯文本（可能是 str 或 ContentItem 列表）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text") or "")
            else:
                parts.append(str(getattr(c, "text", "") or ""))
        return "".join(parts)
    return str(content)


def _get(msg, key, default=None):
    """兼容 dict 与 Message 对象的取值。"""
    if isinstance(msg, dict):
        return msg.get(key, default)
    return getattr(msg, key, default)


class AgentSession:
    """一个进程内的 Agent 对话会话。"""

    def __init__(self):
        self.messages = []      # qwen_agent 格式的对话历史（dict）
        self.transcript = []    # 供前端渲染/刷新恢复的可读记录
        self.busy = False
        self.stop_requested = False
        self.tool_usage = {}    # 工具名 → 调用次数
        self.last_campaign = None   # 最近一次 run_campaign 工具结果原文
        self.last_error = None
        self._bot = None
        self._ctx = None
        self._lock = threading.RLock()
        self._thread = None
        self._agg_cache = None
        self._agg_at = 0.0

    # ---------------- 懒构造 ----------------
    @property
    def ctx(self):
        if self._ctx is None:
            import agent_mode  # 懒导入：模块级 import 会牵出 airtest

            self._ctx = agent_mode.AgentContext()
        return self._ctx

    @property
    def bot(self):
        if self._bot is None:
            import agent_mode

            self._bot = agent_mode.build_agent(self.ctx)
        return self._bot

    def initialized(self) -> bool:
        return self._bot is not None

    # ---------------- 事件 ----------------
    def _emit(self, type_: str, **payload):
        entry = {"ts": _now(), "type": type_}
        entry.update(payload)
        log_broadcast.agent.broadcast(entry)
        return entry

    # ---------------- 对外 API ----------------
    def send(self, message: str):
        """受理一条用户消息，后台线程执行，立即返回。"""
        message = (message or "").strip()
        if not message:
            return False, "消息不能为空"
        with self._lock:
            if self.busy:
                return False, "Agent 正在处理上一条消息，请稍候或点「停止」"
            self.busy = True
            self.stop_requested = False
            if self._ctx is not None:
                self._ctx.stop_requested = False
        self._thread = threading.Thread(
            target=self._run_turn, args=(message,), daemon=True
        )
        self._thread.start()
        return True, "已受理"

    def stop(self):
        """强制停止：贯通 ctx.stop_requested（触屏工具）与本会话迭代。"""
        self.stop_requested = True
        if self._ctx is not None:
            self._ctx.stop_requested = True
        self._emit("stopped", text="已发送强制停止信号（触屏动作会在下一个检查点中止并回主页）")
        return True

    def reset(self):
        """清空对话历史与事件缓冲（不影响已落库的数据）。"""
        with self._lock:
            self.messages = []
            self.transcript = []
            self.last_error = None
        log_broadcast.agent.clear_buffer()
        self._emit("reset", text="对话已清空")
        return True

    def history(self):
        return list(self.transcript)

    def status(self):
        return {
            "busy": self.busy,
            "stop_requested": self.stop_requested,
            "initialized": self.initialized(),
            "touch_ready": self._ctx.touch_available() if self._ctx is not None else False,
            "turns": len([m for m in self.transcript if m.get("role") == "user"]),
            "tool_usage": dict(self.tool_usage),
            "last_error": self.last_error,
        }

    # ---------------- 执行一轮 ----------------
    def _run_turn(self, message: str):
        self.transcript.append({"role": "user", "text": message, "ts": _now()})
        self._emit("user", text=message)
        seen_text, seen_tool, seen_result = {}, set(), set()
        final = []
        assistant_texts = {}
        try:
            bot = self.bot  # 首次会构造 FnCallAgent（不连设备）
            convo = self.messages + [{"role": "user", "content": message}]
            for resp in bot.run(convo):
                final = resp
                self._scan(resp, seen_text, seen_tool, seen_result, assistant_texts)
                if self.stop_requested:
                    self._emit("assistant_delta", text="\n\n（已被用户强制停止）")
                    break
            with self._lock:
                self.messages = self._trim(convo + [self._plain(m) for m in final])
            reply = "\n".join(t for t in assistant_texts.values() if t.strip())
            if reply:
                self.transcript.append({"role": "assistant", "text": reply, "ts": _now()})
            self._emit(
                "done",
                stopped=self.stop_requested,
                text=reply[-2000:] if reply else "（本轮无文本回复）",
            )
        except Exception as e:
            self.last_error = str(e)
            detail = traceback.format_exc()
            self.transcript.append(
                {"role": "error", "text": f"Agent 执行失败：{e}", "ts": _now()}
            )
            self._emit("error", text=f"Agent 执行失败：{e}", detail=detail[-1000:])
        finally:
            with self._lock:
                self.busy = False

    def _scan(self, resp, seen_text, seen_tool, seen_result, assistant_texts):
        """diff 本轮累计消息，产出增量事件。"""
        for i, m in enumerate(resp):
            role = _get(m, "role", "") or ""
            content = _as_text(_get(m, "content", ""))
            fc = _get(m, "function_call", None) or {}
            if isinstance(fc, dict):
                fc_name = fc.get("name") or ""
                fc_args = fc.get("arguments") or ""
            else:
                fc_name = getattr(fc, "name", "") or ""
                fc_args = getattr(fc, "arguments", "") or ""

            if role == "assistant" and fc_name:
                if i not in seen_tool:
                    seen_tool.add(i)
                    self.tool_usage[fc_name] = self.tool_usage.get(fc_name, 0) + 1
                    self._emit("tool_call", name=fc_name, arguments=str(fc_args)[:400])
                    self.transcript.append({
                        "role": "tool", "tool": fc_name,
                        "text": f"调用工具 {fc_name}", "ts": _now(),
                    })
            elif role == "assistant":
                prev = seen_text.get(i, "")
                if content and content != prev:
                    delta = content[len(prev):] if content.startswith(prev) else content
                    seen_text[i] = content
                    assistant_texts[i] = content
                    if delta:
                        self._emit("assistant_delta", text=delta, index=i)
            elif role == "function":
                if i not in seen_result:
                    seen_result.add(i)
                    name = _get(m, "name", "") or ""
                    # 回看上一条 assistant 的最终 arguments，补全参数展示
                    args = ""
                    if i > 0:
                        prev_fc = _get(resp[i - 1], "function_call", None) or {}
                        args = (prev_fc.get("arguments") if isinstance(prev_fc, dict)
                                else getattr(prev_fc, "arguments", "")) or ""
                    if name == "run_campaign":
                        self.last_campaign = content[:2000]
                    self._emit("tool_result", name=name,
                               arguments=str(args)[:400], text=content[:1500])
                    self.transcript.append({
                        "role": "tool_result", "tool": name,
                        "text": content[:1000], "ts": _now(),
                    })

    @staticmethod
    def _plain(m):
        """把 Message 归一成 dict，便于写回历史。"""
        if isinstance(m, dict):
            return m
        if hasattr(m, "model_dump"):
            try:
                return m.model_dump()
            except Exception:
                pass
        return {"role": _get(m, "role", "assistant"),
                "content": _as_text(_get(m, "content", ""))}

    @staticmethod
    def _trim(messages):
        """裁剪历史：超长时从头丢弃，直到首条是 user，避免切断 assistant/function 配对。"""
        if len(messages) <= MAX_HISTORY_MESSAGES:
            return messages
        cut = messages[-MAX_HISTORY_MESSAGES:]
        while cut and (cut[0].get("role") if isinstance(cut[0], dict) else "") != "user":
            cut.pop(0)
        return cut or messages[-1:]

    # ---------------- 目标面板（G1–G5）----------------
    def _aggregate(self):
        """带 TTL 缓存的聚合数据（岗位/回复率等，全表扫描较重）。"""
        import time as _t

        if self._agg_cache is not None and (_t.time() - self._agg_at) < _AGGREGATE_TTL:
            return self._agg_cache
        data = {"total_jobs": 0, "reply_rate": 0.0, "hr_messages": 0, "my_messages": 0}
        try:
            from data_store import get_all_jobs, get_chat_history

            jobs = get_all_jobs()
            hr = me = 0
            for j in jobs:
                for c in get_chat_history(j["id"]):
                    if c["sender"] == "hr":
                        hr += 1
                    elif c["sender"] == "me":
                        me += 1
            data = {
                "total_jobs": len(jobs),
                "hr_messages": hr,
                "my_messages": me,
                "reply_rate": round(hr / me, 3) if me else 0.0,
            }
        except Exception as e:
            data["error"] = str(e)
        self._agg_cache = data
        self._agg_at = _t.time()
        return data

    def goals(self):
        """返回 G1–G5 目标进度（供 Web UI 目标面板）。

        数值全部来自真实数据源（daily_stats / jobs / user_info / blocklist / 会话工具计数），
        无法取到时降级为 0，不编造。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        greeted = browsed = replied = 0
        target = 0
        info_fields = blocked = 0
        try:
            from data_store import get_today_greet_count

            greeted = get_today_greet_count()
        except Exception:
            pass
        try:
            from data_store import get_daily_summary

            rows = get_daily_summary(today) or []
            if rows:
                browsed = rows[0].get("browse_count", 0)
                replied = rows[0].get("reply_count", 0)
        except Exception:
            pass
        try:
            from config import BEHAVIOR_CONFIG

            target = BEHAVIOR_CONFIG.get("greet_per_day", 0)
        except Exception:
            pass
        try:
            from data_store import get_user_info

            info_fields = len(get_user_info())
        except Exception:
            pass
        try:
            import agent_mode

            blocked = len(agent_mode.load_blocklist())
        except Exception:
            pass

        agg = self._aggregate()
        tu = self.tool_usage
        mock_used = tu.get("mock_hr_questions", 0) + tu.get("mock_interview_questions", 0)
        strategy_used = (tu.get("modify_prompt", 0) + tu.get("blocklist", 0)
                         + tu.get("run_campaign", 0))

        def state(v):
            return "进行中" if v else "未开始"

        goals = [
            {
                "id": "G1", "name": "海投获客",
                "desc": "找岗位、批量打招呼，扩大曝光",
                "metrics": [
                    {"label": "今日打招呼", "value": greeted},
                    {"label": "今日浏览岗位", "value": browsed},
                    {"label": "每日目标", "value": target},
                ],
                "progress": min(100, round(greeted / target * 100)) if target else 0,
                "state": "已达成" if target and greeted >= target else state(greeted),
            },
            {
                "id": "G2", "name": "跟进转化",
                "desc": "回复 HR、推进沟通到下一步",
                "metrics": [
                    {"label": "今日回复", "value": replied},
                    {"label": "HR 来信总数", "value": agg.get("hr_messages", 0)},
                ],
                "progress": None,
                "state": state(replied),
            },
            {
                "id": "G3", "name": "信息沉淀与复盘",
                "desc": "记录岗位/HR 信息，聚合分析回复率",
                "metrics": [
                    {"label": "已记录岗位", "value": agg.get("total_jobs", 0)},
                    {"label": "回复率", "value": agg.get("reply_rate", 0.0)},
                    {"label": "analyze 调用", "value": tu.get("analyze_jobs", 0)},
                ],
                "progress": None,
                "state": state(agg.get("total_jobs", 0)),
            },
            {
                "id": "G4", "name": "策略配置",
                "desc": "调匹配规则/人设、拉黑公司、唤起循环",
                "metrics": [
                    {"label": "已拉黑", "value": blocked},
                    {"label": "策略类工具调用", "value": strategy_used},
                ],
                "progress": None,
                "state": state(strategy_used or blocked),
            },
            {
                "id": "G5", "name": "准备与练习",
                "desc": "模拟 HR 提问补资料库；模拟面试题预演",
                "metrics": [
                    {"label": "资料库字段", "value": info_fields},
                    {"label": "本会话出题次数", "value": mock_used},
                ],
                "progress": None,
                "state": state(mock_used or info_fields),
            },
        ]
        return {
            "date": today,
            "goals": goals,
            "last_campaign": self.last_campaign,
            "agent": self.status(),
        }


# 进程内单例
session = AgentSession()

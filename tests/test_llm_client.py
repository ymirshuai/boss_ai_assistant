"""LLMClient 的纯函数部分测试（不依赖网络；qwen_agent 仅在构造检查里惰性导入）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_client import LLMClient


# ---- 模拟 qwen_agent 的 Message 对象 ----
class _FakeMsg:
    def __init__(self, content):
        self.content = content


def test_extract_json_fenced():
    assert LLMClient.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_trailing_text():
    assert LLMClient.extract_json('some text {"is_match": true} extra') == {"is_match": True}


def test_extract_json_nested_braces():
    assert LLMClient.extract_json('{"job_info": {"a": 1}}') == {"job_info": {"a": 1}}


def test_extract_json_empty_raises():
    try:
        LLMClient.extract_json("")
        assert False, "应抛异常"
    except ValueError:
        pass


def test_extract_text_from_message_obj():
    assert LLMClient._extract_text(_FakeMsg("hi")) == "hi"


def test_extract_text_from_message_list_content():
    assert LLMClient._extract_text(_FakeMsg([{"text": "a"}, {"text": "b"}])) == "ab"


def test_extract_text_from_dict():
    assert LLMClient._extract_text({"content": "x"}) == "x"


def test_extract_text_from_list_of_messages():
    msgs = [_FakeMsg("a"), _FakeMsg("b")]
    assert "".join(LLMClient._extract_text(m) for m in msgs) == "ab"


def test_get_llm_builds_without_network():
    # 显式传参，避免触发 config 导入副作用；不发起真实网络调用
    c = LLMClient(
        model="qwen3.6-35b-a3b",
        api_key="dummy",
        base_url="http://example.invalid/api/v1",
    )
    llm = c._get_llm()
    assert llm is not None
    assert c._llm_text is llm  # 单例缓存（文本模型）


class _FakeLLMStream:
    """模拟 qwen_agent 在 use_raw_api 全流式下的 chat：yield List[Message]，
    每片都是「到当前为止的完整回复」。"""
    def __init__(self, chunks):
        self.chunks = chunks

    def chat(self, messages, stream=True):
        assert stream is True, "raw_api 要求 stream=True"
        for ch in self.chunks:
            yield ch


def test_chat_full_stream_takes_last_message_obj():
    c = LLMClient(model="qwen3.6-35b-a3b", api_key="dummy",
                  base_url="http://example.invalid/api/v1")
    c._llm_text = _FakeLLMStream([
        [_FakeMsg("你好")],
        [_FakeMsg("你好世界")],
        [_FakeMsg("你好世界！")],
    ])
    assert c._chat([{"role": "user", "content": "hi"}]) == "你好世界！"


def test_chat_full_stream_takes_last_dict_list():
    c = LLMClient(model="m", api_key="dummy",
                  base_url="http://example.invalid/api/v1")
    c._llm_text = _FakeLLMStream([
        [{"content": "部"}, {"content": "分"}],
        [{"content": "完整回复"}],
    ])
    assert c._chat([{"role": "user", "content": "hi"}]) == "完整回复"


def test_chat_empty_response_raises():
    c = LLMClient(model="m", api_key="dummy",
                  base_url="http://example.invalid/api/v1", max_retries=1)
    c._llm_text = _FakeLLMStream([[ _FakeMsg("") ]])
    try:
        c._chat([{"role": "user", "content": "hi"}])
        assert False, "空响应应抛 LLMClientError"
    except Exception as e:
        assert "均失败" in str(e)


def test_text_and_vision_use_separate_paths(monkeypatch):
    # 文本走 qwen_agent（_get_llm），视觉走 dashscope.MultiModalConversation。
    c = LLMClient(
        model="text-model", api_key="k", base_url="http://text.invalid/api/v1",
        vision_model="vl-model", vision_api_key="k2", vision_base_url="http://vl.invalid/api/v1",
    )

    calls = {"text": 0, "vision": 0}

    def fake_build(model, api_key, base_url):
        class _F:
            def chat(self, messages, stream=True):
                calls["text"] += 1
                yield [_FakeMsg("text-reply")]
        return _F()
    monkeypatch.setattr(c, "_build_llm", fake_build)
    # 跳过真实读图，直接返回占位 content，避免测试依赖真实图片文件
    monkeypatch.setattr(c, "_build_vision_content", lambda paths, prompt: [{"text": prompt}])

    import dashscope

    def fake_mm_call(api_key=None, model=None, messages=None, **kw):
        calls["vision"] += 1
        # 仿 MultiModalConversation 响应：output.choices[0].message.content=[{'text':...}]
        msg = type("Msg", (), {"content": [{"text": "vision-reply"}]})()
        choice = type("Choice", (), {"message": msg})()
        resp = type("R", (), {"output": type("O", (), {"choices": [choice]})()})()
        return resp
    monkeypatch.setattr(dashscope.MultiModalConversation, "call", fake_mm_call)

    assert c.chat("hi") == "text-reply"
    assert c.vision("x.png", "describe") == "vision-reply"
    # 文本与视觉各走各的路径，互不干扰
    assert calls == {"text": 1, "vision": 1}


def test_vision_uses_own_config_defaults(monkeypatch):
    # 未单独配置视觉 key / 网关 / 模型名时，复用 config 层默认值：
    # QWEN_VL_API_KEY 默认 = QWEN_API_KEY，QWEN_VL_BASE_URL 默认 = QWEN_BASE_URL。
    from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_VL_MODEL

    c = LLMClient(model="text-model", api_key="text-key", base_url="http://text.invalid")
    c._resolve_cfg()
    # 视觉默认复用文本 key / 网关，模型名取 config 实际默认值
    assert c.vision_api_key == QWEN_API_KEY
    assert c.vision_base_url == QWEN_BASE_URL
    assert c.vision_model == QWEN_VL_MODEL



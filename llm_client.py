"""
统一模型调用层

所有模型调用（对话 / 视觉 / 检索增强）都经此处，统一重试、超时、JSON 抽取与日志。
底层走 Qwen-Agent 的 model 对象（qwen_agent.llm.get_chat_model）；为降低模块导入耦合，
qwen_agent / config / dashscope 均在方法内惰性导入。

对外三方法：
  - chat(prompt, system=None)       普通对话（生成 / 判断）
  - vision(image_paths, prompt)     视觉：图片 + 文本，用于字段抽取 / OCR 兜底
  - rag(query, docs, system=None)   检索增强：先把检索到的 docs 拼进 prompt 再 chat（本地索引在 T04 接入）
"""
import json
import logging
import re
import time
from typing import List, Optional, Union

logger = logging.getLogger("llm_client")


class LLMClientError(Exception):
    """模型调用在重试后仍失败。"""


class LLMClient:
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        vision_model: Optional[str] = None,
        vision_api_key: Optional[str] = None,
        vision_base_url: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        # 文本模型配置（对话 / 匹配判断 / 检索增强）
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        # 多模态（视觉）模型配置（看图 / OCR 兜底）
        self.vision_model = vision_model
        self.vision_api_key = vision_api_key
        self.vision_base_url = vision_base_url
        self.max_retries = max_retries
        self.timeout = timeout
        self._llm_text = None

    # ---------- 惰性解析配置 / 获取 model ----------
    def _resolve_cfg(self):
        if self.model is None or self.api_key is None or self.base_url is None:
            # 惰性导入，避免导入副作用（config 在 import 时会 load_key）
            from config import QWEN_API_KEY, QWEN_MODEL, QWEN_BASE_URL
            self.model = self.model or QWEN_MODEL
            self.api_key = self.api_key or QWEN_API_KEY
            self.base_url = self.base_url or QWEN_BASE_URL
        if self.vision_model is None or self.vision_api_key is None or self.vision_base_url is None:
            # 未单独配置视觉模型时，复用文本模型的 key / 网关，仅模型名不同
            from config import (
                QWEN_VL_API_KEY,
                QWEN_VL_BASE_URL,
                QWEN_VL_MODEL,
            )
            self.vision_model = self.vision_model or QWEN_VL_MODEL
            self.vision_api_key = self.vision_api_key or QWEN_VL_API_KEY
            self.vision_base_url = self.vision_base_url or QWEN_VL_BASE_URL

    def _build_llm(self, model: str, api_key: str, base_url: str):
        import dashscope
        if base_url:
            # 私有 MaaS 网关：原 OCREngine 使用的端点，qwen_agent 底层也是 dashscope。
            # 注：dashscope.base_http_api_url 是全局变量；文本/视觉若用不同网关，
            # 以最后一次设置为准（绝大多数情况下两者同网关，无影响）。
            dashscope.base_http_api_url = base_url
        from qwen_agent.llm import get_chat_model
        return get_chat_model({"model": model, "api_key": api_key})

    def _get_llm(self, kind: str = "text"):
        # 文本 / 检索增强模型（视觉模型走 MultiModalConversation，不经此路径）
        if self._llm_text is None:
            self._resolve_cfg()
            self._llm_text = self._build_llm(
                self.model, self.api_key, self.base_url
            )
        return self._llm_text

    # ---------- 对外方法 ----------
    def chat(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._chat(messages, kind="text")

    def vision(
        self,
        image_paths: Union[str, List[str]],
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        """多模态视觉问答。

        注意：视觉模型走 dashscope.MultiModalConversation 接口（与 test1.py 一致），
        不走 qwen_agent 的 chat —— 私有 MaaS 网关的多模态模型只认 MultiModalConversation，
        经 qwen_agent raw chat 路径调用会报 url error。
        """
        if isinstance(image_paths, str):
            image_paths = [image_paths]
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {"role": "user", "content": self._build_vision_content(image_paths, prompt)}
        )
        return self._vision_call(messages)

    @staticmethod
    def _build_vision_content(image_paths, prompt) -> list:
        """把本地图片转 base64 data URI 拼进 content（与 test1.py 等价）。"""
        import base64
        import os

        _MIME = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "gif": "image/gif",
        }
        content = []
        for p in image_paths:
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            mime = _MIME.get(ext, "image/jpeg")
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"image": f"data:{mime};base64,{b64}"})
        content.append({"text": prompt})
        return content

    def _vision_call(self, messages) -> str:
        """经 dashscope.MultiModalConversation 调用视觉模型，含重试与解析。"""
        import dashscope
        from dashscope import MultiModalConversation

        self._resolve_cfg()
        if self.vision_base_url:
            # 私有 MaaS 网关（与文本同端点；MultiModalConversation 也读这个全局变量）
            dashscope.base_http_api_url = self.vision_base_url
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = MultiModalConversation.call(
                    api_key=self.vision_api_key,
                    model=self.vision_model,
                    messages=messages,
                )
                text = self._parse_multimodal(resp)
                if not text:
                    raise ValueError("视觉模型返回为空")
                logger.info(
                    "LLM 调用成功 | kind=vision | model=%s | 响应长度=%d | 响应预览=%s",
                    self.vision_model,
                    len(text),
                    text[:1500],
                )
                return text
            except Exception as e:
                last_err = e
                logger.warning(
                    "LLM 调用失败(第%d次): %s | kind=vision | model=%s | base_url=%s | 请求预览=%s",
                    attempt,
                    e,
                    self.vision_model,
                    self.vision_base_url,
                    str(messages)[:300],
                )
                time.sleep(min(2 ** attempt, 10))
        msg = f"LLM 调用 {self.max_retries} 次均失败: {last_err}"
        if "url error" in str(last_err).lower() or "invalidparameter" in str(last_err).lower():
            msg += (
                f"\n[排查] 请求 model={self.vision_model} 打到了 base_url={self.vision_base_url}。"
                f"该端点很可能没有托管此模型（MaaS 网关通常一个端点只部署一个模型），"
                f"或该模型不支持看图。请检查并修正 QWEN_VL_MODEL / QWEN_VL_BASE_URL 配置。"
            )
        raise LLMClientError(msg)

    @staticmethod
    def _parse_multimodal(resp) -> str:
        """解析 MultiModalConversation 响应（content 为 [{'text': ...}] 列表）。"""
        output = getattr(resp, "output", None)
        choices = getattr(output, "choices", None)
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(item["text"])
                elif hasattr(item, "text") and item.text:
                    parts.append(item.text)
            return "".join(parts).strip()
        return ""

    def rag(self, query: str, docs: str, system: Optional[str] = None) -> str:
        prompt = f"参考以下资料回答问题。\n\n资料：\n{docs}\n\n问题：{query}"
        return self.chat(prompt, system=system)

    # ---------- 底层调用 + 重试（文本 / 检索增强）----------
    def _chat(self, messages, kind: str = "text") -> str:
        last_err = None
        model_name = self.model
        logger.debug("LLM 请求 | kind=%s | model=%s | messages=%s", kind, model_name, messages)
        for attempt in range(1, self.max_retries + 1):
            try:
                llm = self._get_llm(kind)
                # 注意：raw API 网关（私有 MaaS / Qwen3 系列会自动开启 use_raw_api）
                # 只支持全流式，必须 stream=True；qwen_agent 默认也推荐 stream=True。
                # 全流式下每次 yield 的都是「到当前为止的完整回复」，故取最后一片即为最终完整内容。
                resp = llm.chat(messages, stream=True)
                text = ""
                for item in resp:
                    # item 为 List[Message]/List[dict]（流式逐片）或单个 Message/dict
                    if isinstance(item, list):
                        chunk = "".join(
                            t for t in (self._extract_text(m) for m in item) if t
                        )
                    else:
                        chunk = self._extract_text(item)
                    if chunk:
                        text = chunk
                text = text.strip()
                if not text:
                    raise ValueError("LLM 返回为空")
                # 真机回溯关键：记录模型实际返回，便于排查「为什么判不匹配 / 文案怎么来的」
                logger.info(
                    "LLM 调用成功 | kind=%s | model=%s | 响应长度=%d | 响应预览=%s",
                    kind,
                    model_name,
                    len(text),
                    text[:1500],
                )
                return text
            except Exception as e:  # 统一兜底：重试
                last_err = e
                url = self.vision_base_url if kind == "vision" else self.base_url
                logger.warning(
                    "LLM 调用失败(第%d次): %s | kind=%s | model=%s | base_url=%s | 请求预览=%s",
                    attempt,
                    e,
                    kind,
                    model_name,
                    url,
                    str(messages)[:300],
                )
                time.sleep(min(2 ** attempt, 10))
        msg = f"LLM 调用 {self.max_retries} 次均失败: {last_err}"
        if "url error" in str(last_err).lower() or "invalidparameter" in str(last_err).lower():
            url = self.vision_base_url if kind == "vision" else self.base_url
            msg += (
                f"\n[排查] 请求 model={model_name} 打到了 base_url={url}。"
                f"该端点很可能没有托管此模型（MaaS 网关通常一个端点只部署一个模型），"
                f"或该模型不支持看图。请检查并修正 QWEN_VL_MODEL / QWEN_VL_BASE_URL 配置。"
            )
        raise LLMClientError(msg)

    @staticmethod
    def _extract_text(msg) -> str:
        """qwen_agent 返回 Message 对象或 dict；content 可能是 str 或 list。"""
        if hasattr(msg, "content"):
            content = msg.content
        elif isinstance(msg, dict):
            content = msg.get("content")
        else:
            content = msg
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return ""

    # ---------- 统一 JSON 抽取（容错）----------
    @staticmethod
    def extract_json(text: str):
        if not text:
            raise ValueError("empty text")
        s = text.strip()
        # 去 ```json ... ``` 围栏
        if "```" in s:
            m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
            if m:
                s = m.group(1).strip()
        # 截取首个 { 到最后一个 }
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析 JSON: {e}\n原始文本前 500 字: {text[:500]}")

"""
本地知识库（T04）

把 资料库/ 下的简历 / FAQ / 项目资料等建成本地索引，提供基于 BM25 的检索。
设计取舍（已与方案对齐）：
  - 不依赖云端 embedding（私有 MaaS 网关对 embedding 的支持不确定，且离线沙箱无法验证）。
  - 「本地知识库」本就应是本地索引：用纯 Python BM25（字符 unigram + CJK bigram）
    即可对短、具体的查询（如「求职期望」）稳定召回相关片段。
  - 检索到的片段在匹配 / 回复时注入提示词，由 LLMClient（底层 Qwen-Agent）生成答案，
    即「经 Qwen-Agent 检索并增强」。
  - 若日后网关支持 embedding，可在 retrieve() 内换成向量召回，对外接口不变。

对外：
  KnowledgeBase(directory)        建索引
  kb.retrieve(query, top_k)       返回相关片段文本列表
  kb.context(query, top_k)        返回带 [资料片段 N] 标注的上下文字符串（喂给提示词）
  get_knowledge_base()            单例，默认加载项目根 资料库/
"""
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

# ---------- 可调参数 ----------
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".text"}
CHUNK_SIZE = 700          # 单片段字符数上限
CHUNK_OVERLAP = 120       # 相邻片段重叠，避免切断语义
K1 = 1.5
B = 0.75

_CJK = re.compile(r"[一-鿿]")
_ASCII = re.compile(r"[a-z0-9]+")
_WS = re.compile(r"\s+")


class KnowledgeBase:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.chunks: List[Dict] = []   # {"source", "text", "tokens"}
        self._idf: Dict[str, float] = {}
        self._avgdl = 0.0
        self._load_and_index()

    # ---------- 加载与建索引 ----------
    def _iter_files(self):
        if not self.directory.exists():
            return
        for p in sorted(self.directory.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES:
                yield p

    def _load_and_index(self):
        for p in self._iter_files():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for chunk in self._chunk(text):
                tokens = self._tokenize(chunk)
                if tokens:
                    self.chunks.append({"source": p.name, "text": chunk, "tokens": tokens})

        n = len(self.chunks)
        self._avgdl = (sum(len(c["tokens"]) for c in self.chunks) / n) if n else 0.0
        df: Dict[str, int] = {}
        for c in self.chunks:
            for t in set(c["tokens"]):
                df[t] = df.get(t, 0) + 1
        # BM25 的 IDF；加 1 平滑，避免未登录词为负
        self._idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1.0) for t, c in df.items()}

    def _chunk(self, text: str) -> List[str]:
        text = _WS.sub("\n", text).strip()
        if not text:
            return []
        paras = [x.strip() for x in re.split(r"\n{1,}", text) if x.strip()]
        out, buf = [], ""
        for para in paras:
            if buf and len(buf) + len(para) > CHUNK_SIZE:
                out.append(buf)
                tail = buf[-CHUNK_OVERLAP:] if CHUNK_OVERLAP < len(buf) else ""
                buf = tail
            buf = (buf + "\n" + para).strip() if buf else para
            if len(buf) >= CHUNK_SIZE:
                out.append(buf)
                buf = ""
        if buf:
            out.append(buf)
        return out or [text[:CHUNK_SIZE]]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        text = text.lower()
        tokens: List[str] = []
        tokens += _ASCII.findall(text)
        cjk = "".join(_CJK.findall(text))
        # 中文按「字」+「相邻二字」切，兼顾召回与精度
        for ch in cjk:
            tokens.append(ch)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i:i + 2])
        return tokens

    # ---------- 检索 ----------
    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        q_tokens = self._tokenize(query)
        if not q_tokens or not self.chunks:
            return []
        scored = [(self._score(q_tokens, c), c) for c in self.chunks]
        scored.sort(key=lambda x: -x[0])
        return [c["text"] for s, c in scored[:top_k] if s > 0]

    def _score(self, q_tokens, chunk) -> float:
        dl = len(chunk["tokens"])
        tf: Dict[str, int] = {}
        for t in chunk["tokens"]:
            tf[t] = tf.get(t, 0) + 1
        denom = (self._avgdl if self._avgdl else 1)
        score = 0.0
        for qt in q_tokens:
            idf = self._idf.get(qt)
            if idf is None:
                continue
            f = tf.get(qt, 0)
            if f == 0:
                continue
            score += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / denom))
        return score

    def context(self, query: str, top_k: int = 3, max_len: int = 900) -> str:
        """返回带标注的检索上下文，直接拼进提示词。无命中返回空串。"""
        snips = self.retrieve(query, top_k=top_k)
        if not snips:
            return ""
        parts = [f"[资料片段 {i}]\n{s[:max_len]}" for i, s in enumerate(snips, 1)]
        return "\n\n".join(parts)


@lru_cache(maxsize=1)
def get_knowledge_base(directory=None) -> KnowledgeBase:
    """单例：默认加载项目根目录下的 资料库/。"""
    if directory:
        return KnowledgeBase(Path(directory))
    return KnowledgeBase(Path(__file__).parent / "资料库")

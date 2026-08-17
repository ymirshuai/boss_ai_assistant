"""本地知识库测试（不依赖网络 / 设备）。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from knowledge_base import KnowledgeBase, get_knowledge_base  # noqa: E402


RESUME_MD = """# 罗帅
男 | 32 岁 | 深圳

## 求职意向
AI 应用开发工程师 / 大模型应用开发工程师 / Agent 开发工程师
期望薪资：18K以上 ｜ 期望城市：深圳

## 专业技能
熟练使用 OpenAI / Claude / 通义千问等主流大模型 API
RAG 架构：文档切分、向量检索、Embedding、Reranker 两级检索优化
"""

OTHER_MD = """# 项目运行逻辑与实现方案报告
本程序通过 Airtest 连接安卓设备，自动浏览 BOSS 直聘岗位并打招呼。
主循环：检测新消息 -> 回复；否则浏览岗位 -> 判断匹配 -> 打招呼。
"""


def _make_kb(tmp: Path) -> KnowledgeBase:
    (tmp / "resume.md").write_text(RESUME_MD, encoding="utf-8")
    (tmp / "report.md").write_text(OTHER_MD, encoding="utf-8")
    return KnowledgeBase(tmp)


def test_build_index_from_dir():
    with tempfile.TemporaryDirectory() as d:
        kb = _make_kb(Path(d))
        assert len(kb.chunks) >= 2  # 至少两个文件各有片段


def test_retrieve_recalls_salary_expectation():
    with tempfile.TemporaryDirectory() as d:
        kb = _make_kb(Path(d))
        snips = kb.retrieve("求职期望 薪资 城市", top_k=2)
        assert snips, "应召回至少一个片段"
        joined = "\n".join(snips)
        assert "18K以上" in joined
        assert "深圳" in joined


def test_retrieve_recalls_job_direction():
    with tempfile.TemporaryDirectory() as d:
        kb = _make_kb(Path(d))
        snips = kb.retrieve("岗位方向 AI应用开发 Agent", top_k=2)
        joined = "\n".join(snips)
        assert "Agent" in joined or "AI" in joined


def test_context_formatting():
    with tempfile.TemporaryDirectory() as d:
        kb = _make_kb(Path(d))
        ctx = kb.context("求职期望 薪资", top_k=2)
        assert "[资料片段 1]" in ctx
        # 含简历片段内容
        assert "18K以上" in ctx


def test_empty_directory_no_crash():
    with tempfile.TemporaryDirectory() as d:
        kb = KnowledgeBase(Path(d))
        assert kb.retrieve("任意查询") == []
        assert kb.context("任意查询") == ""


def test_real_knowledge_base_recalls_resume():
    """真实集成：项目 资料库/ 应能被检索到求职期望片段。"""
    kb = get_knowledge_base()
    snips = kb.retrieve("求职期望 期望薪资 期望城市", top_k=3)
    joined = "\n".join(snips)
    assert "18K以上" in joined, "真实 资料库/ 应召回简历中的期望薪资（以简历为准）"
    assert "深圳" in joined

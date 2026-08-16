"""T02 验证：OCREngine / RAGEngine 已统一走 LLMClient（mock），并正确解析 JSON。

注意：airtest_connector 在模块顶层 auto_setup 连真机，沙箱无设备会超时。
这里用假模块替换它，使纯逻辑单测可跑；真机环境不受影响。
"""
import sys
import types
from pathlib import Path
from unittest import mock

# ---- 沙箱无设备：用假 airtest_connector 替换（仅本测试进程）----
_fake_conn = types.ModuleType("airtest_connector")
_fake_conn.job_JD_screenshots = lambda sm: []
_fake_conn.SnapshotManager = object
sys.modules["airtest_connector"] = _fake_conn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr_engine import OCREngine
from RAG_engine import RAGEngine


def _fake_llm(return_text):
    m = mock.MagicMock()
    m.vision.return_value = return_text
    m.chat.return_value = return_text
    return m


def _fake_ocr(job_info):
    o = mock.MagicMock()
    o.extract_job_info.return_value = job_info
    return o


def test_ocr_extract_which_job_uses_local_ocr_primary():
    """主路径：本地 OCR 抽出 → 不调视觉模型。"""
    llm = _fake_llm("ignored")
    local_ocr = mock.MagicMock()
    local_ocr.extract_chat_header_info.return_value = {
        "company": "X公司", "hr_name": "张三", "hr_title": "HR",
    }
    eng = OCREngine(
        llm=llm, sm=mock.MagicMock(), logger=mock.MagicMock(), local_ocr=local_ocr
    )
    out = eng.extract_which_job("fake.png")
    assert out == {"company": "X公司", "hr_name": "张三"}
    local_ocr.extract_chat_header_info.assert_called_once_with("fake.png")
    llm.vision.assert_not_called()


def test_ocr_extract_which_job_falls_back_to_vision_when_ocr_empty():
    """兜底：本地 OCR 双未识别时，调视觉；解析失败也安全降级。"""
    llm = _fake_llm('{"company": "X公司", "hr_name": "张三"}')
    local_ocr = mock.MagicMock()
    local_ocr.extract_chat_header_info.return_value = {
        "company": "未识别到", "hr_name": "未识别到", "hr_title": "未识别到",
    }
    eng = OCREngine(
        llm=llm, sm=mock.MagicMock(), logger=mock.MagicMock(), local_ocr=local_ocr
    )
    out = eng.extract_which_job("fake.png")
    assert out == {"company": "X公司", "hr_name": "张三"}
    local_ocr.extract_chat_header_info.assert_called_once()
    llm.vision.assert_called_once()


def test_ocr_extract_which_job_local_ocr_exception_still_falls_back():
    """异常路径：本地 OCR 抛异常时回退到视觉；最终取视觉结果。"""
    llm = _fake_llm('{"company": "Y", "hr_name": "李四"}')
    local_ocr = mock.MagicMock()
    local_ocr.extract_chat_header_info.side_effect = RuntimeError("paddle 挂了")
    eng = OCREngine(
        llm=llm, sm=mock.MagicMock(), logger=mock.MagicMock(), local_ocr=local_ocr
    )
    out = eng.extract_which_job("fake.png")
    assert out == {"company": "Y", "hr_name": "李四"}
    llm.vision.assert_called_once()


def test_rag_extract_job_jd_ocr_then_llm_judges():
    # OCR 抽取出结构化字段 → LLM 仅做文本判断（不直接读图）
    llm = _fake_llm('{"is_match": true, "message": "你好"}')
    ocr = _fake_ocr({"job_title": "AI工程师", "company": "Y公司", "salary": "20-30K"})
    eng = RAGEngine(llm=llm, ocr=ocr, sm=mock.MagicMock(), logger=mock.MagicMock())
    out = eng.extract_job_JD()
    assert out["is_match"] is True
    assert out["message"] == "你好"
    # OCR 抽取的岗位信息被附回结果，供下游保存
    assert out["job_info"]["company"] == "Y公司"
    # 先 OCR 抽取，再 LLM 文本判断（不应调用 vision）
    ocr.extract_job_info.assert_called_once()
    llm.chat.assert_called_once()
    llm.vision.assert_not_called()


def test_rag_extract_job_jd_fallback_on_bad_json():
    llm = _fake_llm("模型跑偏了，没返回 JSON")
    ocr = _fake_ocr({"job_title": "X", "company": "未识别到"})
    eng = RAGEngine(llm=llm, ocr=ocr, sm=mock.MagicMock(), logger=mock.MagicMock())
    out = eng.extract_job_JD()
    assert out["is_match"] is False
    assert "job_info" in out


def test_rag_judge_new_job_ocr_then_llm():
    llm = _fake_llm('{"is_match": false, "reply_message": "不感兴趣"}')
    ocr = _fake_ocr({"job_title": "前端", "company": "Z", "salary": "10K"})
    eng = RAGEngine(llm=llm, ocr=ocr, sm=mock.MagicMock(), logger=mock.MagicMock())
    out = eng.judge_new_job(["a.png"])
    assert out["is_match"] is False
    assert out["reply_message"] == "不感兴趣"
    assert out["job_info"]["company"] == "Z"
    ocr.extract_job_info.assert_called_once_with(["a.png"])
    llm.chat.assert_called_once()

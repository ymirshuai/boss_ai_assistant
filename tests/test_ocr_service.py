"""OCRService 的多维度判定与回填测试（纯函数，不依赖 PaddleOCR / qwen_agent）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr_service import should_fallback, merge_fallback, _is_missing


def test_is_missing():
    assert _is_missing(None) and _is_missing("") and _is_missing("未识别到")
    assert not _is_missing("AI工程师")


def test_fallback_on_exception():
    assert should_fallback({}, 0.99, True, 200) is True


def test_fallback_on_key_missing():
    fields = {"job_title": "未识别到", "company": "未识别到", "salary": "未识别到"}
    assert should_fallback(fields, 0.95, False, 200) is True


def test_fallback_on_low_confidence():
    fields = {"job_title": "AI工程师", "company": "X", "salary": "20K"}
    assert should_fallback(fields, 0.40, False, 200) is True


def test_fallback_on_structure_anomaly():
    fields = {"job_title": "AI工程师", "company": "X", "salary": "20K"}
    assert should_fallback(fields, 0.95, False, 0) is True


def test_no_fallback_when_ok():
    fields = {"job_title": "AI工程师", "company": "X", "salary": "20K"}
    assert should_fallback(fields, 0.95, False, 200) is False


def test_merge_fills_missing():
    primary = {"job_title": "未识别到", "company": "X", "salary": "20K"}
    fb = {"job_title": "AI工程师", "company": "X", "salary": "20K"}
    assert merge_fallback(primary, fb)["job_title"] == "AI工程师"


def test_merge_keeps_primary_when_fallback_missing():
    # primary 用真实场景的完整 8 字段 schema；fallback 只补非空字段
    primary = {
        "job_title": "AI工程师", "company": "X", "salary": "未识别到",
        "hr_name": "未识别到", "hr_title": "未识别到",
        "job_JD": "未识别到", "job_requirements": "未识别到", "home_distance": "未识别到",
    }
    fb = {"job_title": "其它", "salary": "20K"}
    out = merge_fallback(primary, fb)
    assert out["job_title"] == "AI工程师"  # 主路径有值，不被兜底覆盖
    assert out["salary"] == "20K"          # 主路径空，被兜底补全

"""T07 验证：聊天窗口顶部 crop 抽取（_extract_chat_header_from_blocks）。

不需要 PaddleOCR；直接喂 OCR 文字块字典，验证三种布局：
  1) 正常：徽章 + 名字同行 + 公司·职位行
  2) 无徽章（兜底取顶部最大块）
  3) HR 名字带 honorific（女士/先生/老师）
"""
from local_ocr_engine import LocalOCREngine

# 虚拟画布尺寸（取自常见手机分辨率）
W, H = 1080.0, 300.0


def _b(text, x, y, w=120, h=50):
    return {
        "text": text,
        "score": 0.99,
        "x": x, "y": y,
        "cx": x + w / 2, "cy": y + h / 2,
        "w": w, "h": h,
    }


def test_normal_layout_with_badge():
    # 布局：
    #   y=40  HR名(左) + 在线 badge(右)
    #   y=140 公司 · 职位
    blocks = [
        _b("刘泽瀚", 40, 40, w=200, h=60),
        _b("在线", 720, 50, w=80, h=40),
        _b("微步信息 · 经理", 40, 140, w=600, h=50),
    ]
    out = LocalOCREngine._extract_chat_header_from_blocks(blocks, W, H)
    assert out == {"company": "微步信息", "hr_name": "刘泽瀚", "hr_title": "经理"}, out


def test_normal_layout_with_honorific():
    # 布局：HR 名字 = "高女士"（带 honorific）
    blocks = [
        _b("高女士", 40, 40, w=200, h=60),
        _b("在线", 720, 50, w=80, h=40),
        _b("科大讯飞 · 高级招聘HR", 40, 140, w=600, h=50),
    ]
    out = LocalOCREngine._extract_chat_header_from_blocks(blocks, W, H)
    assert out["company"] == "科大讯飞"
    assert out["hr_name"] == "高女士"
    assert "高级招聘HR" in out["hr_title"]


def test_no_badge_fallback_to_top_block():
    # 没有"在线/忙碌/离线"徽章，应回退取顶部最大块
    blocks = [
        _b("张三", 40, 40, w=240, h=60),  # 名字：top + largest
        _b("ACME公司 · CTO", 40, 140, w=400, h=50),
    ]
    out = LocalOCREngine._extract_chat_header_from_blocks(blocks, W, H)
    assert out["company"] == "ACME公司"
    assert out["hr_name"] == "张三"
    assert out["hr_title"] == "CTO"


def test_only_one_field_returned_by_ocr_still_triggers_fallback_path():
    # OCR 漏掉 HR 名字 + 公司（OCR 返回"未识别到"）
    # 这里直接模拟 OCR 极端情况：blocks 为空
    out = LocalOCREngine._extract_chat_header_from_blocks([], W, H)
    assert out == {"company": "未识别到", "hr_name": "未识别到", "hr_title": "未识别到"}, out


def test_irrelevant_blocks_are_ignored():
    # 混入徽章候选词（在顶部以下）+ 大段无关文本
    blocks = [
        _b("刘泽瀚", 40, 40, w=200, h=60),
        _b("在线", 720, 50, w=80, h=40),
        # 这行 y > 0.45H 不该被当作徽章
        _b("忙碌中", 100, 200, w=100, h=40),
        _b("微步信息 · 经理", 40, 140, w=600, h=50),
    ]
    out = LocalOCREngine._extract_chat_header_from_blocks(blocks, W, H)
    assert out["company"] == "微步信息"
    assert out["hr_name"] == "刘泽瀚"
    assert out["hr_title"] == "经理"
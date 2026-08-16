"""
OCR 服务：本地 OCR 主路径 + 大模型兜底

流程：
  1) LocalOCREngine(GPU) 先做字段抽取（快、不花云端额度）；
  2) 多维度校验（异常 / 关键字段缺失 / 平均置信度 < 阈值 / 结构异常）；
  3) 任一维度命中 → 切换 LLMClient.vision 大模型兜底，并把兜底结果回填，
     保证下游始终拿到结构化字段。
"""
import logging
from typing import Dict, List, Optional

from local_ocr_engine import LocalOCREngine
from llm_client import LLMClient
from prompts_loader import get_prompt

logger = logging.getLogger("ocr_service")

# 平均置信度阈值（低于即触发兜底）
CONFIDENCE_THRESHOLD = 0.6
# 判定「关键字段缺失」的字段
KEY_FIELDS = ("job_title", "company", "salary")


def _is_missing(v) -> bool:
    return v is None or v == "" or v == "未识别到"


def should_fallback(
    fields: Dict,
    avg_confidence: float,
    exception: bool,
    total_blocks: int,
) -> bool:
    """多维度判定：任一命中即走大模型兜底。"""
    if exception:
        return True
    if all(_is_missing(fields.get(k)) for k in KEY_FIELDS):
        return True
    if avg_confidence < CONFIDENCE_THRESHOLD:
        return True
    if total_blocks == 0:  # 多图解析结构异常：没有任何文字块
        return True
    return False


def merge_fallback(primary: Dict, fallback: Dict) -> Dict:
    """用兜底结果补全主路径里为空的字段；兜底没有的保持主路径值。"""
    out = dict(primary)
    for k, v in (fallback or {}).items():
        if k in out and _is_missing(out[k]) and not _is_missing(v):
            out[k] = v
    return out


class OCRService:
    def __init__(self, llm: Optional[LLMClient] = None, use_gpu: bool = True, logger_=None):
        self.llm = llm or LLMClient()
        self.engine = LocalOCREngine(use_gpu=use_gpu, logger=logger_)
        self._fallback_prompt = get_prompt("extract_job_info_fallback")

    # ---------- 置信度 / 结构统计（复用 OCR 缓存，不重复推理）----------
    def _confidence_and_blocks(self, image_paths: List[str]):
        blocks = []
        for p in image_paths:
            try:
                blocks.extend(self.engine.ocr_image(p))
            except Exception as e:  # 单张失败不应拖垮整体
                logger.warning("ocr_image 失败(%s): %s", p, e)
        if not blocks:
            return 0.0, 0
        avg = sum(b["score"] for b in blocks) / len(blocks)
        return avg, len(blocks)

    # ---------- 对外：抽取岗位字段（含兜底）----------
    def extract_job_info(self, image_paths: List[str]) -> Dict:
        exception = False
        try:
            fields = self.engine.extract_job_info_from_screenshots(image_paths)
        except Exception as e:
            logger.warning("本地 OCR 异常，准备切兜底: %s", e)
            exception = True
            fields = self.engine._empty()

        avg_conf, total = self._confidence_and_blocks(image_paths)

        if should_fallback(fields, avg_conf, exception, total):
            logger.info(
                "OCR 兜底触发：avg_conf=%.3f total=%d exception=%s",
                avg_conf,
                total,
                exception,
            )
            try:
                raw = self.llm.vision(image_paths, self._fallback_prompt)
                fb = LLMClient.extract_json(raw)
                if isinstance(fb, dict):
                    fields = merge_fallback(fields, fb)
            except Exception as e:
                logger.error("OCR 兜底失败，沿用本地结果: %s", e)

        return fields

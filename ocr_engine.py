"""
OCR 引擎模块

字段抽取统一走 LLMClient（底层 Qwen-Agent / 千问 VL）。
聊天窗口顶部抽取走本地 GPU OCR（LocalOCREngine），OCR 双未识别时兜底 LLM 视觉。
公共方法签名保持不变，自动模式零回归。
"""
import json
import os
from typing import Optional

from airtest_connector import job_JD_screenshots, SnapshotManager
from job_reader import parse_ai_reply
from llm_client import LLMClient
from local_ocr_engine import LocalOCREngine
from prompts_loader import get_prompt
from logger import Logger
from airtest.core.api import *


class OCREngine:
    """OCR 引擎类（字段抽取：详情页走 LLMClient，聊天顶部走本地 GPU OCR）"""

    def __init__(
        self,
        logger=None,
        sm=None,
        llm: Optional[LLMClient] = None,
        local_ocr: Optional[LocalOCREngine] = None,
    ):
        # logger / sm 由 BOSSAssistant 在最开始创建并注入；未传入时退化创建
        self.logger = logger if logger is not None else Logger()
        self.sm = sm if sm is not None else SnapshotManager()
        self.llm = llm or LLMClient()
        # 本地 OCR 默认 GPU 推理；环境变量 LOCAL_OCR_USE_GPU=0 可强制 CPU。
        use_gpu = os.environ.get("LOCAL_OCR_USE_GPU", "1") == "1"
        self.local_ocr = local_ocr or LocalOCREngine(use_gpu=use_gpu, logger=self.logger)

    def _call_vl(self, image_path, prompt):
        """单图视觉抽取。"""
        return self.llm.vision(image_path, prompt)

    def extract_job_info(self):
        """提取岗位卡片信息（列表，前两个岗位）。"""
        image_path = self.sm.snapshot()
        prompt = get_prompt("extract_job_info")
        result = self._call_vl(image_path, prompt)
        result = parse_ai_reply(result)
        if len(result) == 2:
            return result
        return result

    def extract_which_job(self, image_path):
        """提取聊天窗口上方的公司名称和 hr 姓名。

        主路径：本地 GPU OCR（extract_chat_header_info）。
        兜底：本地 OCR 两个关键字段都为"未识别到"时，回退到 LLM 视觉
              （prompts.yaml: extract_which_job）。
        返回结构与原版一致：{company, hr_name}，调用方无需改动。
        """
        info = {"company": "未识别到", "hr_name": "未识别到"}
        try:
            info = self.local_ocr.extract_chat_header_info(image_path)
        except Exception as e:
            self.logger.log(f"[extract_which_job] 本地 OCR 失败: {e}", "WARNING")

        company = info.get("company", "未识别到")
        hr_name = info.get("hr_name", "未识别到")

        if company == "未识别到" and hr_name == "未识别到":
            # 兜底：交给大模型视觉
            try:
                prompt = get_prompt("extract_which_job")
                result = self._call_vl(image_path, prompt)
                json_start = result.find("{")
                json_end = result.rfind("}") + 1
                if json_start != -1 and json_end != -1:
                    result = result[json_start:json_end]
                parsed = json.loads(result)
                company = parsed.get("company", "未识别到")
                hr_name = parsed.get("hr_name", "未识别到")
            except Exception as e:
                self.logger.log(f"[extract_which_job] 视觉兜底失败: {e}", "WARNING")

        return {"company": company, "hr_name": hr_name}
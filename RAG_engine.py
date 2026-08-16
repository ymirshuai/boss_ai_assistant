"""
RAG 引擎模块

匹配判断 / 回复生成统一走 LLMClient（底层 Qwen-Agent）。
原「app_id RAG 应用」（云端应用）已废弃不可用，由 T04 的本地 RAG 检索取代。
"""
import json
from typing import Optional

from airtest_connector import job_JD_screenshots, SnapshotManager
from llm_client import LLMClient
from ocr_service import OCRService
from prompts_loader import get_prompt
from knowledge_base import get_knowledge_base
from logger import Logger


class RAGEngine:
    """RAG 引擎类（匹配判断 / 回复生成，经统一 LLMClient）

    岗位 JD 判断流程（OCR 优先 + LLM 判断）：
      1) OCRService 从岗位详情截图本地抽取结构化字段（LocalOCREngine + 大模型兜底）；
      2) 把抽取结果 + 求职期望 交给 LLMClient.chat 做匹配判断。
    这样 LLM 只负责「判断/生成」，不再直接读图，省额度也更稳。
    """

    def __init__(self, logger=None, sm=None, llm: Optional[LLMClient] = None, ocr: Optional[OCRService] = None):
        self.sm = sm if sm is not None else SnapshotManager()
        self.logger = logger if logger is not None else Logger()
        self.llm = llm or LLMClient()
        # OCR 提取主路径；默认 OCRService（LocalOCREngine + 兜底），可注入便于测试
        self.ocr = ocr or OCRService(llm=self.llm, logger_=self.logger)

    def _ask_vision(self, screenshot_path, prompt):
        """多图视觉问答（聊天回复等仍需读图时使用），走多模态模型。

        视觉模型未配置/不可用时降级返回空字符串，避免整条链路因兜底失败而崩溃
        （主路径是本地 OCR，vision 仅作增强）。
        """
        try:
            return self.llm.vision(screenshot_path, prompt)
        except Exception as e:
            self.logger.log(f"[_ask_vision] 视觉调用失败，降级返回空: {e}", "WARNING")
            return ""

    # ------------------------------------------------------------------ #
    # 公共：OCR 抽取 + LLM 判断
    # ------------------------------------------------------------------ #
    def _ocr_and_judge(self, image_paths, prompt_name: str) -> dict:
        """OCR 优先抽取岗位信息，再交给 LLM 判断；返回解析后的 dict（含 job_info）。"""
        knowledge = get_knowledge_base().context(
            "求职期望 薪资范围 期望城市 通勤 岗位方向 匹配条件", top_k=2
        )
        # 1) 本地 OCR 抽取结构化字段（含大模型兜底）
        job_info = self.ocr.extract_job_info(image_paths)
        job_info_text = json.dumps(job_info, ensure_ascii=False, indent=2)
        self.logger.log(
            f"[{prompt_name}] OCR 抽取岗位字段:\n{job_info_text[:2000]}", "INFO"
        )
        # 2) 把抽取结果交给 LLM 做匹配判断（纯文本，不读图）
        prompt = get_prompt(
            prompt_name,
            job_info_text=job_info_text,
            knowledge=knowledge,
        )
        resp = self.llm.chat(prompt)
        self.logger.log(f"[{prompt_name}] LLM 原始响应:\n{resp[:2000]}", "INFO")
        try:
            parsed = LLMClient.extract_json(resp)
        except Exception:
            self.logger.log_error(f"{prompt_name} 解析失败", resp, "")
            parsed = {"is_match": False, "message": "未能识别岗位信息", "reply_message": "未能识别岗位信息"}
        # 附上 OCR 实际抽取的岗位信息，供下游保存 / 匹配
        parsed["job_info"] = job_info
        return parsed

    def extract_job_JD(self):
        """浏览循环中判断岗位是否符合求职期望，返回 {is_match, message, job_info}。"""
        image_paths = job_JD_screenshots(self.sm)
        return self._ocr_and_judge(image_paths, "extract_job_jd")

    def judge_new_job(self, image_paths):
        """消息流中判断 HR 新招呼的岗位（check_new_job），返回 {is_match, reply_message, job_info}。"""
        return self._ocr_and_judge(image_paths, "check_new_job")

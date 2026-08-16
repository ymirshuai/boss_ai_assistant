"""
消息回复模块
负责回复消息、发送简历/微信
"""
import json

from airtest_connector import job_JD_screenshots
from callMaster import call_master
from data_store import get_job_by_company_hr, get_chat_history, save_chat_record, save_job_info
from prompts_loader import get_prompt
from knowledge_base import get_knowledge_base
from airtest.core.api import *


class MessageReplier:
    """消息回复类"""

    def __init__(self, device=None, logger=None, sm=None, ocr=None, rag=None):
        # 实例由 BOSSAssistant 在最开始创建并注入，避免重复 new
        self.device = device
        self.logger = logger
        self.sm = sm
        self.ocr = ocr
        self.rag = rag
        self.last_reply_time = {}  # {boss_name: timestamp}
    
    def reply(self):
        """回复消息
        
        Args:

        
        Returns:
            str: "success" | "skip" | "error"
        """

        # 2. 识别消息

        #判断聊天岗位在库中是否存在，有没有历史记录
        # 局部截图提取公司名称和hr姓名
        time.sleep(1.5)
        screenshot_path = self.sm.snapshot()
        screen = self.sm.crop_and_save(screenshot_path, (247, 101, 923, 232))

        company_hr = self.ocr.extract_which_job(screen)
        job_data = get_job_by_company_hr(company_hr['company'],company_hr['hr_name'])

        if job_data is not None:
            self.logger.log("有聊天记录，开始回复消息", "INFO")
            #获取聊天记录，提取当前聊天信息
            job_id = job_data['id']
            chat_history = get_chat_history(job_id)
            #将聊天截图和聊天记录发给AI判断意图
            reply_text = self._generate_reply_text(chat_history,job_data,screenshot_path)
            #发送消息
            touch((500, 2276))
            time.sleep(2)
            text(reply_text)
            self.logger.update_stats("reply_count", 1)
            # 保存聊天记录
            save_chat_record(job_id, reply_text, "me")
            time.sleep(1)
            touch(Template(r"png/tpl1783331945136.png", record_pos=(0.425, 0.106), resolution=(1080, 2400)))#发送
            time.sleep(0.5)
            touch(Template(r"png/tpl1783592232267.png", record_pos=(-0.419, -0.974), resolution=(1080, 2400)))  # 返回
            time.sleep(1)
            return "success"
        #如果库里没有，表示为hr主动打招呼，点击进入岗位信息，判断是否符合求职要求，回复拒绝或发简历
        else:
            self.logger.log("新招呼，判断岗位", "INFO")
            #点击进入岗位信息
            time.sleep(1)
            touch((388,555))
            image_paths = job_JD_screenshots(self.sm)
            self._check_new_job(image_paths)
            return "success"
    
    def _generate_reply_text(self, chat_history,job_info,screenshot_path):
        """生成回复文案
        
        Args:
            message: 对方消息
        
        Returns:
            str: 回复文案
        """
        
        # T04：注入个人资料 / 项目经历，让回复能体现真实能力
        knowledge = get_knowledge_base().context(
            "个人技能 项目经历 自我介绍 姓名 联系方式", top_k=2
        )
        prompt = get_prompt("generate_reply", chat_history=chat_history, job_info=job_info, knowledge=knowledge)

        resp = self.rag._ask_vision(screenshot_path, prompt)

        try:
            # 提取 JSON 部分（防止返回内容包含其他文字）
            json_start = resp.find("{")
            json_end = resp.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                resp = resp[json_start:json_end]
            resp = json.loads(resp)
            # 提取AI返回结果
        except:
            # 解析失败，返回原始文本
            self.logger.log_error("generate_reply返回解析错误", resp, screenshot_path)
            return {"raw": resp}
        # 保存hr消息
        job_id = job_info['id']
        for message in resp["hr_message"]:
            save_chat_record(job_id, message, "hr")
        #如果要简历
        if resp["need_resume"]:
            #touch(Template(r"png\tpl1783479599949.png", record_pos=(0.125, -0.818), resolution=(1080, 2400)))#发简历
            time.sleep(0.5)
            qr = exists(Template(r"png\tpl1783479611176.png", record_pos=(0.205, 0.341), resolution=(1080, 2400)))#确定
            if qr:
                touch(qr)
            self.logger.update_stats("resume_sent",1)
        #要微信
        if resp["need_wechat"]:
            touch(Template(r"png\tpl1783480117837.png", record_pos=(-0.125, -0.815), resolution=(1080, 2400)))#换微信
            time.sleep(0.5)
            touch(Template(r"png\tpl1783479611176.png", record_pos=(0.19, 0.314), resolution=(1080, 2400)))#确定
            self.logger.update_stats("wechat_sent", 1)
        #约面试
        if resp["is_interview_invited"]:
            content = f""+job_info["company"]+"公司"+job_info["hr_name"]+"想约面试"
            call_master("约面试",content)
            self.logger.update_stats("wechat_sent", 1)
        return resp["reply_message"]

    def _check_new_job(self, image_paths):
        """判断聊天界面中的新岗位，并发消息

                Args:
                    image_paths: 岗位截图

                Returns:
                    str: 回复文案
                """
        # OCR 优先抽取岗位字段 → 交给 LLM 判断是否符合求职期望（取代原直接读图）
        result = self.rag.judge_new_job(image_paths)
        job_info = result.get("job_info", {})
        time.sleep(0.5)
        keyevent("BACK")  # 返回
        time.sleep(1)
        #符合期望，保存岗位，发简历，发消息
        if result["is_match"]:
            touch(Template(r"png/tpl1783479599949.png", record_pos=(0.125, -0.818), resolution=(1080, 2400)))#发简历
            time.sleep(0.5)
            touch(Template(r"png/tpl1783479611176.png", record_pos=(0.205, 0.341), resolution=(1080, 2400)))#确定
            self.logger.update_stats("resume_sent", 1)
            #保存信息
            job_id = save_job_info(result["job_info"])
            touch((500, 2276))
            time.sleep(2)
            message = result["reply_message"]
            text(message)
            self.logger.update_stats("greet_count", 1)
            # 保存聊天记录
            save_chat_record(job_id, message, "me")
            touch(Template(r"png/tpl1783331945136.png", record_pos=(0.425, 0.106), resolution=(1080, 2400)))  # 发送
            time.sleep(0.5)
            touch(Template(r"png/tpl1783592232267.png", record_pos=(-0.419, -0.974), resolution=(1080, 2400)))#返回
            time.sleep(1)
        #不符合期望，保存岗位，发消息
        else:
            job_id = save_job_info(result["job_info"])
            touch((500, 2276))
            time.sleep(2)
            message = result["reply_message"]
            text(message)
            self.logger.update_stats("skip_count", 1)
            # 保存聊天记录
            save_chat_record(job_id, message, "me")
            touch(Template(r"png/tpl1783331945136.png", record_pos=(0.425, 0.106), resolution=(1080, 2400)))  # 发送
            time.sleep(0.5)
            touch(Template(r"png/tpl1783592232267.png", record_pos=(-0.419, -0.974), resolution=(1080, 2400)))#返回
            time.sleep(1)



    def _send_resume(self):
        """发送简历"""
        # TODO: 实现发送简历的逻辑
        # 方法 1：点击"发送简历"按钮
        # self.device.tap_by_name("send_resume_button")
        
        # 方法 2：发送简历文件
        # self.device.push(FILE_PATHS["resume"], "/sdcard/resume.pdf")
        # self.device.tap_by_name("resume_file")
        pass
    
    def _send_wechat(self):
        """发送微信"""
        # TODO: 实现发送微信的逻辑
        # 方法 1：发送微信二维码图片
        # self.device.push(FILE_PATHS["wechat_qr"], "/sdcard/wechat_qr.png")
        # self.device.tap_by_name("send_wechat_button")
        
        # 方法 2：直接发送微信号文字
        # self.device.input_text("我的微信：xxxxx")
        pass

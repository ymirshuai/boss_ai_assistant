"""
岗位浏览模块
负责浏览岗位、判断匹配度、自动打招呼
"""

import time

from config import BEHAVIOR_CONFIG
from data_store import save_job_info, save_chat_record
from airtest.core.api import *

class JobBrowser:
    """岗位浏览类"""

    def __init__(self, device, logger, ocr, rag):
        # 实例由 BOSSAssistant 在最开始创建并注入，避免重复 new
        self.device = device
        self.logger = logger
        self.ocr = ocr
        self.rag = rag
        self.last_greet_time = 0
        self.greet_count_this_hour = 0
        self.hour_start = time.time()
        # 拉黑公司集合：browse 时命中则跳过打招呼（由 ctx 在浏览前 set 进来）
        self.blocklist = set()

    def set_blocklist(self, items):
        """设置拉黑公司集合（公司名精确匹配）。"""
        self.blocklist = set(items or [])

    def browse(self, greet=True):
        """浏览岗位

        Args:
            greet: True 时匹配岗位自动打招呼；False 时只浏览/保存岗位信息不招呼
                   （agent 工具「是否打招呼」开关 = False 的路径）。
        Returns:
            dict: {"browsed": 浏览岗位数, "greeted": 发送打招呼次数}
        """

        # 计数
        greeted = 0
        # 2. 识别岗位信息
        # 自带截图
        job_infos = self.ocr.extract_job_info()
        # 4. 点击进入详情页
        self.device.tap_by_name("first_job_card")
        time.sleep(2)
        # 循环3次
        for i in range(0,len(job_infos)):

            # 5. 截图读取 JD
            # 自带截图
            result = self.rag.extract_job_JD()



            job_info_all = job_infos[i] | result["job_info"]
            # 保存岗位信息
            job_id = save_job_info(job_info_all)
            self.logger.update_stats("browse_count")

            # 判断是否求职符合要求，不符合返回False，符合返回打招呼文字
            #不符合，跳过，下一个
            if not result["is_match"]:
                self.logger.update_stats("skip_count")
                self.logger.log("跳过当前岗位（不匹配）", "WARNING")
                #左滑下一个
                swipe((930, 1238), (216, 1238))
                time.sleep(2)
                continue

            # 命中拉黑公司：跳过打招呼（agent blocklist 生效点）
            company = job_info_all.get("company", "")
            if company and company in self.blocklist:
                self.logger.update_stats("skip_count")
                self.logger.log(f"跳过拉黑公司岗位：{company}", "WARNING")
                swipe((930, 1238), (216, 1238))
                time.sleep(2)
                continue

            # 只浏览不招呼：左滑看下一个
            if not greet:
                swipe((930, 1238), (216, 1238))
                time.sleep(2)
                continue

            #符合，发送打招呼
            # 7. 检查冷却时间和频率限制
            # 检查打招呼间隔
            now = time.time()
            if now - self.last_greet_time < BEHAVIOR_CONFIG["greet_interval"]:
                wait_time = BEHAVIOR_CONFIG["greet_interval"] - (now - self.last_greet_time)
                time.sleep(wait_time)
            #发送打招呼
            touch(Template(r"png/tpl1783331562916.png", record_pos=(0.008, 0.975), resolution=(1080, 2400)))#立刻沟通
            time.sleep(2)
            touch((500, 2276))
            time.sleep(2)
            message = result["message"]
            text(message)
            time.sleep(1)
            self.logger.update_stats("greet_count", 1)
            #保存聊天记录
            save_chat_record(job_id,message,"me")
            touch(Template(r"png/tpl1783331945136.png", record_pos=(0.425, 0.106), resolution=(1080, 2400)))#发送
            time.sleep(0.5)
            touch(Template(r"png/tpl1783592232267.png", record_pos=(-0.419, -0.974), resolution=(1080, 2400)))#返回
            time.sleep(2)
            # 9. 更新状态
            self.last_greet_time = time.time()
            greeted += 1
            # 左滑下一个
            if i ==0:
                swipe((930, 1238), (216, 1238))
        keyevent("BACK")  # 返回
        time.sleep(1)
        return {"browsed": len(job_infos), "greeted": greeted}

    def search(self, keyword=""):
        """发起岗位搜索（设备 UI 动作）。

        keyword 为空则仅进入搜索页（浏览首页推荐）；否则输入关键词并发起搜索。
        供 Agent 的 search_jobs 工具调用。
        """
        from config import search_job

        kw = keyword or search_job or ""
        touch(Template(r"png/tpl1783585382020.png", record_pos=(-0.377, 1.006), resolution=(1080, 2400)))
        time.sleep(1)
        if not kw:
            return "ok（浏览首页推荐）"
        touch(Template(r"png/tpl1783583458648.png", threshold=0.9, record_pos=(0.42, -0.964),
                       resolution=(1080, 2400)))
        time.sleep(2)
        text(kw)
        touch(Template(r"png/tpl1783583514445.png", record_pos=(0.371, -0.873),
                       resolution=(1080, 2400)))
        time.sleep(4)
        return f"ok（搜索：{kw}）"


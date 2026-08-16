"""
主程序入口
负责主循环调度和异常处理
"""

import sys
import time

from airtest_connector import SnapshotManager, handle_common_exception
from callMaster import call_master
from RAG_engine import RAGEngine
from data_store import get_today_greet_count
from ocr_engine import OCREngine
from config import DEVICE_CONFIG, BEHAVIOR_CONFIG, search_job, FILE_PATHS
from device import DeviceManager
from job_browser import JobBrowser
from message_replier import MessageReplier
import traceback
from logger import Logger, setup_logging
from airtest.core.api import *
from airtest.aircv import crop_image, imread

# Airtest 设备初始化改为懒加载：首次进入 campaign 时才执行 auto_setup，
# 这样模块可在无设备的环境（Web UI / 测试）中被安全 import，不会在 import 时连接手机。
_AIRTEST_SETUP_DONE = False


def _ensure_airtest_setup():
    global _AIRTEST_SETUP_DONE
    if _AIRTEST_SETUP_DONE:
        return
    auto_setup(__file__, devices=["android://127.0.0.1:5037/VKV8RGGANNQWAI7T"])
    _AIRTEST_SETUP_DONE = True

class BOSSAssistant:
    """BOSS 直聘 AI 助手主类"""
    
    def __init__(self):
        # 最开始创建共享实例：后续所有模块都复用同一份，不再各自 new
        self.logger = Logger()
        self.device = DeviceManager()
        self.sm = SnapshotManager()
        self.ocr = OCREngine(logger=self.logger, sm=self.sm)
        self.rag = RAGEngine(logger=self.logger, sm=self.sm)

        # 业务模块：把共享实例注入进去
        self.job_browser = JobBrowser(
            device=self.device,
            logger=self.logger,
            ocr=self.ocr,
            rag=self.rag,
        )
        self.message_replier = MessageReplier(
            device=self.device,
            logger=self.logger,
            sm=self.sm,
            ocr=self.ocr,
            rag=self.rag,
        )

        self.running = False
        self.hour_start = time.time()
        self.greet_count_this_hour = 0

        # campaign 运行时状态（供 Web UI / 未来 Agent 读取）
        self.campaign_keyword = search_job
        self.campaign_target = BEHAVIOR_CONFIG["greet_per_day"]
        self.campaign_deadline = None
        self.campaign_status = "空闲"
        self.latest_screenshot_path = None
    
    def start(self):
        """启动（自动模式）：初始化日志后进入 campaign 主循环。"""
        setup_logging(self.logger.session_id)
        self.logger.log("BOSS 直聘 AI 助手启动", "INFO")
        self.logger.log(f"设备：{DEVICE_CONFIG['device_id']}", "INFO")
        self.logger.log(f"ADB 路径：{self.device.adb_path}", "INFO")
        # 自动模式沿用 config 默认参数
        self.run_campaign()

    def run_campaign(self, keyword=None, target_greet_count=None, duration=None):
        """可独立调用的 campaign 主循环。

        被自动模式、Web UI「开始自动打招呼」按钮、以及未来的 Agent 工具复用。
        在后台线程中调用时，可用 stop() 发送停止信号。

        Args:
            keyword: 搜索岗位关键词；为空用 config.search_job。
            target_greet_count: 目标打招呼数（达到即暂停本轮）；为空用 BEHAVIOR_CONFIG["greet_per_day"]。
            duration: 最长运行秒数；为空则一直运行直到手动停止或达每日上限。
        """
        _ensure_airtest_setup()
        setup_logging(self.logger.session_id)
        self.running = True
        self.error_time = 0
        self.campaign_keyword = keyword or search_job
        self.campaign_target = target_greet_count or BEHAVIOR_CONFIG["greet_per_day"]
        self.campaign_deadline = (time.time() + float(duration)) if duration else None
        self.search_job = self.campaign_keyword
        self.campaign_status = f"运行中（岗位：{self.campaign_keyword}｜目标：{self.campaign_target}）"
        self.logger.log(
            f"开始 campaign | 岗位={self.campaign_keyword} | 目标打招呼={self.campaign_target}"
            + (f" | 时长={int(duration)}s" if duration else ""),
            "INFO",
        )


        while self.running:
            # 时长上限：到点主动停止
            if self.campaign_deadline and time.time() > self.campaign_deadline:
                self.logger.log("已到设定运行时长，停止 campaign", "INFO")
                self.running = False
                break
            try:
                # 1. 检查设备连接
                if not self.device.is_device_online():
                    self.logger.log("设备断开，尝试重连...", "WARNING")
                    try:
                        self.device.reconnect()
                    except Exception as e:
                        self._handle_exception("设备断开", str(e))
                        continue

                # 捕获最新截图供 Web UI 展示（设备未连接时静默跳过）
                self._capture_latest_screenshot()

                # 3. 检测新消息
                #直接识别 搭配直接点击
                #has_new = exists(Template(r"png/tpl1783658515582.png", threshold=0.9,record_pos=(0.133, 0.973), resolution=(1080, 2400)))

                #局部截图识别，搭配还原坐标点击
                screen = G.DEVICE.snapshot()
                # 局部截图
                new_screen = crop_image(screen, (624, 2219, 785, 2348))
                template =Template(r"png/tpl1783658515582.png", threshold=0.9)
                has_new = template.match_in(new_screen)
                time.sleep(1)
                if has_new:
                    self.logger.log("有新消息,点击进入...", "INFO")
                    #touch(has_new)#直接点击

                    touch((has_new[0] + 624, has_new[1] + 2219))  # 还原坐标
                    time.sleep(1)
                    # 下拉到顶
                    for i in range(0, 5):
                        din = exists(
                            Template(r"png/tpl1783675112668.png", record_pos=(-0.149, -0.843), resolution=(1080, 2400)))
                        if din:
                            break
                        swipe((600, 550), (600, 2066), duration=2.0)
                    #检测当前界面的红点
                    while True:
                        ccc=0
                        for i in range(0,2):#下滑3次查找新消息

                            screen = G.DEVICE.snapshot()
                            # 局部截图
                            local_screen = crop_image(screen, (45, 506, 288, 2134))
                            # 将我们的目标截图设置为一个Template对象
                            tempalte = Template(r"png/tpl1783340414618.png", threshold=0.85)
                            # 在局部截图里面查找指定的图片对象
                            pos = tempalte.match_in(local_screen)
                            time.sleep(1)
                            #msg_point = exists(Template(r"png/tpl1783340414618.png", threshold=0.9,record_pos=(-0.329, -0.039), resolution=(1080, 2400)))#半截红点
                            if pos:
                                time.sleep(1)
                                touch((pos[0]+45+500,pos[1]+506+98))#偏移坐标
                                # 4. 回复消息
                                self.logger.log("检测到新消息，开始回复...", "INFO")
                                result = self.message_replier.reply()

                                if result == "success":
                                    self.logger.log("回复成功", "SUCCESS")
                            #没有新消息退出循环
                            else:
                                #上划
                                self.logger.log("未找到新消息,上划...", "INFO")
                                swipe((600, 2066), (600, 550), duration=2.0)
                                ccc+=1
                        if ccc==1:
                            self.logger.log("未找到新消息,结束消息回复。。。", "INFO")
                            break
                else:
                    #没有新消息就浏览岗位
                    self.logger.log("没有新消息...", "INFO")
                    #搜索岗位，为空时浏览主页岗位
                    self.search_job_or_not(self.campaign_keyword)
                    count = 0
                    while True:
                        #达到当日最大打招呼，返回检查新消息
                        today_greets = get_today_greet_count()
                        self.logger.log("今天已打招呼："+str(today_greets), "INFO")
                        # 达到目标数或每日硬上限，返回检查新消息
                        if today_greets >= self.campaign_target or today_greets >= BEHAVIOR_CONFIG["greet_per_day"]:
                            time.sleep(600)#直接等10分钟吧
                            break
                        now = time.time()
                        # 检查每小时打招呼限制
                        if now - self.hour_start > 3600:
                            self.greet_count_this_hour = 0
                            self.hour_start = now
                        # 大于跳出，检测新消息
                        if self.greet_count_this_hour >= BEHAVIOR_CONFIG["max_greet_per_hour"]:
                            self.logger.log("超出一小时打招呼数，返回检查新消息...", "INFO")
                            time.sleep(600)#直接等10分钟吧
                            break
                        # 5. 浏览岗位,浏览两个岗位

                        self.logger.log("开始浏览岗位...", "INFO")
                        #先上划，不看前两个
                        swipe((600, 2066), (600, 550), duration=2.0)
                        count_one = self.job_browser.browse()
                        count +=count_one
                        self.greet_count_this_hour = count_one + self.greet_count_this_hour
                        time.sleep(1)
                        #打招呼后跳出，检查新消息
                        if count>0:
                            break

                    # 10. 返回主页
                    handle_common_exception()
                # 6. 打印统计
                self.logger.print_stats()
                
                # 7. 等待一段时间
                self.logger.log(f"等待 {BEHAVIOR_CONFIG['loop_interval']} 秒...", "INFO")
                time.sleep(BEHAVIOR_CONFIG["loop_interval"])
        
            except KeyboardInterrupt:
                self.logger.log("用户中断，退出...", "WARNING")
                self.logger.print_stats()
                self.logger.save_stats()
                sys.exit(0)

            except Exception as e:
                self.error_time+=1
                # 获取异常栈帧对象列表
                tb = traceback.extract_tb(e.__traceback__)
                # 取最后一帧（真正报错的那一行）
                last_frame = tb[-1]
                file_name = last_frame.filename  # 报错文件路径
                line_no = last_frame.lineno  # 报错行号
                func_name = last_frame.name  # 函数名
                code_line = last_frame.line  # 出错代码文本
                print(f"报错文件：{file_name}")
                print(f"报错行号：{line_no}")
                #print(f"出错代码：{code_line}")
                print(f"错误信息：{str(e)}")
                self.logger.log(
                    f"异常位置：{file_name} | 行号：{line_no} | 函数：{func_name}", "ERROR"
                )
                self.logger.log_error("主循环异常", traceback.format_exc())
                if self.error_time>=3:
                    self._handle_exception("主循环异常3次", str(e))
                    break
                # 10. 返回主页
                handle_common_exception()

    def search_job_or_not(self,job=None):
        touch(Template(r"png/tpl1783585382020.png", record_pos=(-0.377, 1.006), resolution=(1080, 2400)))
        time.sleep(1)
        if job is None or job == "":

            return
        else:

            count = 0
            # 进入搜索
            touch(Template(r"png/tpl1783583458648.png", threshold=0.9, record_pos=(0.42, -0.964),
                           resolution=(1080, 2400)))
            time.sleep(2)
            text(job)
            touch(Template(r"png/tpl1783583514445.png", record_pos=(0.371, -0.873),
                           resolution=(1080, 2400)))
            time.sleep(4)
    def _handle_exception(self, error_type, error_msg, screenshot_path=None):
        """处理异常
        
        Args:
            error_type: 错误类型
            error_msg: 错误信息
            screenshot_path: 截图路径
        """
        self.logger.log_error(error_type, error_msg, screenshot_path)
        self.logger.log(f"异常：{error_type}", "ERROR")
        self.logger.log(f"详情：{error_msg}", "ERROR")
        self.logger.log("处理：呼叫人工处理", "WARNING")

        call_master("主循环异常3次",error_msg)
    
    def stop(self):
        """停止主循环"""
        self.running = False
        self.campaign_status = "已停止"
        self.logger.log("停止主循环", "INFO")
        self.logger.print_stats()
        self.logger.save_stats()

    def _capture_latest_screenshot(self):
        """把当前屏幕保存到 screenshots/latest.png，供 Web UI 实时展示。

        设备未连接 / 截图失败时不阻塞主流程。
        """
        try:
            screen = G.DEVICE.snapshot()
            if screen is None:
                return
            import cv2
            cv2.imwrite(FILE_PATHS["latest_screenshot"], screen)
            self.latest_screenshot_path = FILE_PATHS["latest_screenshot"]
        except Exception:
            pass

    def status(self) -> dict:
        """返回当前运行状态，供 Web UI 轮询。"""
        try:
            today = get_today_greet_count()
        except Exception:
            today = 0
        return {
            "running": self.running,
            "keyword": getattr(self, "campaign_keyword", search_job),
            "target": getattr(self, "campaign_target", BEHAVIOR_CONFIG["greet_per_day"]),
            "today_greet_count": today,
            "latest_screenshot": self.latest_screenshot_path,
            "status": getattr(self, "campaign_status", "空闲"),
            "session_id": self.logger.session_id[:8],
        }


def main():
    """主函数"""
    # 模式分派：auto=写死循环；agent=Qwen-Agent 工具调度；ui=本地 Web 交互界面
    from config import MODE
    if MODE == "agent":
        from agent_mode import run_agent_mode
        run_agent_mode()
        return
    if MODE == "ui":
        from web_ui import run_ui
        run_ui()
        return

    # 启动助手（自动模式）
    assistant = BOSSAssistant()

    try:
        assistant.start()
    except KeyboardInterrupt:
        assistant.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()

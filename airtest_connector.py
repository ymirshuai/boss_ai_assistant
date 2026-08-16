from airtest.core.api import *
from airtest.aircv import crop_image, imread
import os
import cv2
from datetime import datetime
# 在auto_setup接口传入devices参数
auto_setup(__file__,devices=["android://127.0.0.1:5037/VKV8RGGANNQWAI7T"])

"""
截图文件管理工具

目录结构: screenshots / 本次运行时间(一级目录) / snap截图时间.png(文件名)

用法:
    from snapshot_manager import SnapshotManager

    # 一次运行 = 一个 manager 实例(内部记录 run_time 作为一级目录)
    sm = SnapshotManager()                 # 默认 screenshots/20260708_205150/
    name1 = sm.snapshot()                  # 截图并保存进 run_dir,返回完整路径
    name2 = sm.snapshot(prefix="login")    # 自定义前缀
    name3 = sm.crop_and_save(src, rect)    # 裁剪并保存进 run_dir,返回完整路径

依赖: pip install airtest opencv-python numpy
"""



def save_cv2_img(img, path):
    """把 cv2(numpy) 图像写到本地,兼容中文/非 ASCII 路径。

    cv2.imwrite 在 Windows 上对含中文的路径会静默失败,
    改用 cv2.imencode + 普通 open 写入即可规避。
    """
    ext = os.path.splitext(path)[1].lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError("图像编码失败,无法保存: %s" % path)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf.tobytes())


class SnapshotManager:
    """一次运行对应一个实例: 自动建 /screenshots/<本次运行时间>/ 目录,
    每次 snapshot() 把图片存进去,文件名按 snap 截图时间自动命名。"""

    def __init__(self, base_dir="screenshots", run_time=None, device=None):
        """
        base_dir : 根目录,默认 "screenshots"
        run_time : 本次运行时间(一级目录名);默认取当前时间
        device   : Airtest 设备对象(可选,不传则用全局 snapshot)
        """
        self.base_dir = base_dir
        # 本次运行时间 -> 一级目录名,例如 20260708_205150
        self.run_time = run_time or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.device = device
        # 一级目录: screenshots/本次运行时间/
        self.run_dir = os.path.join(base_dir, self.run_time)
        os.makedirs(self.run_dir, exist_ok=True)

    def snapshot(self, prefix="snap", ext=".png"):
        """截图并保存到 当前运行目录(run_dir),返回完整路径。

        文件名规则: <prefix>_<snap截图时间(含毫秒)>.<ext>
        例如: snap_20260708_205150_123.png
        """
        # snap 截图时间(带毫秒,避免同秒冲突)
        snap_time = datetime.now().strftime("%Y%m%d_%H%M%S_") + \
                    "%03d" % (datetime.now().microsecond // 1000)
        filename = "%s_%s%s" % (prefix, snap_time, ext)
        filepath = os.path.join(self.run_dir, filename)
        from airtest.core.api import snapshot as air_snapshot
        air_snapshot(filename=filepath)
        return filepath

    def crop_and_save(self, src_img, rect, prefix="crop", ext=".png"):
        """裁剪图片并自动保存到 当前运行目录(run_dir),返回完整路径。

        与 snapshot() 保持一致: 同目录(run_dir)、同命名规则
        (前缀_截图时间(含毫秒).后缀)。

        参数:
            src_img : cv2 图像(numpy ndarray),或图片文件路径字符串
            rect    : [x_min, y_min, x_max, y_max]
            prefix  : 文件名前缀,默认 "crop"
            ext     : 文件后缀,默认 ".png"(无损)

        返回:
            str : 自动生成的完整路径,例如
                  screenshots/20260708_205150/crop_20260708_205150_123.png
        """
        # 允许直接传图片路径
        if isinstance(src_img, str):
            img = imread(src_img)          # aircv.imread 支持中文路径
        else:
            img = src_img

        cropped = crop_image(img, rect)    # 返回 numpy 图像数组

        # 命名规则与 snapshot() 一致: 前缀_截图时间(含毫秒).后缀
        snap_time = datetime.now().strftime("%Y%m%d_%H%M%S_") + \
                    "%03d" % (datetime.now().microsecond // 1000)
        filename = "%s_%s%s" % (prefix, snap_time, ext)
        save_path = os.path.join(self.run_dir, filename)
        save_cv2_img(cropped, save_path)

        return save_path

    def full_path(self, filename):
        """给定文件名,返回该截图在本运行目录下的完整路径。"""
        return os.path.join(self.run_dir, filename)

    def list_snaps(self):
        """列出本次运行已保存的所有截图文件名。"""
        if not os.path.isdir(self.run_dir):
            return []
        return sorted(f for f in os.listdir(self.run_dir)
                      if f.lower().endswith((".png", ".jpg", ".jpeg")))


def job_JD_screenshots(sm=None):
    """
        对岗位信息进行截图保存，返回图片地址。
        参考screenshots/test

            返回:
                detail_screenshots : 多张截图的list
    """
    detail_screenshots = [] #截图列表
    sm = sm or SnapshotManager()
    sleep(2)
    snapshot_name = sm.snapshot()
    detail_screenshots.append(snapshot_name)
    #居然有4张截不完的岗位
    for i in range(1,6):
        #上划
        swipe((450, 2122), (450, 300), duration = 1)
        #点击查看更多
        cheakmore = exists(Template(r"png/tpl1783231943147.png", threshold=0.9,record_pos=(-0.077, -0.317), resolution=(1080, 2400)))
        if cheakmore:
            touch(cheakmore)
        #滑动后截图
        snapshot_name = sm.snapshot()
        detail_screenshots.append(snapshot_name)
        #查看是否到底
        cheakend = exists(Template(r"png/tpl1783594975852.png", record_pos=(-0.299, 0.372), resolution=(1080, 2400)))
        if cheakend:
            return detail_screenshots
    return detail_screenshots

def handle_common_exception():
    #多次返回，最终回到主页
    for i in range(0,8):
        keyevent("BACK")
        ziwei = exists(Template(r"png/tpl1783585382020.png", record_pos=(-0.377, 1.006), resolution=(1080, 2400)))
        if ziwei:
            touch(ziwei)
        souye = exists(Template(r"png/tpl1783590820209.png", record_pos=(0.373, -0.965), resolution=(1080, 2400)))
        if souye:
            break
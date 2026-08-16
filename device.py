"""
设备管理模块
负责 ADB 连接、截图、点击、输入等操作
"""

import os
import subprocess
import time
from pathlib import Path
from config import DEVICE_CONFIG, COORDINATES


def resolve_adb_path() -> str:
    """解析 adb 可执行文件路径（避免在 PATH 缺失时报 [WinError 2]）。

    优先级：airtest 自带 adb（随包内置，最可靠）→ ANDROID_HOME/platform-tools → PATH 上的 adb。
    若都拿不到，退化回 "adb"（交给 subprocess 报错，错误信息更明确）。
    """
    # 1. airtest 内置 adb（项目已依赖 airtest，且自带 windows/adb.exe）
    try:
        from airtest.core.android.adb import ADB

        return ADB.get_adb_path()
    except Exception:
        pass
    # 2. ANDROID_HOME / ANDROID_SDK_ROOT
    for env_key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk = os.environ.get(env_key)
        if sdk:
            name = "adb.exe" if os.name == "nt" else "adb"
            cand = os.path.join(sdk, "platform-tools", name)
            if os.path.exists(cand):
                return cand
    # 3. 退化到 PATH
    return "adb"


class DeviceManager:
    """设备管理类"""
    
    def __init__(self):
        self.device_id = DEVICE_CONFIG["device_id"]
        self.screenshot_dir = DEVICE_CONFIG["screenshot_dir"]
        self.local_dir = DEVICE_CONFIG["local_screenshot_dir"]
        self.adb_path = resolve_adb_path()
        
    def shell(self, cmd):
        """执行 ADB shell 命令"""
        result = subprocess.run(
            [self.adb_path, "-s", self.device_id, "shell", cmd],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip()
    
    def pull(self, remote_path, local_path):
        """从设备拉取文件"""
        result = subprocess.run(
            [self.adb_path, "-s", self.device_id, "pull", remote_path, local_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    
    def push(self, local_path, remote_path):
        """推送文件到设备"""
        result = subprocess.run(
            [self.adb_path, "-s", self.device_id, "push", local_path, remote_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    
    def screencap(self, filename="screenshot.png"):
        """截图并保存到本地
        
        Args:
            filename: 文件名（保存在 local_dir 下）
        
        Returns:
            str: 本地文件路径
        """
        local_path = str(Path(self.local_dir) / filename)
        remote_path = f"{self.screenshot_dir}/{filename}"
        
        # 设备端截图
        self.shell(f"screencap -p {remote_path}")
        
        # 拉取到本地
        if self.pull(remote_path, local_path):
            return local_path
        else:
            raise Exception(f"截图失败：无法拉取文件 {remote_path}")
    
    def tap(self, x, y):
        """点击坐标
        
        Args:
            x: X 坐标
            y: Y 坐标
        """
        self.shell(f"input tap {x} {y}")
        time.sleep(0.5)  # 等待点击生效
    
    def tap_by_name(self, coord_name):
        """按名称点击预设坐标
        
        Args:
            coord_name: 坐标名称（在 config.COORDINATES 中定义）
        """
        if coord_name not in COORDINATES:
            raise ValueError(f"未知的坐标名称：{coord_name}")
        
        x, y = COORDINATES[coord_name]
        self.tap(x, y)
    
    def input_text(self, text):
        """输入文字
        
        Args:
            text: 要输入的文字
        
        Note:
            ADB 的 input text 不支持中文，需要用其他方法
            推荐用 Airtest 的 text() 方法
        """
        # 方法 1：用 Airtest（推荐）
        try:
            from airtest.core.api import text as airtest_text
            airtest_text(text)
            return
        except ImportError:
            pass
        
        # 方法 2：用剪贴板（备用）
        import pyperclip
        pyperclip.copy(text)
        self.shell("input keyevent 279")  # KEYCODE_PASTE
        time.sleep(0.5)
    
    def swipe(self, start_x, start_y, end_x, end_y, duration=500):
        """滑动屏幕
        
        Args:
            start_x: 起始 X
            start_y: 起始 Y
            end_x: 结束 X
            end_y: 结束 Y
            duration: 滑动时长（毫秒）
        """
        self.shell(f"input swipe {start_x} {start_y} {end_x} {end_y} {duration}")
        time.sleep(0.5)
    
    def keyevent(self, keycode):
        """发送按键事件
        
        Args:
            keycode: 按键代码（如 4=返回，66=回车）
        """
        self.shell(f"input keyevent {keycode}")
        time.sleep(0.3)
    
    def launch_app(self, package="com.hpbr.bosszhipin"):
        """启动 APP
        
        Args:
            package: 包名
        """
        self.shell(f"am start -n {package}/.module.launcher.WelcomeActivity")
        time.sleep(3)
    
    def is_device_online(self):
        """检查设备是否在线
        
        Returns:
            bool: 是否在线
        """
        result = subprocess.run(
            [self.adb_path, "devices"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return self.device_id in result.stdout
    
    def reconnect(self):
        """重连设备"""
        subprocess.run([self.adb_path, "kill-server"], timeout=10)
        time.sleep(2)
        subprocess.run([self.adb_path, "start-server"], timeout=10)
        time.sleep(2)
        
        if self.is_device_online():
            return True
        else:
            raise Exception("设备重连失败")

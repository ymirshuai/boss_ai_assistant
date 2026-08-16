"""
配置文件模板（请勿直接提交真实 config.py）

使用方式：
  1. 复制本文件为 config.py：  cp config.example.py config.py
  2. 填入你自己的值（device_id / 坐标 / 私有 MaaS 网关等）
  3. API Key 放 Key.json（见 Key.json.example），或由 load_key() 交互式输入

⚠️ config.py 已在 .gitignore 中，不会进入版本库；本模板不含任何私人数据。
"""
from pathlib import Path
import os

# 加载 Key.json 中的 DASHSCOPE_API_KEY（缺失时会交互式要求输入）
from load_key import load_key
load_key()

# ========== 项目根目录 ==========
PROJECT_ROOT = Path(__file__).parent

# ========== API 配置 ==========
QWEN_API_KEY = os.environ["DASHSCOPE_API_KEY"]
QWEN_MODEL = "qwen-max"
# 私有 MaaS 网关：替换为你在阿里云百炼控制台看到的部署端点（MaaS 专用 key 走此端点）
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "https://<你的私有MaaS网关>/api/v1")

# 多模态（视觉）模型：图片 OCR 兜底 / 读图问答
QWEN_VL_MODEL = os.environ.get("QWEN_VL_MODEL", "qwen3.8-max")
QWEN_VL_API_KEY = os.environ.get("QWEN_VL_API_KEY", QWEN_API_KEY)
QWEN_VL_BASE_URL = os.environ.get("QWEN_VL_BASE_URL", QWEN_BASE_URL)

# ========== 运行模式 ==========
# auto: 原写死 Airtest 循环   agent: Qwen-Agent 工具调用模式
MODE = os.environ.get("BOSS_MODE", "agent")

# ========== 设备配置 ==========
DEVICE_CONFIG = {
    "device_id": "YOUR_DEVICE_ID",                       # 你的设备序列号（adb devices 查看）
    "screenshot_dir": "/sdcard/boss_screenshots",
    "local_screenshot_dir": str(PROJECT_ROOT / "screenshots"),
}

# ========== 个人资料 ==========
search_job = "AI应用开发"

# ========== 坐标配置（需用 AirtestIDE 针对你的设备分辨率重新获取） ==========
COORDINATES = {
    "first_chat_item": (200, 400),
    "message_tab": (500, 2200),
    "input_box": (500, 2200),
    "send_button": (950, 2200),
    "back_button": (97, 150),
    "first_job_card": (712, 693),
    "job_detail_back": (97, 150),
    "send_resume_button": (800, 1800),
    "send_wechat_button": (800, 1900),
    "resume_file": (500, 1500),
}

# ========== 行为配置 ==========
BEHAVIOR_CONFIG = {
    "greet_per_day": 60,
    "cooldown_seconds": 300,
    "greet_interval": 10,
    "match_threshold": 70,
    "max_greet_per_hour": 30,
    "loop_interval": 5,
    "screenshot_quality": 80,
}

# ========== 文件路径 ==========
FILE_PATHS = {
    "resume": str(PROJECT_ROOT / "assets" / "resume.pdf"),
    "wechat_qr": str(PROJECT_ROOT / "assets" / "wechat_qr.png"),
    "error_log": str(PROJECT_ROOT / "logs" / "error.log"),
    "stats_log": str(PROJECT_ROOT / "logs" / "stats.log"),
    "latest_screenshot": str(PROJECT_ROOT / "screenshots" / "latest.png"),
}

for path in FILE_PATHS.values():
    os.makedirs(os.path.dirname(path), exist_ok=True)

"""
重启 BOSS 直聘 APP
强行停止 → 等待 → 重新启动
"""

import subprocess
import time
import sys

from device import resolve_adb_path

# ========== 配置 ==========
DEVICE_ID = "VKV8RGGANNQWAI7T"
PACKAGE = "com.hpbr.bosszhipin"
ACTIVITY = ".module.launcher.WelcomeActivity"
WAIT_SECONDS = 2  # 停止后等待秒数

ADB_PATH = resolve_adb_path()


def adb(cmd: str) -> subprocess.CompletedProcess:
    """执行 ADB 命令"""
    return subprocess.run(
        [ADB_PATH, "-s", DEVICE_ID, "shell", cmd],
        capture_output=True,
        text=True,
        timeout=15,
    )


def check_device() -> bool:
    """检查设备是否在线"""
    result = subprocess.run(
        [ADB_PATH, "devices"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    for line in result.stdout.splitlines():
        if DEVICE_ID in line and "device" in line:
            return True
    return False


def force_stop():
    """强制停止 BOSS 直聘"""
    print(f"[1/3] 正在停止 {PACKAGE} ...")
    result = adb(f"am force-stop {PACKAGE}")
    if result.returncode != 0:
        print(f"⚠ 停止失败: {result.stderr}")
        # 停止失败不一定是致命错误，继续尝试启动
    else:
        print("✓ 已停止")
    time.sleep(WAIT_SECONDS)


def launch():
    """启动 BOSS 直聘"""
    print(f"[2/3] 正在启动 {PACKAGE} ...")
    result = adb(f"am start -n {PACKAGE}/{ACTIVITY}")
    if result.returncode != 0:
        print(f"✗ 启动失败: {result.stderr}")
        return False
    # 检查 output 中是否有成功标志
    if "Error" in result.stdout:
        print(f"✗ 启动失败: {result.stdout}")
        return False
    print("✓ 已启动")
    return True


def verify():
    """验证 APP 是否正在运行"""
    print("[3/3] 验证运行状态 ...")
    result = adb("pidof " + PACKAGE)
    # 如果返回退出码 0 且有输出，说明进程在运行
    if result.stdout.strip():
        pid = result.stdout.strip()
        print(f"✓ 运行中 (PID: {pid})")
        return True
    # pidof 没找到进程会返回非零退出码，但也可能 stdout 为空
    print(f"⚠ 未检测到进程（可能刚启动，稍等即可）")
    return False


def main():
    print("=" * 40)
    print("  重启 BOSS 直聘")
    print(f"  设备: {DEVICE_ID}")
    print(f"  包名: {PACKAGE}")
    print("=" * 40)
    print()

    # 检查设备
    if not check_device():
        print(f"✗ 设备 {DEVICE_ID} 未连接")
        print("请确认 USB 已连接并开启了 USB 调试")
        sys.exit(1)
    print(f"✓ 设备已连接\n")

    # 执行重启
    force_stop()
    success = launch()
    verify()

    print()
    if success:
        print("=" * 40)
        print("  重启完成 ✓")
        print("=" * 40)
    else:
        print("=" * 40)
        print("  重启失败 ✗")
        print("=" * 40)
        sys.exit(1)


if __name__ == "__main__":
    main()

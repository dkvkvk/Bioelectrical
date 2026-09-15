#!/bin/bash
# 烧录脚本：把编译好的固件写入 ESP32-S3 开发板
#
# 用法：
#   ./flash.sh              # 自动找串口
#   ./flash.sh /dev/ttyACM0 # 手动指定
set -e
cd /home/litmus/PHCodes/bioelectrical

export ZEPHYR_BASE=/home/litmus/PHCodes/Env/zephyrproject/zephyr
export ZEPHYR_SDK_INSTALL_DIR=/home/litmus/PHCodes/Env/zephyr-sdk-1.0.1
export PATH=/home/litmus/PHCodes/Env/zephyrproject/.venv/bin:/home/litmus/PHCodes/Env/zephyr-sdk-1.0.1/bin:/home/litmus/PHCodes/Env/zephyrproject/zephyr/scripts:/home/litmus/.local/bin:/usr/bin:/bin

WEST=/home/litmus/PHCodes/Env/zephyrproject/.venv/bin/west

# --- 1. 确定串口 ---
PORT="$1"
if [ -z "$PORT" ]; then
    PORT=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1)
fi
if [ -z "$PORT" ]; then
    echo "❌ 没找到串口设备（/dev/ttyACM* 或 /dev/ttyUSB*）"
    echo ""
    echo "请依次确认："
    echo "  1) 板子 USB 线已插好"
    echo "  2) 已在 Windows 上把板子转发进 WSL："
    echo "     usbipd attach --wsl --busid <设备号>"
    echo "  3) 驱动已加载：  sudo modprobe cdc_acm"
    exit 1
fi
echo "使用串口: $PORT"

# --- 2. 修复串口权限（WSL 无 udev，设备默认 root:root 600）---
if [ ! -r "$PORT" ] || [ ! -w "$PORT" ]; then
    echo "修复串口权限..."
    sudo -n chmod 666 "$PORT" 2>/dev/null || sudo chmod 666 "$PORT"
fi

# --- 3. 烧录 ---
exec "$WEST" flash --esp-device "$PORT"

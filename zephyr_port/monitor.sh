#!/bin/bash
# 查看板子串口日志
#
# 用法：
#   ./monitor.sh              # 自动找串口
#   ./monitor.sh /dev/ttyACM0 # 手动指定
# 退出：按 Ctrl+C
set -e

PORT="$1"
if [ -z "$PORT" ]; then
    PORT=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1)
fi
if [ -z "$PORT" ]; then
    echo "❌ 没找到串口设备（/dev/ttyACM* 或 /dev/ttyUSB*）"
    echo "   请确认板子已转发进 WSL：usbipd attach --wsl --busid <设备号>"
    exit 1
fi

# 修复权限（WSL 无 udev）
if [ ! -r "$PORT" ] || [ ! -w "$PORT" ]; then
    sudo -n chmod 666 "$PORT" 2>/dev/null || sudo chmod 666 "$PORT"
fi

stty -F "$PORT" raw 115200 2>/dev/null || true

echo "=== 串口日志 ($PORT) —— 按 Ctrl+C 退出 ==="
exec cat "$PORT"

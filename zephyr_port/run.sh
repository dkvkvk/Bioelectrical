#!/bin/bash
# ============================================================================
#  一键三连 —— 编译 → 烧录 → 看日志
#
#  用法：
#     ./run.sh            编译 + 烧录 + 看日志（增量编译，日常使用）
#     ./run.sh -f         同上，但全量编译（改动较大时用，慢一些但干净）
#     ./run.sh -q         只编译 + 烧录，不进入日志
#     ./run.sh -l         只看日志（不编译不烧录）
#
#  说明：脚本会自动完成串口准备（从 Windows 转发进 WSL、加载驱动、修权限），
#        所以插拔板子后直接运行即可，无需手工操作。
# ============================================================================

set -e
cd /home/litmus/PHCodes/bioelectrical

# ---------------------------------------------------------------- 环境
export ZEPHYR_BASE=/home/litmus/PHCodes/Env/zephyrproject/zephyr
export ZEPHYR_SDK_INSTALL_DIR=/home/litmus/PHCodes/Env/zephyr-sdk-1.0.1
export PATH=/home/litmus/PHCodes/Env/zephyrproject/.venv/bin:/home/litmus/PHCodes/Env/zephyr-sdk-1.0.1/bin:/home/litmus/PHCodes/Env/zephyrproject/zephyr/scripts:/home/litmus/.local/bin:/usr/bin:/bin

WEST=/home/litmus/PHCodes/Env/zephyrproject/.venv/bin/west
PYTHON=/home/litmus/PHCodes/Env/zephyrproject/.venv/bin/python3
USBIPD="/mnt/c/Program Files/usbipd-win/usbipd.exe"
BOARD=my_esp32s3/esp32s3/procpu

# ---------------------------------------------------------------- 参数
FULL=0
DO_BUILD=1
DO_FLASH=1
DO_LOG=1

case "${1:-}" in
    ""|--all) ;;
    -f|--full) FULL=1 ;;
    -q|--quiet) DO_LOG=0 ;;
    -l|--log) DO_BUILD=0; DO_FLASH=0 ;;
    -h|--help)
        sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
        exit 0 ;;
    *) echo "未知参数：$1（用 -h 查看帮助）"; exit 1 ;;
esac

# ---------------------------------------------------------------- 工具函数
find_port() {
    ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1
}

# 确保串口可用：必要时自动从 Windows 转发进 WSL
ensure_serial() {
    local port
    port=$(find_port)
    if [ -n "$port" ]; then
        SERIAL_PORT="$port"
        return 0
    fi

    echo "  · 串口未接入，正在自动转发..."
    if [ ! -x "$USBIPD" ]; then
        echo "  ✗ 找不到 usbipd（$USBIPD）"
        echo "    请先安装：winget install usbipd"
        return 1
    fi

    # 先确保内核驱动在（设备枚举时需要）
    if ! lsmod | grep -q cdc_acm; then
        sudo -n modprobe cdc_acm 2>/dev/null || true
    fi

    # 找 ESP32 板子（乐鑫厂商号 303a）
    local busid
    busid=$("$USBIPD" list 2>/dev/null | grep -i "303a:" | awk '{print $1}' | head -1)
    if [ -z "$busid" ]; then
        echo "  ✗ 没找到 ESP32 板子"
        echo "    请检查 USB 线是否插好（插板子上标着 USB 的那个口）"
        return 1
    fi

    echo "  · 找到板子（busid=$busid），转发中..."
    "$USBIPD" attach --wsl --busid "$busid" >/dev/null 2>&1 || true

    # 等设备枚举出来
    local i
    for i in $(seq 1 20); do
        sleep 0.5
        port=$(find_port)
        if [ -n "$port" ]; then
            if ! lsmod | grep -q cdc_acm; then
                sudo -n modprobe cdc_acm 2>/dev/null || true
                sleep 0.5
            fi
            SERIAL_PORT="$port"
            echo "  ✓ 串口就绪：$port"
            return 0
        fi
    done

    echo "  ✗ 转发后仍未出现串口设备"
    echo "    可尝试：拔插 USB 线后重跑本脚本"
    return 1
}

fix_port_perm() {
    if [ ! -r "$SERIAL_PORT" ] || [ ! -w "$SERIAL_PORT" ]; then
        sudo -n chmod 666 "$SERIAL_PORT" 2>/dev/null || sudo chmod 666 "$SERIAL_PORT"
    fi
}

# ---------------------------------------------------------------- 主流程
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║   ESP32-S3 生物电采集固件 —— 一键三连                   ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

if [ "$DO_BUILD" = "1" ]; then
    echo "▶ [1/3] 编译"
    if [ "$FULL" = "1" ]; then
        echo "     模式：全量编译（-p always）"
        "$WEST" build -b "$BOARD" . -p always 2>&1 | \
            grep -E "error|Error|FAILED|FLASH:|Successfully created|^\[[0-9]+/[0-9]+\] Linking" || true
    else
        echo "     模式：增量编译"
        "$WEST" build -b "$BOARD" . 2>&1 | \
            grep -E "error|Error|FAILED|FLASH:|Successfully created|^\[[0-9]+/[0-9]+\] Linking" || true
    fi

    if [ ! -f build/zephyr/zephyr.bin ]; then
        echo "  ✗ 编译失败，未生成固件"
        exit 1
    fi
    echo "  ✓ 编译完成：build/zephyr/zephyr.bin"
    echo ""
fi

if [ "$DO_FLASH" = "1" ]; then
    echo "▶ [2/3] 烧录"
    if ! ensure_serial; then
        echo "  ✗ 串口不可用，跳过烧录"
        exit 1
    fi
    fix_port_perm

    FLASH_OUT=$("$WEST" flash --esp-device "$SERIAL_PORT" 2>&1) || true
    echo "$FLASH_OUT" | grep -E "Wrote [0-9]+ bytes|Hash of data verified" || true
    if echo "$FLASH_OUT" | grep -q "Hash of data verified"; then
        echo "  ✓ 烧录完成，校验通过，板子已复位重启"
    else
        echo "  ✗ 烧录失败，最后几行输出："
        echo "$FLASH_OUT" | tail -8
        exit 1
    fi
    echo ""
fi

if [ "$DO_LOG" = "1" ]; then
    echo "▶ [3/3] 查看日志"
    if ! ensure_serial; then
        exit 1
    fi
    fix_port_perm

    echo "  ── 开机日志 ──"
    "$PYTHON" boot_log.py "$SERIAL_PORT" 8 2>/dev/null || true
    echo ""
    echo "  ── 实时日志（按 Ctrl+C 退出）──"
    stty -F "$SERIAL_PORT" raw 115200 2>/dev/null || true
    trap 'echo ""; echo "已退出日志查看。"; exit 0' INT
    cat "$SERIAL_PORT"
fi

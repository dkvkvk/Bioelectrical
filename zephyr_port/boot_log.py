#!/usr/bin/env python3
"""
复位 ESP32-S3 并抓取启动日志。

原理：在保持串口打开的状态下，通过 USB-Serial-JTAG 的控制线（DTR/RTS）
触发一次正常复位，然后连续读取输出，这样不会丢失启动日志。

用法：
    python3 boot_log.py [串口] [抓取秒数]
    python3 boot_log.py /dev/ttyACM0 10
"""
import sys
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

s = serial.Serial(port, 115200, timeout=0.2)

# 正常运行模式复位：IO0 保持高电平（不进入下载模式）
s.dtr = False   # IO0 = HIGH
s.rts = True    # EN  = LOW  -> 芯片复位
time.sleep(0.15)
s.rts = False   # EN  = HIGH -> 释放复位，开始运行
time.sleep(0.1)

s.reset_input_buffer()

end = time.time() + secs
try:
    while time.time() < end:
        data = s.read(8192)
        if data:
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()
finally:
    s.close()

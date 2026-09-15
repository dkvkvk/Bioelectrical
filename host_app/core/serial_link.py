"""串口（USB线）连接模块：在独立线程里读写串口。

协议（与固件 main/uart.c 一致）:
- 设备 → 上位机: 9 字节帧 FF 09 2E | CH1(2大端) | CH2(2) | 心率(1) | CRC8(1)
  每帧 1 个样本。开机日志等垃圾字节靠帧头+CRC 自动重同步跳过。
- 上位机 → 设备: 与蓝牙相同的 6 字节设置命令。
- 设备要求 30 秒内收到一次命令维持会话，否则停止发数据 → 本模块自动
  每 KEEPALIVE_S 秒重发最近一次设置命令保活。
"""

import time
from typing import Optional

import serial
from serial.tools import list_ports
from PySide6.QtCore import QThread, Signal

from .ble_link import (
    ST_CONNECTED, ST_DISCONNECTED, ST_IDLE,
)
from .frame_parser import FrameParser, extract_uart_frames

BAUD = 115200
KEEPALIVE_S = 20.0    # 设备会话30秒超时，20秒保活留足余量
READ_TIMEOUT_S = 0.05
BATCH_SAMPLES = 4     # 与蓝牙批次一致：凑满4个样本发一批


def available_ports() -> list:
    """列出电脑上的串口 [(端口名, 描述)]。"""
    out = []
    for p in list_ports.comports():
        desc = p.description or ""
        if "蓝牙" in desc and "COM" not in (p.device or ""):
            continue  # 过滤 Windows 的蓝牙串口虚拟口
        out.append((p.device, desc))
    return sorted(out)


def friendly_serial_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "could not open port" in text or "permission" in text or "access" in text:
        return "串口打不开：可能被其他软件占用（比如烧录工具、串口助手），请关掉后重试"
    if "does not exist" in text or "not found" in text or "FileNotFoundError".lower() in text:
        return "串口不存在：设备可能没插好，请点「刷新端口」重试"
    return "串口连接失败：" + str(exc)


class SerialLink(QThread):
    frames = Signal(object)            # 4样本批次 dict（与 BleLink 相同格式）
    state_changed = Signal(str, str)   # (状态, 中文说明)
    log = Signal(str)

    def __init__(self, parser: FrameParser, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self._port: Optional[str] = None
        self._ser = None
        self._running = False
        self._pending_cmd: Optional[bytes] = None
        self._last_cmd: Optional[bytes] = None
        self._last_keepalive = 0.0
        self._state = ST_IDLE

    # ------------------------------------------------------------ 公开操作（界面线程调用）

    def connect_to(self, port: str) -> None:
        if self.isRunning():
            return
        self._port = port
        self.start()

    def disconnect(self) -> None:
        self._running = False

    def send_command(self, ch1: int, ch2: int, sr: int, f1: int, f2: int,
                     sw: int) -> None:
        """设置命令会立即发出，并作为之后的保活命令周期重发。"""
        self._pending_cmd = bytes((ch1 & 0xFF, ch2 & 0xFF, sr & 0xFF,
                                   f1 & 0xFF, f2 & 0xFF, sw & 0xFF))

    # ------------------------------------------------------------ 线程体

    def run(self) -> None:
        try:
            self._ser = serial.Serial(self._port, BAUD, timeout=READ_TIMEOUT_S)
        except Exception as exc:
            self._set_state(ST_IDLE, friendly_serial_error(exc))
            return

        self._running = True
        self._set_state(ST_CONNECTED, f"串口已连接 {self._port}")
        self.log.emit(f"串口已连接：{self._port} @ {BAUD}")

        buf = bytearray()
        acc1: list = []
        acc2: list = []
        last_hr = 0
        unexpected = False

        while self._running:
            # ---- 发送：新命令优先，否则按周期保活 ----
            if self._pending_cmd is not None:
                cmd, self._pending_cmd = self._pending_cmd, None
                if self._write(cmd):
                    self._last_cmd = cmd
                    self._last_keepalive = time.time()
            elif (self._last_cmd is not None
                  and time.time() - self._last_keepalive >= KEEPALIVE_S):
                self._pending_cmd = self._last_cmd  # 下轮循环发出

            # ---- 接收 ----
            try:
                data = self._ser.read(4096)
            except Exception as exc:
                self._set_state(ST_DISCONNECTED,
                                "串口连接断开：" + friendly_serial_error(exc))
                unexpected = True
                break
            if not data:
                continue
            buf.extend(data)
            frames, buf = extract_uart_frames(buf)
            for f in frames:
                sample = self.parser.feed_uart(f)
                if sample is None:
                    continue
                acc1.append(sample["ch1"])
                acc2.append(sample["ch2"])
                last_hr = sample["heart_rate"]
                if len(acc1) >= BATCH_SAMPLES:
                    self.frames.emit({
                        "ch1": acc1[:BATCH_SAMPLES],
                        "ch2": acc2[:BATCH_SAMPLES],
                        "battery": None,
                        "lead_off": 0,
                        "heart_rate": last_hr,
                    })
                    acc1 = acc1[BATCH_SAMPLES:]
                    acc2 = acc2[BATCH_SAMPLES:]

        try:
            self._ser.close()
        except Exception:
            pass
        self._ser = None
        if not unexpected:
            self._set_state(ST_IDLE, "串口已断开")

    def _write(self, data: bytes) -> bool:
        try:
            self._ser.write(data)
            return True
        except Exception as exc:
            self._set_state(ST_DISCONNECTED,
                            "串口发送失败：" + friendly_serial_error(exc))
            self._running = False
            return False

    def _set_state(self, state: str, msg: str) -> None:
        self._state = state
        self.state_changed.emit(state, msg)

"""蓝牙连接模块：在独立线程里跑 asyncio 事件循环，负责扫描/连接设备、
订阅数据、发送 6 字节控制命令。界面线程通过信号收数据、通过公开方法发指令。

协议细节见 doc/host_esp32_ble_protocol.md。
"""

import asyncio
import threading
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .frame_parser import FrameParser

DEVICE_NAME = "BLE_EEG"
UUID_SERVICE = "8653000a-43e6-47b7-9cb0-5fc21d4ae340"
UUID_DATA = "8653000b-43e6-47b7-9cb0-5fc21d4ae340"
UUID_CMD = "8653000c-43e6-47b7-9cb0-5fc21d4ae340"

# 状态常量
ST_IDLE = "idle"
ST_SCANNING = "scanning"
ST_CONNECTING = "connecting"
ST_CONNECTED = "connected"
ST_DISCONNECTED = "disconnected"


def friendly_ble_error(exc: Exception) -> str:
    """把 bleak 的常见报错翻译成普通人能看懂的话。"""
    text = str(exc).lower()
    if "bluetooth is turned off" in text or "radio" in text:
        return "电脑蓝牙没有打开，请先开启蓝牙再试"
    if "not found" in text or "timeout" in text:
        return "没有找到设备。请确认：设备已开机、离电脑不超过2米、没有连着其他软件"
    if "pairing" in text or "authentication" in text:
        return "蓝牙配对出现问题，请删除系统里已配对的设备后重试"
    return "蓝牙连接失败：" + str(exc)


class BleLink(QThread):
    frames = Signal(object)            # 解析好的批次 dict（每帧 4 个样本）
    state_changed = Signal(str, str)   # (状态, 中文说明)
    scan_hit = Signal(str, str)        # (设备地址, 显示名)
    log = Signal(str)

    def __init__(self, parser: FrameParser, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._client = None
        self._state = ST_IDLE

    # ------------------------------------------------------------ 线程体

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _post(self, coro) -> None:
        # 最多等2秒事件循环就绪；线程没启动/已退出时直接丢弃任务
        if not self._ready.wait(2.0):
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _set_state(self, state: str, msg: str) -> None:
        self._state = state
        self.state_changed.emit(state, msg)

    # ------------------------------------------------------------ 公开操作（界面线程调用）

    def scan(self) -> None:
        self._post(self._scan())

    def connect_to(self, address: str) -> None:
        self._post(self._connect(address))

    def disconnect(self) -> None:
        self._post(self._disconnect())

    def send_command(self, ch1: int, ch2: int, sr: int, f1: int, f2: int,
                     sw: int) -> None:
        self._post(self._send_command(ch1, ch2, sr, f1, f2, sw))

    def shutdown(self) -> None:
        if self._loop is not None and self.isRunning():
            self._post(self._shutdown())

    # ------------------------------------------------------------ 协程实现

    async def _scan(self) -> None:
        from bleak import BleakScanner
        self._set_state(ST_SCANNING, "正在扫描附近的设备（约6秒）……")
        try:
            results = await BleakScanner.discover(timeout=6.0, return_adv=True)
        except Exception as exc:
            self._set_state(ST_IDLE, friendly_ble_error(exc))
            return
        hits = []
        for addr, (dev, adv) in results.items():
            name = dev.name or adv.local_name or ""
            uuids = [str(u).lower() for u in (adv.service_uuids or [])]
            if name.startswith(DEVICE_NAME) or UUID_SERVICE in uuids:
                hits.append((addr, name or DEVICE_NAME))
        for addr, name in hits:
            self.scan_hit.emit(addr, name)
        if hits:
            self._set_state(ST_IDLE, f"扫描到 {len(hits)} 个设备，请在下拉框选择后点「连接」")
        else:
            self._set_state(ST_IDLE, "没有扫到设备。请确认设备已开机并且没有连着其他软件")

    async def _connect(self, address: str) -> None:
        from bleak import BleakClient
        self._set_state(ST_CONNECTING, "正在连接设备……")

        def _on_disconnect(c):
            # 手动断开时状态已被置为 IDLE，这里只处理意外断开
            if self._state == ST_CONNECTED:
                self._set_state(ST_DISCONNECTED, "设备连接已断开")

        client = BleakClient(address, disconnected_callback=_on_disconnect)
        try:
            await client.connect()
        except Exception as exc:
            self._set_state(ST_IDLE, friendly_ble_error(exc))
            return
        self._client = client

        try:
            await client.start_notify(UUID_DATA, self._on_notify)
        except Exception as exc:
            self._set_state(ST_IDLE, friendly_ble_error(exc))
            return
        self._set_state(ST_CONNECTED, "已连接 " + (address or ""))
        self.log.emit(f"蓝牙已连接：{address}")

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._set_state(ST_IDLE, "已手动断开")

    async def _send_command(self, ch1, ch2, sr, f1, f2, sw) -> None:
        if self._client is None or not self._client.is_connected:
            self.log.emit("发送失败：设备未连接")
            return
        data = bytes((ch1 & 0xFF, ch2 & 0xFF, sr & 0xFF,
                      f1 & 0xFF, f2 & 0xFF, sw & 0xFF))
        try:
            await self._client.write_gatt_char(UUID_CMD, data, response=False)
            self.log.emit(
                f"已发送设置: 增益寄存器 CH1=0x{ch1:02X} CH2=0x{ch2:02X} "
                f"采样率=0x{sr:02X} 滤波CH1={'开' if f1 else '关'} "
                f"CH2={'开' if f2 else '关'} 数据流={'开' if sw else '停'}")
        except Exception as exc:
            self.log.emit("发送设置失败：" + str(exc))

    async def _shutdown(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._loop.stop()

    # ------------------------------------------------------------ 数据回调（蓝牙线程内）

    def _on_notify(self, _handle: int, data: bytearray) -> None:
        batch = self.parser.feed(bytes(data))
        if batch is not None:
            self.frames.emit(batch)

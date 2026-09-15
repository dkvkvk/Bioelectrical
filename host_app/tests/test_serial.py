"""串口功能测试：9字节帧解析 + 字节流重同步 + 假串口设备全链路。"""
import os
import sys
import time
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

from core import serial_link as sl  # noqa: E402
from core.frame_parser import (  # noqa: E402
    FrameParser, build_uart_frame, extract_uart_frames,
)

# QThread + 跨线程信号在没有 QApplication/CoreApplication 时行为不稳定，
# 测试环境必须先建一个（真实软件里始终存在应用对象）
_app = QCoreApplication.instance() or QCoreApplication([])

CMD_360_500_FON = bytes((0x20, 0x00, 0x02, 0x01, 0x01, 0x01))


def test_uart_frame_roundtrip():
    p = FrameParser()
    s = p.feed_uart(build_uart_frame(1.2, 0.5, heart_rate=71))
    assert s is not None
    assert abs(s["ch1"] - 1.2) <= 0.0002 and abs(s["ch2"] - 0.5) <= 0.0002
    assert s["heart_rate"] == 71 and s["battery"] is None and s["lead_off"] == 0
    assert p.frames_ok == 1


def test_uart_frame_bias():
    p = FrameParser()
    p.filter_ch1 = True
    p.filter_ch2 = True
    s = p.feed_uart(build_uart_frame(1.0, 1.0))
    assert abs(s["ch1"] - 0.1) < 0.0002 and abs(s["ch2"] - 0.1) < 0.0002


def test_uart_frame_bad():
    p = FrameParser()
    good = build_uart_frame(1.0, 1.0)
    assert p.feed_uart(good) is not None
    assert p.feed_uart(good[:8]) is None                    # 长度错
    bad = bytearray(good); bad[0] = 0x00
    assert p.feed_uart(bytes(bad)) is None                  # 帧头错
    bad = bytearray(good); bad[3] ^= 0xFF
    assert p.feed_uart(bytes(bad)) is None                  # CRC错
    assert p.frames_ok == 1 and p.frames_bad == 3


def test_stream_resync():
    """垃圾字节（模拟开机日志）混在帧中间也能正确提取。"""
    f1 = build_uart_frame(1.0, 0.5)
    f2 = build_uart_frame(1.1, 0.6)
    f3 = build_uart_frame(1.2, 0.7)
    stream = bytearray()
    stream += b"ets Jul 29 2024\r\nI (325) boot: chip rev: v0.2\r\n"  # 开机日志
    stream += f1
    stream += b"\x00\xFF"        # 垃圾（含假帧头字节）
    stream += f2
    stream += f3[:5]             # 半截帧
    frames, rest = extract_uart_frames(bytearray(stream))
    assert frames == [f1, f2]
    assert bytes(rest) == f3[:5]
    # 半截帧补全后能继续提取
    frames2, rest2 = extract_uart_frames(bytearray(rest) + f3[5:])
    assert frames2 == [f3] and not rest2


class FakeSerial:
    """假装是一个串口设备：注入要发的字节，记录上位机写来的字节。

    注意 read 的语义模仿真 pyserial：没数据时阻塞等待一小段再返回空，
    而不是立即返回——否则上层循环会以每秒百万次空转，与真实串口行为
    完全不同，也不符合 pyserial 的 timeout 语义。
    """
    instances = []

    def __init__(self, port, baudrate=115200, timeout=0.05):
        self.port = port
        self.timeout = timeout
        self.written = []
        self._stream = bytearray()
        FakeSerial.instances.append(self)

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, n):
        if not self._stream:
            time.sleep(self.timeout)   # 模拟 pyserial 的阻塞等待
            return b""
        chunk = bytes(self._stream[:n])
        del self._stream[:n]
        return chunk

    def inject(self, data):
        self._stream.extend(data)

    def close(self):
        pass


def _wait(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _diag(link, p, batches):
    dev = FakeSerial.instances[0] if FakeSerial.instances else None
    print(f"[diag] thread_running={link.isRunning()} frames_ok={p.frames_ok} "
          f"frames_bad={p.frames_bad} batches={len(batches)} "
          f"stream_left={len(dev._stream) if dev else '-'} "
          f"written={len(dev.written) if dev else '-'}")


def test_serial_link_full_path():
    """假串口全链路：连接 → 发命令 → 收数据成批 → 保活重发 → 断开。"""
    FakeSerial.instances.clear()
    sl.serial = types.SimpleNamespace(Serial=FakeSerial)  # 替换真串口
    sl.KEEPALIVE_S = 0.3  # 测试用短保活

    p = FrameParser()
    link = sl.SerialLink(p)
    batches, states = [], []
    link.frames.connect(lambda b: batches.append(b), Qt.DirectConnection)
    link.state_changed.connect(
        lambda s, m: states.append(s), Qt.DirectConnection)

    link.connect_to("COM_FAKE")
    assert _wait(lambda: "connected" in states), "没有进入已连接状态"

    link.send_command(0x20, 0x00, 0x02, 1, 1, 1)
    assert _wait(lambda: FakeSerial.instances and FakeSerial.instances[0].written)
    assert FakeSerial.instances[0].written[0] == CMD_360_500_FON

    dev = FakeSerial.instances[0]
    # 注入：一段垃圾 + 32个帧（串口每帧1个样本，4样本凑一批 → 8批）
    dev.inject(b"boot log...\r\n")
    for i in range(32):
        dev.inject(build_uart_frame(1.0 + i * 0.001, 0.5))
    if not _wait(lambda: len(batches) >= 8):
        _diag(link, p, batches)
        raise AssertionError("没有收到数据批次")
    assert all(len(b["ch1"]) == 4 for b in batches)
    assert abs(batches[0]["ch1"][0] - 1.0) < 0.0002
    assert p.frames_ok >= 8

    # 保活：等超过 KEEPALIVE_S，命令应被重发
    n_before = len(dev.written)
    assert _wait(lambda: len(dev.written) > n_before, timeout=3), "保活命令没有重发"
    assert dev.written[-1] == CMD_360_500_FON

    link.disconnect()
    link.wait(3000)
    assert not link.isRunning()
    sl.KEEPALIVE_S = 20.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_serial 全部通过")

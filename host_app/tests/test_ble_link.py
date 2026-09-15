"""蓝牙模块冒烟测试：不依赖真机，验证模块可导入、错误翻译、
以及用假设备对象走一遍 BleLink 的回调链路。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.ble_link import BleLink, friendly_ble_error  # noqa: E402
from core.frame_parser import FrameParser, build_frame  # noqa: E402


def test_friendly_errors():
    assert "蓝牙" in friendly_ble_error(Exception("Bluetooth is turned off"))
    assert "没有找到设备" in friendly_ble_error(Exception("Device not found"))
    assert "失败" in friendly_ble_error(Exception("whatever else"))


def test_notify_path():
    """模拟一帧真机数据从蓝牙回调进入解析器。"""
    p = FrameParser()
    link = BleLink(p)
    got = []
    link.frames.connect(lambda b: got.append(b))
    frame = build_frame([1.2, 1.21, 1.19, 1.22], [0.5, 0.51, 0.49, 0.52])
    link._on_notify(0, bytearray(frame))
    assert len(got) == 1 and got[0]["battery"] == 87
    assert p.frames_ok == 1


def test_thread_lifecycle():
    """线程能启动、能接收任务、能干净退出。"""
    p = FrameParser()
    link = BleLink(p)
    link.start()
    done = []

    async def noop():
        done.append(True)

    link._post(noop())
    link.shutdown()
    link.wait(3000)
    assert done and not link.isRunning()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_ble_link 全部通过")

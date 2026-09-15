"""帧解析测试：CRC 标准校验值 + 构帧/解帧往返 + 坏帧处理。"""
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.frame_parser import FrameParser, build_frame, crc8  # noqa: E402


def crc8_bitwise(data: bytes, poly: int = 0x07) -> int:
    """独立实现的逐位 CRC-8，用来交叉验证查表法抄写无误。"""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def test_crc8_standard_vector():
    assert crc8(b"123456789") == 0xF4, "CRC-8/ATM 标准校验值应为 0xF4"
    rnd = random.Random(1)
    for _ in range(20):
        data = bytes(rnd.randrange(256) for _ in range(23))
        assert crc8(data) == crc8_bitwise(data), "查表法与逐位法不一致"


def test_roundtrip():
    ch1 = [1.2, 1.21, 1.19, 1.22]
    ch2 = [0.5, 0.51, 0.49, 0.52]
    frame = build_frame(ch1, ch2, battery=88, lead_off=0, heart_rate=71)
    assert len(frame) == 23
    p = FrameParser()
    b = p.feed(frame)
    assert b is not None, "合法帧被拒"
    assert b["battery"] == 88 and b["heart_rate"] == 71 and b["lead_off"] == 0
    for i in range(4):
        assert abs(b["ch1"][i] - ch1[i]) <= 0.0002, "电压往返误差超限"
        assert abs(b["ch2"][i] - ch2[i]) <= 0.0002
    assert p.frames_ok == 1 and p.frames_bad == 0


def test_bias_removal():
    """固件开滤波时数据带 0.9V 偏置，解析层应减回。"""
    p = FrameParser()
    p.filter_ch1 = True
    p.filter_ch2 = True
    b = p.feed(build_frame([1.0] * 4, [1.0] * 4))
    assert abs(b["ch1"][0] - 0.1) < 0.0002
    assert abs(b["ch2"][0] - 0.1) < 0.0002


def test_bad_frames():
    p = FrameParser()
    good = build_frame([1.0] * 4, [1.0] * 4)
    assert p.feed(good) is not None
    assert p.feed(good[:22]) is None, "长度错误应被拒"
    bad_hdr = bytearray(good)
    bad_hdr[0] = 0x00
    assert p.feed(bytes(bad_hdr)) is None, "帧头错误应被拒"
    bad_crc = bytearray(good)
    bad_crc[5] ^= 0xFF
    assert p.feed(bytes(bad_crc)) is None, "CRC错误应被拒"
    assert p.frames_ok == 1 and p.frames_bad == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_frame_parser 全部通过")

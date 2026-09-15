"""23 字节数据帧的解析与校验，规则与固件 main/ble.c、main/protocol_crc.c 完全一致。

帧结构（大端）:
    FF 17 2E | 电量(1) | CH1(2)+CH2(2) ×4组 | 脱落(1) | 心率(1) | CRC8(1)

数值换算:
    原始值 = 电压(V) × 10000
    固件开软件滤波时会加上约 0.9V 的显示偏置，解析时需要减回。
"""

from typing import List, Optional, Tuple

FRAME_LEN = 23
SAMPLES_PER_FRAME = 4
HEADER = bytes((0xFF, 0x17, 0x2E))
DISPLAY_BIAS_V = 0.9

# 串口（USB线）帧：与固件 main/uart.c 一致，每帧 1 个样本，无电量/脱落字段
UART_FRAME_LEN = 9
UART_HEADER = bytes((0xFF, 0x09, 0x2E))

# 与固件 protocol_crc.c 中 crc8_table 逐字节一致（CRC-8，多项式 0x07，查表法）
_CRC8_TABLE = (
    0x00, 0x07, 0x0E, 0x09, 0x1C, 0x1B, 0x12, 0x15,
    0x38, 0x3F, 0x36, 0x31, 0x24, 0x23, 0x2A, 0x2D,
    0x70, 0x77, 0x7E, 0x79, 0x6C, 0x6B, 0x62, 0x65,
    0x48, 0x4F, 0x46, 0x41, 0x54, 0x53, 0x5A, 0x5D,
    0xE0, 0xE7, 0xEE, 0xE9, 0xFC, 0xFB, 0xF2, 0xF5,
    0xD8, 0xDF, 0xD6, 0xD1, 0xC4, 0xC3, 0xCA, 0xCD,
    0x90, 0x97, 0x9E, 0x99, 0x8C, 0x8B, 0x82, 0x85,
    0xA8, 0xAF, 0xA6, 0xA1, 0xB4, 0xB3, 0xBA, 0xBD,
    0xC7, 0xC0, 0xC9, 0xCE, 0xDB, 0xDC, 0xD5, 0xD2,
    0xFF, 0xF8, 0xF1, 0xF6, 0xE3, 0xE4, 0xED, 0xEA,
    0xB7, 0xB0, 0xB9, 0xBE, 0xAB, 0xAC, 0xA5, 0xA2,
    0x8F, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9D, 0x9A,
    0x27, 0x20, 0x29, 0x2E, 0x3B, 0x3C, 0x35, 0x32,
    0x1F, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0D, 0x0A,
    0x57, 0x50, 0x59, 0x5E, 0x4B, 0x4C, 0x45, 0x42,
    0x6F, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7D, 0x7A,
    0x89, 0x8E, 0x87, 0x80, 0x95, 0x92, 0x9B, 0x9C,
    0xB1, 0xB6, 0xBF, 0xB8, 0xAD, 0xAA, 0xA3, 0xA4,
    0xF9, 0xFE, 0xF7, 0xF0, 0xE5, 0xE2, 0xEB, 0xEC,
    0xC1, 0xC6, 0xCF, 0xC8, 0xDD, 0xDA, 0xD3, 0xD4,
    0x69, 0x6E, 0x67, 0x60, 0x75, 0x72, 0x7B, 0x7C,
    0x51, 0x56, 0x5F, 0x58, 0x4D, 0x4A, 0x43, 0x44,
    0x19, 0x1E, 0x17, 0x10, 0x05, 0x02, 0x0B, 0x0C,
    0x21, 0x26, 0x2F, 0x28, 0x3D, 0x3A, 0x33, 0x34,
    0x4E, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5C, 0x5B,
    0x76, 0x71, 0x78, 0x7F, 0x6A, 0x6D, 0x64, 0x63,
    0x3E, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2C, 0x2B,
    0x06, 0x01, 0x08, 0x0F, 0x1A, 0x1D, 0x14, 0x13,
    0xAE, 0xA9, 0xA0, 0xA7, 0xB2, 0xB5, 0xBC, 0xBB,
    0x96, 0x91, 0x98, 0x9F, 0x8A, 0x8D, 0x84, 0x83,
    0xDE, 0xD9, 0xD0, 0xD7, 0xC2, 0xC5, 0xCC, 0xCB,
    0xE6, 0xE1, 0xE8, 0xEF, 0xFA, 0xFD, 0xF4, 0xF3,
)


def crc8(data: bytes) -> int:
    """与固件 Fast_CRC_Cal8Bits(0x00, len, buf) 一致的 CRC-8。"""
    crc = 0
    for b in data:
        crc ^= b
        crc = _CRC8_TABLE[crc]
    return crc


class FrameParser:
    """把蓝牙收到的原始字节解析成电压样本和状态，并统计好帧/坏帧数量。"""

    def __init__(self) -> None:
        self.frames_ok = 0
        self.frames_bad = 0
        # 固件端软件滤波开关：开启时数据里带有 0.9V 显示偏置，需要减回。
        # 由界面在发送设置命令时同步更新。
        self.filter_ch1 = False
        self.filter_ch2 = False

    def feed(self, buf: bytes) -> Optional[dict]:
        """解析一帧。帧头/CRC/长度任一不对返回 None，否则返回:
        {"ch1": [4个电压V], "ch2": [...], "battery": int,
         "lead_off": 0/1(1=电极脱落), "heart_rate": int}
        """
        if len(buf) != FRAME_LEN or bytes(buf[:3]) != HEADER:
            self.frames_bad += 1
            return None
        if crc8(bytes(buf[:22])) != buf[22]:
            self.frames_bad += 1
            return None

        ch1 = []
        ch2 = []
        for i in range(SAMPLES_PER_FRAME):
            o = 4 + i * 4
            v1 = ((buf[o] << 8) | buf[o + 1]) / 10000.0
            v2 = ((buf[o + 2] << 8) | buf[o + 3]) / 10000.0
            if self.filter_ch1:
                v1 -= DISPLAY_BIAS_V
            if self.filter_ch2:
                v2 -= DISPLAY_BIAS_V
            ch1.append(v1)
            ch2.append(v2)

        self.frames_ok += 1
        return {
            "ch1": ch1,
            "ch2": ch2,
            "battery": buf[3],
            "lead_off": buf[20],
            "heart_rate": buf[21],
        }

    def feed_uart(self, buf: bytes) -> Optional[dict]:
        """解析一个 9 字节串口帧。成功返回:
        {"ch1": 电压V, "ch2": 电压V, "heart_rate": int,
         "battery": None(串口帧无电量), "lead_off": 0(串口帧无脱落字段)}
        """
        if len(buf) != UART_FRAME_LEN or bytes(buf[:3]) != UART_HEADER:
            self.frames_bad += 1
            return None
        if crc8(bytes(buf[:8])) != buf[8]:
            self.frames_bad += 1
            return None
        v1 = ((buf[3] << 8) | buf[4]) / 10000.0
        v2 = ((buf[5] << 8) | buf[6]) / 10000.0
        if self.filter_ch1:
            v1 -= DISPLAY_BIAS_V
        if self.filter_ch2:
            v2 -= DISPLAY_BIAS_V
        self.frames_ok += 1
        return {
            "ch1": v1,
            "ch2": v2,
            "heart_rate": buf[7],
            "battery": None,
            "lead_off": 0,
        }


def extract_uart_frames(buf: bytearray) -> Tuple[List[bytes], bytearray]:
    """从连续字节流中提取所有完整且 CRC 正确的 9 字节串口帧。

    开机日志等垃圾字节会被自动跳过（按帧头+CRC 重同步）。
    返回 (帧列表, 剩余字节)——剩余的不完整尾部留给下次拼接。
    """
    frames: List[bytes] = []
    i = 0
    n = len(buf)
    while i + UART_FRAME_LEN <= n:
        if buf[i] == 0xFF and buf[i + 1] == 0x09 and buf[i + 2] == 0x2E:
            f = bytes(buf[i:i + UART_FRAME_LEN])
            if crc8(f[:8]) == f[8]:
                frames.append(f)
                i += UART_FRAME_LEN
                continue
        i += 1
    return frames, buf[i:]


def build_frame(ch1_samples, ch2_samples, battery=87, lead_off=0,
                heart_rate=72) -> bytes:
    """按协议构造一帧（测试/演示用）。ch1_samples/ch2_samples 为 4 个
    电压(V) 值组成的序列，电压会乘以 10000 后取整。"""
    vals1 = [max(0, min(0xFFFF, int(round(v * 10000)))) for v in ch1_samples]
    vals2 = [max(0, min(0xFFFF, int(round(v * 10000)))) for v in ch2_samples]
    buf = bytearray(FRAME_LEN)
    buf[0:3] = HEADER
    buf[3] = battery & 0xFF
    for i in range(SAMPLES_PER_FRAME):
        o = 4 + i * 4
        buf[o] = (vals1[i] >> 8) & 0xFF
        buf[o + 1] = vals1[i] & 0xFF
        buf[o + 2] = (vals2[i] >> 8) & 0xFF
        buf[o + 3] = vals2[i] & 0xFF
    buf[20] = lead_off & 0xFF
    buf[21] = heart_rate & 0xFF
    buf[22] = crc8(bytes(buf[:22]))
    return bytes(buf)


def build_uart_frame(ch1_v: float, ch2_v: float, heart_rate: int = 72) -> bytes:
    """按串口协议构造一个 9 字节帧（测试/演示用）。"""
    v1 = max(0, min(0xFFFF, int(round(ch1_v * 10000))))
    v2 = max(0, min(0xFFFF, int(round(ch2_v * 10000))))
    buf = bytearray(UART_FRAME_LEN)
    buf[0:3] = UART_HEADER
    buf[3] = (v1 >> 8) & 0xFF
    buf[4] = v1 & 0xFF
    buf[5] = (v2 >> 8) & 0xFF
    buf[6] = v2 & 0xFF
    buf[7] = heart_rate & 0xFF
    buf[8] = crc8(bytes(buf[:8]))
    return bytes(buf)

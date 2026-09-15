"""模拟信号源：生成带已知 RR 序列的合成心电。

两个用途:
1. 演示模式——界面在没有真机时也能看波形、录制、分析;
2. 自动测试——RR 序列是预设的"标准答案"，用来验证分析引擎算得准不准。
"""

from typing import Optional, Tuple

import numpy as np

# 心电波形模板: (相对R波的偏移秒, 相对幅度(R=1.0), 宽度秒)
_ECG_WAVES = (
    (-0.20, 0.06, 0.045),    # P 波
    (-0.035, -0.08, 0.012),  # Q 波
    (0.000, 1.00, 0.011),    # R 波
    (0.035, -0.20, 0.014),   # S 波
    (0.30, 0.20, 0.060),     # T 波
)


def make_rr_series(n_beats: int, base_ms: float = 850.0,
                   lf_amp_ms: float = 25.0, hf_amp_ms: float = 18.0,
                   noise_ms: float = 6.0, seed: int = 42) -> np.ndarray:
    """生成带低频(0.1Hz)/高频(0.25Hz)调制和随机成分的 RR 序列（毫秒）。"""
    rng = np.random.default_rng(seed)
    rr = np.empty(n_beats)
    t = 0.0
    for i in range(n_beats):
        v = base_ms
        v += lf_amp_ms * np.sin(2 * np.pi * 0.10 * t)
        v += hf_amp_ms * np.sin(2 * np.pi * 0.25 * t)
        v += rng.normal(0.0, noise_ms)
        rr[i] = v
        t += v / 1000.0
    return rr


def synthesize_ecg(rr_ms, fs: float, r_amp_v: float = 0.15,
                   noise_v: float = 0.008, mains_v: float = 0.004,
                   wander_v: float = 0.03, seed: int = 7,
                   artifact_prob: float = 0.0
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """按 RR 序列合成心电电压信号。

    返回 (ecg 电压数组, R 波样本索引)。默认带少量噪声、50Hz 工频和
    基线漂移，模拟真实采集条件；artifact_prob>0 时随机插入运动伪差段。
    """
    rr = np.asarray(rr_ms, dtype=float)
    total_s = float(rr.sum() / 1000.0) + 2.0
    n = int(total_s * fs)
    t = np.arange(n) / fs
    rng = np.random.default_rng(seed)

    beat_t = np.concatenate(([0.6], 0.6 + np.cumsum(rr) / 1000.0))
    r_idx = np.round(beat_t * fs).astype(int)
    r_idx = r_idx[r_idx < n]

    ecg = np.zeros(n)
    for k, bt in enumerate(beat_t):
        for off, amp, w in _ECG_WAVES:
            c = bt + off
            i0 = max(0, int((c - 4 * w) * fs))
            i1 = min(n, int((c + 4 * w) * fs) + 1)
            if i1 <= i0:
                continue
            tt = t[i0:i1] - c
            ecg[i0:i1] += amp * r_amp_v * np.exp(-0.5 * (tt / w) ** 2)

    ecg += noise_v * rng.standard_normal(n)                        # 白噪
    ecg += mains_v * np.sin(2 * np.pi * 50.0 * t + 1.3)            # 工频
    ecg += wander_v * np.sin(2 * np.pi * 0.28 * t + 0.5)           # 基线漂移
    if artifact_prob > 0:
        n_art = max(1, int(len(beat_t) * artifact_prob))
        for _ in range(n_art):
            a = int(rng.integers(int(fs), max(int(fs) + 1, n - int(fs))))
            dur = int(rng.integers(int(0.2 * fs), int(0.5 * fs)))
            ecg[a:a + dur] += 0.3 * rng.standard_normal(min(dur, n - a))  # 运动伪差
    return ecg, r_idx


# ---------------------------------------------------------------- 演示设备

class DemoSource:
    """预生成一段心电，按 500Hz 定时回放，输出与 FrameParser.feed 相同
    格式的批次 dict，界面走与真机完全相同的显示/录制/分析路径。"""

    FS = 500.0

    def __init__(self, seed: int = 42, minutes: float = 10.0) -> None:
        n_beats = int(minutes * 60.0 * 60.0 / 850.0)
        rr = make_rr_series(n_beats, seed=seed)
        ecg, r_idx = synthesize_ecg(rr, self.FS, artifact_prob=0.004)
        self.ecg = ecg + 1.2  # 加直流偏置，模拟 ADC 输出电压水平
        self.r_idx = set(int(i) for i in r_idx)
        self.rr = rr
        self.pos = 0
        self._hr_i = 0
        self.battery = 87

    def next_batches(self, n_samples: int) -> list:
        """取接下来 n_samples 个点，打包成每帧 4 个点的批次列表。"""
        out = []
        remaining = n_samples
        while remaining > 0:
            take = min(4, remaining)
            seg = []
            for _ in range(take):
                if self.pos >= len(self.ecg):
                    self.pos = 0  # 循环回放
                seg.append(self.pos)
                self.pos += 1
            ch1 = [float(self.ecg[i]) for i in seg]
            ch2 = [float(self.ecg[i]) * 0.05 + 1.1 for i in seg]
            hr = int(round(60000.0 / self.rr[self._hr_i % len(self.rr)]))
            self._hr_i += 1
            out.append({
                "ch1": ch1,
                "ch2": ch2,
                "battery": self.battery,
                "lead_off": 0,
                "heart_rate": hr,
            })
            remaining -= take
        return out

    def tick_minutes(self, elapsed_s: float) -> None:
        """按演示时间缓慢掉电，纯粹为了状态栏好看。"""
        self.battery = max(5, 87 - int(elapsed_s / 60.0 * 1))

"""HRV 分析引擎：数据清洗 → R 波检测 → RR 间期 → 质量把关 → 各项指标。

设计为独立模块：只依赖 numpy/scipy，输入 (心电数组, 采样率)，
输出 HrvResult（包含画图所需的全部中间数据），界面层和以后的设备端
移植都可以直接复用。
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.signal import butter, filtfilt, find_peaks, iirnotch, welch

# 质量把关参数
RR_MIN_MS = 300.0     # 生理下限：低于 300ms (200bpm) 视为伪差
RR_MAX_MS = 2000.0    # 生理上限：高于 2000ms (30bpm) 视为伪差
RR_DEV_RATIO = 0.20   # 相邻偏差超过参照值 20% 视为伪差
FREQ_MIN_DURATION_S = 120.0   # 频域分析要求可用数据至少 2 分钟（标准为 5 分钟）

_trapezoid = getattr(np, "trapezoid", None) or np.trapz


# ---------------------------------------------------------------- 数据清洗

def clean_ecg(x, fs: float):
    """标准滤波链（与 tools/clean_ecg.py 一致）:
    0.5Hz 高通(去基线漂移) + 50Hz 陷波(去工频) + 40Hz 低通(去高频毛刺)。
    """
    x = np.asarray(x, dtype=float)
    nyq = fs / 2.0
    b, a = butter(2, 0.5 / nyq, btype="high")
    y = filtfilt(b, a, x)
    if 50.0 < nyq * 0.95:  # 采样率够高才需要/才能做 50Hz 陷波
        b, a = iirnotch(50.0, 30.0, fs)
        y = filtfilt(b, a, y)
    if 40.0 < nyq * 0.95:
        b, a = butter(4, 40.0 / nyq, btype="low")
        y = filtfilt(b, a, y)
    return y


# ---------------------------------------------------------------- R 波检测

def detect_r_peaks(ecg, fs: float) -> np.ndarray:
    """Pan-Tompkins 类 QRS 检测，返回 R 波所在样本索引（升序）。

    流程: 5-15Hz 带通突出 QRS → 微分平方 → 150ms 滑动积分 →
    自适应阈值(信号/噪声运行估计) + 200ms 不应期 + 长间隙回搜 →
    在原信号上精确定位 R 波顶点。
    """
    x = np.asarray(ecg, dtype=float)
    n = len(x)
    min_len = max(int(fs * 5), 64)
    if n < min_len:
        return np.array([], dtype=int)

    nyq = fs / 2.0
    hi = min(15.0, nyq * 0.9)
    lo = min(5.0, hi * 0.4)
    b, a = butter(2, [lo / nyq, hi / nyq], btype="band")
    bp = filtfilt(b, a, x)

    sq = np.gradient(bp) ** 2
    w = max(1, int(round(0.15 * fs)))
    mwi = np.convolve(sq, np.ones(w), mode="same") / w

    refractory = max(1, int(0.2 * fs))
    cands, _ = find_peaks(mwi, distance=refractory)
    if len(cands) == 0:
        return np.array([], dtype=int)
    heights = mwi[cands]

    # 初始信号/噪声估计取前 2 秒
    init = mwi[: min(n, int(fs * 2))]
    spki = float(np.max(init)) if len(init) else float(np.max(mwi))
    npki = float(np.median(init)) if len(init) else float(np.median(mwi))
    if spki <= npki:  # 前 2 秒信号异常时退回全段稳健估计
        spki = float(np.percentile(mwi, 99))
        npki = float(np.median(mwi))

    accepted: list = []   # 候选列表中通过的索引
    recent_rr: list = []  # 最近的 RR 样本数
    for k in range(len(cands)):
        h = heights[k]
        idx = int(cands[k])
        thr_hi = npki + 0.25 * (spki - npki)
        thr_lo = 0.5 * thr_hi

        # 回搜：距上一个已检出峰超过约 1.7 个平均 RR，用低阈值在间隙里补找
        if accepted:
            last_pos = int(cands[accepted[-1]])
            mean_rr = float(np.mean(recent_rr)) if recent_rr else fs
            if idx - last_pos > 1.66 * mean_rr:
                gap = [j for j in range(accepted[-1] + 1, k)
                       if heights[j] > thr_lo]
                if gap:
                    j = max(gap, key=lambda t: heights[t])
                    accepted.append(j)
                    if len(accepted) >= 2:
                        recent_rr.append(int(cands[j] - cands[accepted[-2]]))
                    last_pos = int(cands[j])

        if h > thr_hi and (not accepted or idx - int(cands[accepted[-1]]) >= refractory):
            if accepted:
                recent_rr.append(idx - int(cands[accepted[-1]]))
                if len(recent_rr) > 12:
                    recent_rr.pop(0)
            accepted.append(k)
            spki = 0.125 * h + 0.875 * spki
        else:
            npki = 0.125 * h + 0.875 * npki

    if not accepted:
        return np.array([], dtype=int)

    # 在带通信号上把每个检出位置精化到真正的 R 波顶点（±80ms 内取极值）
    half = max(1, int(0.08 * fs))
    peaks = []
    for k in accepted:
        pos = int(cands[k])
        i0, i1 = max(0, pos - half), min(n, pos + half + 1)
        seg = bp[i0:i1]
        peaks.append(i0 + int(np.argmax(np.abs(seg))))
    return np.array(sorted(set(peaks)), dtype=int)


# ---------------------------------------------------------------- RR 间期

def rr_intervals(peaks, fs: float) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (每个 RR 的结束时间秒, RR 毫秒)。"""
    peaks = np.asarray(peaks, dtype=float)
    rr_ms = np.diff(peaks) / fs * 1000.0
    times_s = peaks[1:] / fs
    return times_s, rr_ms


def clean_rr(rr_ms, min_ms=RR_MIN_MS, max_ms=RR_MAX_MS,
             dev_ratio=RR_DEV_RATIO, passes=2) -> np.ndarray:
    """质量把关，返回保留掩码。

    第一道：生理范围 (300~2000ms)。
    第二道（迭代 passes 次）：与"之前最近两个有效间期的中位数"相差超过
    dev_ratio 的视为伪差剔除（捕捉漏检造成的倍长间期、毛刺造成的短间期）。
    只向后看参照，避免一个坏点污染两侧好点的判定。
    """
    rr = np.asarray(rr_ms, dtype=float)
    ok = (rr >= min_ms) & (rr <= max_ms)
    for _ in range(passes):
        changed = False
        for i in range(len(rr)):
            if not ok[i]:
                continue
            hist_mask = ok[max(0, i - 4):i]
            hist = rr[max(0, i - 4):i][hist_mask]
            if len(hist) == 0:
                continue
            ref = float(np.median(hist[-2:]))
            if abs(rr[i] - ref) > dev_ratio * ref:
                ok[i] = False
                changed = True
        if not changed:
            break
    return ok


# ---------------------------------------------------------------- 时域

def time_domain(rr_ms) -> dict:
    rr = np.asarray(rr_ms, dtype=float)
    diff = np.diff(rr)
    out = {
        "mean_rr": float(rr.mean()),
        "mean_hr": float(60000.0 / rr.mean()),
        "sdnn": float(rr.std(ddof=1)) if len(rr) > 1 else float("nan"),
        "rmssd": float(np.sqrt(np.mean(diff ** 2))) if len(diff) else float("nan"),
        "pnn50": float(100.0 * np.mean(np.abs(diff) > 50.0)) if len(diff) else float("nan"),
        "sdsd": float(diff.std(ddof=1)) if len(diff) > 1 else float("nan"),
        "cv": float(100.0 * rr.std(ddof=1) / rr.mean()) if len(rr) > 1 else float("nan"),
        "min_rr": float(rr.min()),
        "max_rr": float(rr.max()),
        "n_beats": int(len(rr)),
    }
    return out


# ---------------------------------------------------------------- 频域

FREQ_BANDS = (
    ("VLF", 0.003, 0.04),
    ("LF", 0.04, 0.15),
    ("HF", 0.15, 0.40),
)


def frequency_domain(times_s, rr_ms, fs_interp=4.0) -> Optional[dict]:
    """频域分析：三次样条插值到 4Hz 均匀序列 → 线性去趋势 → Welch 功率谱
    → 分波段积分。可用时长不足 2 分钟返回 None。"""
    times_s = np.asarray(times_s, dtype=float)
    rr = np.asarray(rr_ms, dtype=float)
    if len(rr) < 8:
        return None
    duration = times_s[-1] - times_s[0]
    if duration < FREQ_MIN_DURATION_S:
        return None

    t = np.arange(times_s[0], times_s[-1], 1.0 / fs_interp)
    rr_u = CubicSpline(times_s, rr)(t)
    rr_u = rr_u - np.polyval(np.polyfit(t - t[0], rr_u, 1), t - t[0])  # 去线性趋势

    nperseg = min(len(rr_u), 512)  # 512/4Hz = 128s 窗，Δf≈0.0078Hz
    freqs, psd = welch(rr_u, fs=fs_interp, nperseg=nperseg,
                       noverlap=nperseg // 2, window="hann")

    def band_power(f0, f1):
        m = (freqs >= f0) & (freqs < f1)
        return float(_trapezoid(psd[m], freqs[m])) if m.sum() > 1 else 0.0

    out = {}
    for name, f0, f1 in FREQ_BANDS:
        out[name.lower()] = band_power(f0, f1)
    out["tp"] = band_power(0.0, 0.40)
    out["lf_hf"] = out["lf"] / out["hf"] if out["hf"] > 0 else float("nan")
    lf_hf_sum = out["lf"] + out["hf"]
    out["lfnu"] = 100.0 * out["lf"] / lf_hf_sum if lf_hf_sum > 0 else float("nan")
    out["hfnu"] = 100.0 * out["hf"] / lf_hf_sum if lf_hf_sum > 0 else float("nan")
    out["_freqs"] = freqs
    out["_psd"] = psd
    return out


# ---------------------------------------------------------------- Poincaré

def poincare(rr_ms) -> Tuple[float, float]:
    """返回 (SD1, SD2)。SD1 反映短期变异，SD2 反映长期变异。"""
    rr = np.asarray(rr_ms, dtype=float)
    if len(rr) < 3:
        return float("nan"), float("nan")
    d = np.diff(rr)
    sd1 = float(np.sqrt(np.var(d, ddof=1) / 2.0))
    sd2 = float(np.sqrt(2.0 * np.var(rr, ddof=1) - np.var(d, ddof=1) / 2.0))
    return sd1, sd2


# ---------------------------------------------------------------- 总入口

@dataclass
class HrvResult:
    fs: float
    duration_s: float
    n_samples: int
    ecg_clean: np.ndarray                 # 清洗后的心电
    r_peaks: np.ndarray                   # R 波样本索引（全部检出）
    rr_times_s: np.ndarray                # 每个 RR 的结束时间
    rr_ms: np.ndarray                     # 全部 RR
    rr_ok_mask: np.ndarray                # 保留掩码
    time: dict = field(default_factory=dict)
    sd1: float = float("nan")
    sd2: float = float("nan")
    freq: Optional[dict] = None           # 频域指标（数据不足为 None）
    error: Optional[str] = None

    @property
    def removed_ratio(self) -> float:
        return 1.0 - float(self.rr_ok_mask.sum()) / max(1, len(self.rr_ms))

    @property
    def kept_rr(self):
        return self.rr_ms[self.rr_ok_mask]

    @property
    def kept_times(self):
        return self.rr_times_s[self.rr_ok_mask]


def analyze(ecg, fs: float) -> HrvResult:
    """对一段心电数据做完整 HRV 分析。数据太短/心跳太少时在 result.error
    里给出中文说明（界面据此提示）。"""
    ecg = np.asarray(ecg, dtype=float)
    n = len(ecg)
    duration = n / fs
    base = HrvResult(fs=fs, duration_s=duration, n_samples=n,
                     ecg_clean=np.array([]), r_peaks=np.array([], dtype=int),
                     rr_times_s=np.array([]), rr_ms=np.array([]),
                     rr_ok_mask=np.array([], dtype=bool))
    if duration < 30.0:
        base.error = "数据太短（不足30秒），至少需要约1分钟，建议安静录制3~5分钟"
        return base

    x = clean_ecg(ecg, fs)
    peaks = detect_r_peaks(x, fs)
    base.ecg_clean = x
    base.r_peaks = peaks
    if len(peaks) < 10:
        base.error = "没有找到足够的心跳（信号可能太弱或干扰太大），请检查电极接触后重新录制"
        return base

    times, rr = rr_intervals(peaks, fs)
    ok = clean_rr(rr)
    base.rr_times_s = times
    base.rr_ms = rr
    base.rr_ok_mask = ok
    if ok.sum() < 10:
        base.error = "有效心跳太少（伪差比例过高），请安静状态、电极贴好后重新录制"
        return base

    base.time = time_domain(rr[ok])
    base.sd1, base.sd2 = poincare(rr[ok])
    base.freq = frequency_domain(times[ok], rr[ok])
    return base

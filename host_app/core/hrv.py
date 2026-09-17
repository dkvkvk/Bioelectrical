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


# ---------------------------------------------------------------- QRS 波群定位

QRS_WIDE_MS = 120.0  # 宽 QRS 提示阈值（正常 80~120ms，>120ms 标记异常，课件第13页）


def delineate_qrs(ecg, r_peaks, fs: float):
    """QRS 波群定位（课件第13页斜率法）：对每个 R 波向左找 Q 起点、
    向右找 S 终点，得到每一拍的 QRS 宽度。

    判据：信号幅度回到基线带（偏离 < R 波幅度的 10%）且斜率降到 QRS
    内最大斜率的 10% 以下，并连续保持约 8ms，即认为走出了 QRS。
    Q/S 都是相对 R 的反方向偏离，用绝对偏离量判断，R 波倒置也能工作。

    返回 (q_onset, s_off, qrs_ms, valid)，数组与 r_peaks 等长；
    定位失败的拍 q/s 为 -1、宽度为 NaN、valid 为 False。
    """
    x = np.asarray(ecg, dtype=float)
    peaks = np.asarray(r_peaks, dtype=int)
    n, nb = len(x), len(peaks)
    q_on = np.full(nb, -1, dtype=int)
    s_off = np.full(nb, -1, dtype=int)
    qrs_ms = np.full(nb, np.nan)
    valid = np.zeros(nb, dtype=bool)
    if nb == 0 or n == 0:
        return q_on, s_off, qrs_ms, valid

    d = np.abs(np.diff(x, prepend=x[:1]))
    persist = max(2, int(round(0.008 * fs)))  # 需连续平坦约 8ms 才算出了 QRS

    for k, r in enumerate(peaks):
        lo = max(0, r - int(0.15 * fs))
        if k > 0:
            lo = max(lo, int(peaks[k - 1]) + 1)
        hi = min(n - 1, r + int(0.30 * fs))
        if k < nb - 1:
            hi = min(hi, int(peaks[k + 1]) - 1)
        if hi <= lo:
            continue
        base = float(np.median(x[lo:hi + 1]))  # 搜索窗大部分是基线
        r_amp = abs(float(x[r]) - base)
        core_lo, core_hi = max(0, r - int(0.09 * fs)), min(n - 1, r + int(0.10 * fs))
        if r_amp <= 0 or core_hi <= core_lo:
            continue
        slope_thr = 0.10 * float(np.max(d[core_lo:core_hi + 1]))
        amp_thr = 0.10 * r_amp
        if slope_thr <= 0:
            continue

        # Q 起点：从 R 向左，幅度和斜率同时低于阈值并保持 persist 个样本
        run, q = 0, -1
        for i in range(r - 1, lo - 1, -1):
            if abs(x[i] - base) < amp_thr and d[i] < slope_thr:
                run += 1
                if run >= persist:
                    q = i + persist - 1  # 平坦段最右侧 = QRS 起点
                    break
            else:
                run = 0
        # S 终点：从 R 向右，同样判据
        run, s = 0, -1
        for i in range(r + 1, hi + 1):
            if abs(x[i] - base) < amp_thr and d[i] < slope_thr:
                run += 1
                if run >= persist:
                    s = i - persist + 1  # 平坦段最左侧 = QRS 终点
                    break
            else:
                run = 0
        if q < 0 or s < 0:
            continue
        q_on[k], s_off[k] = q, s
        qrs_ms[k] = (s - q + 1) / fs * 1000.0
        valid[k] = True
    return q_on, s_off, qrs_ms, valid


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
        "hr_min": float(60000.0 / rr.max()),
        "hr_max": float(60000.0 / rr.min()),
        "n_beats": int(len(rr)),
    }
    return out


# 需要较长记录的时域指标参数（课件第14页）
SEGMENT_S = 300.0          # SDANN / SDNN指数按 5 分钟分段
SEGMENT_MIN_SEGS = 2       # 至少 2 段（约10分钟）才有意义
SEGMENT_MIN_BEATS = 5      # 每段至少5拍才参与统计
TRI_MIN_DURATION_S = 600.0        # 三角指数建议≥10分钟（标准为24小时长记录）
TRI_BIN_MS = 1000.0 / 128.0       # 标准直方图格宽 1/128 秒 ≈ 7.8125ms


def extra_time_domain(times_s, rr_ms) -> dict:
    """需要更长记录的时域指标（课件第14页）:
    SDANN（5分钟平均RR的标准差）、SDNN指数（5分钟SDNN的均值）、
    HRV三角指数（RR直方图总计数 / 最高一格计数）。
    时长不足时对应值为 None（界面显示"—"并在含义里说明所需时长）。
    """
    t = np.asarray(times_s, dtype=float)
    rr = np.asarray(rr_ms, dtype=float)
    out = {"sdann": None, "sdnn_index": None, "tri_index": None}
    if len(rr) < 10:
        return out

    seg_idx = ((t - t[0]) // SEGMENT_S).astype(int)
    means, stds = [], []
    for g in np.unique(seg_idx):
        v = rr[seg_idx == g]
        if len(v) >= SEGMENT_MIN_BEATS and len(v) > 1:
            means.append(float(v.mean()))
            stds.append(float(v.std(ddof=1)))
    if len(means) >= SEGMENT_MIN_SEGS:
        out["sdann"] = float(np.std(means, ddof=1))
        out["sdnn_index"] = float(np.mean(stds))

    if (t[-1] - t[0]) >= TRI_MIN_DURATION_S:
        n_bins = int(np.ceil((rr.max() - rr.min()) / TRI_BIN_MS)) + 1
        bins = np.arange(n_bins + 1) * TRI_BIN_MS + np.floor(rr.min() / TRI_BIN_MS) * TRI_BIN_MS
        hist, _ = np.histogram(rr, bins=bins)
        if hist.max() > 0:
            out["tri_index"] = float(len(rr) / hist.max())
    return out


# ---------------------------------------------------------------- 心率序列

def hr_series(times_s, rr_ms, win_secs=(60.0, 300.0), min_beats: int = 5) -> dict:
    """心率随时间的变化（课件第9~12页）:
    inst 逐拍瞬时心率（60000/RR，临床金标准思路）；
    m60 / m300 分别为最近 1 分钟 / 5 分钟滑动平均心率（时间加权，
    窗口内心跳不足 min_beats 拍时为 NaN）。
    """
    t = np.asarray(times_s, dtype=float)
    rr = np.asarray(rr_ms, dtype=float)
    out = {"inst": 60000.0 / rr}
    for w in win_secs:
        avg = np.full(len(rr), np.nan)
        for i in range(len(rr)):
            j = int(np.searchsorted(t, t[i] - w, side="left"))
            if i - j + 1 >= min_beats:
                avg[i] = 60000.0 / float(rr[j:i + 1].mean())
        out[f"m{int(w)}"] = avg
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


def spectral_hr(ecg, fs: float, fmin: float = 0.7, fmax: float = 3.5,
                bpm_step: float = 0.5) -> Optional[float]:
    """频域法心率（课件第10页，穿戴设备常用对照方案）：在 0.7~3.5Hz
    （约42~210bpm）里找心电的基频，×60 即心率。

    实现：先算功率谱再做傅里叶反变换得到自相关函数（两者等价），在
    候选周期处看"信号平移一个周期后与自身的相似度"。QRS 尖脉冲的
    谐波在谱上可能比基频还强，直接找谱峰会得出成倍心率；自相关对
    谐波不敏感：只有真周期处移位后波形才对齐。每个候选周期的得分
    减去邻域中位数（去掉相关性随延迟衰减的底噪）。
    数据太短或周期性太弱返回 None。
    """
    x = np.asarray(ecg, dtype=float)
    if len(x) < int(fs * 10):
        return None
    x = x - x.mean()
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, nfft)) ** 2)[:n]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]

    w = max(1, int(0.25 * fs))  # 邻域半宽，用于估计自相关底噪
    best_bpm, best_score = None, -2.0
    for bpm in np.arange(60.0 * fmin, 60.0 * fmax + bpm_step, bpm_step):
        tau = int(round(fs / (bpm / 60.0)))
        if tau + w >= n:
            continue
        lo, hi = max(0, tau - w), min(n, tau + w + 1)
        score = float(ac[tau] - np.median(ac[lo:hi]))
        if score > best_score:
            best_score, best_bpm = score, float(bpm)
    if best_bpm is None or best_score < 0.10:
        return None
    return best_bpm


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


# ---------------------------------------------------------------- 非线性: DFA / 样本熵

def _dfa_alpha(y: np.ndarray, scales: np.ndarray) -> Optional[float]:
    """对积分序列 y 在给定窗口尺度上做一阶去趋势波动分析，返回斜率 α。"""
    n_tot = len(y)
    log_f = []
    for s in scales:
        n_box = n_tot // int(s)
        if n_box < 2:
            return None
        boxes = y[: n_box * int(s)].reshape(n_box, int(s))
        t = np.arange(int(s), dtype=float)
        tc = t - t.mean()
        denom = float(np.sum(tc * tc))
        slope = (boxes @ tc) / denom
        inter = boxes.mean(axis=1)
        resid = boxes - (inter[:, None] + slope[:, None] * tc[None, :])
        log_f.append(np.log(np.sqrt(np.mean(resid ** 2))))
    if len(log_f) < 4:
        return None
    return float(np.polyfit(np.log(scales[:len(log_f)]), np.asarray(log_f), 1)[0])


def dfa(rr_ms, a1_scales=(4, 11), a2_scales=(11, 64),
        a1_min_beats=120, a2_min_beats=256) -> Tuple[Optional[float], Optional[float]]:
    """去趋势波动分析 DFA（课件第17页）。
    α1 短程（4~11拍窗口）：健康心脏≈1.0，明显偏低提示调节能力下降；
    α2 长程（11~64拍窗口）：需要更长的记录。
    拍数不足时对应值为 None。
    """
    rr = np.asarray(rr_ms, dtype=float)
    if len(rr) < 20:
        return None, None
    y = np.cumsum(rr - rr.mean())
    a1 = _dfa_alpha(y, np.arange(a1_scales[0], a1_scales[1] + 1)) if len(rr) >= a1_min_beats else None
    a2 = _dfa_alpha(y, np.arange(a2_scales[0], a2_scales[1] + 1)) if len(rr) >= a2_min_beats else None
    return a1, a2


def sample_entropy(rr_ms, m: int = 2, r_frac: float = 0.2,
                   min_beats: int = 150, max_beats: int = 5000) -> Optional[float]:
    """样本熵 SampEn（课件第17页）：度量 RR 序列的复杂度。
    规律性强 → 熵低（自主神经调节能力下降）；复杂多变 → 熵高。
    m=2、r=0.2×SD（常用参数）。拍数不足或无匹配对时返回 None。
    """
    rr = np.asarray(rr_ms, dtype=float)
    if len(rr) < min_beats:
        return None
    if len(rr) > max_beats:  # 等距抽样控制 O(n²) 计算量
        step = int(np.ceil(len(rr) / max_beats))
        rr = rr[::step]
    r = r_frac * float(np.std(rr, ddof=1))
    if r <= 0:
        return None

    def _match_counts(embed_len: int) -> int:
        vecs = np.lib.stride_tricks.sliding_window_view(rr, embed_len)
        close = np.ones((len(vecs), len(vecs)), dtype=bool)
        for c in range(embed_len):
            col = vecs[:, c]
            close &= np.abs(col[:, None] - col[None, :]) <= r
        return (int(np.sum(close)) - len(vecs)) // 2  # 去掉自匹配和对称重复

    b = _match_counts(m)
    a = _match_counts(m + 1)
    if a <= 0 or b <= 0:
        return None
    return float(-np.log(a / b))


# ---------------------------------------------------------------- 检测性能指标

def detection_scores(detected, truth, fs: float, tol_ms: float = 75.0) -> dict:
    """R波检测性能指标（课件第8页）：灵敏度 Se、阳性预测值 PPV、F1、
    平均定位误差(ms)。真值 ±tol_ms 内记为命中（MIT-BIH 评估惯例）。
    用于自动化测试和真机数据复核。
    """
    det = np.sort(np.asarray(detected, dtype=int))
    tr = np.sort(np.asarray(truth, dtype=int))
    tol = tol_ms / 1000.0 * fs
    matched = np.zeros(len(tr), dtype=bool)
    errs: list = []
    for dv in det:
        cand = np.nonzero(~matched & (np.abs(tr - dv) <= tol))[0]
        if len(cand):
            j = int(cand[np.argmin(np.abs(tr[cand] - dv))])
            matched[j] = True
            errs.append(abs(float(tr[j]) - float(dv)) / fs * 1000.0)
    tp = int(matched.sum())
    fn, fp = len(tr) - tp, len(det) - tp
    se = tp / (tp + fn) if (tp + fn) else float("nan")
    ppv = tp / (tp + fp) if (tp + fp) else float("nan")
    f1 = 2 * se * ppv / (se + ppv) if (se + ppv) > 0 else float("nan")
    return {"tp": tp, "fp": fp, "fn": fn, "se": se, "ppv": ppv, "f1": f1,
            "mean_err_ms": float(np.mean(errs)) if errs else float("nan")}


# ---------------------------------------------------------------- 白话解读

def interpret(time_m: dict, freq_m: Optional[dict], nonlin_m: dict,
              qrs_stats: Optional[dict] = None, removed_ratio: float = 0.0,
              duration_s: float = 0.0) -> list:
    """规则式白话解读（课件第18页临床应用的简化规则）。
    返回 [(级别, 文本), ...]，级别为 good / info / warn / alert。
    只是参考性提示，不构成医疗诊断。
    """
    f: list = []

    if duration_s and duration_s < 300.0:
        f.append(("info", f"本次录制 {duration_s/60:.1f} 分钟，不足标准短时HRV的5分钟，解读仅供参考"))
    if removed_ratio >= 0.25:
        f.append(("alert", f"伪差剔除比例达 {removed_ratio*100:.0f}%，信号质量差，建议电极贴好后重新录制"))
    elif removed_ratio >= 0.10:
        f.append(("warn", f"伪差剔除比例 {removed_ratio*100:.0f}%，信号质量一般，指标仅供参考"))

    sdnn = time_m.get("sdnn")
    if sdnn == sdnn:  # 非 NaN
        if sdnn < 50:
            f.append(("alert", "整体HRV明显偏低（SDNN<50ms），自主神经功能可能受损，建议咨询专业人员"))
        elif sdnn < 100:
            f.append(("info", "整体HRV偏低（SDNN 50~100ms）；短时录制的SDNN偏低不完全可比，建议录满5分钟以上"))
        else:
            f.append(("good", "整体HRV水平良好（SDNN≥100ms）"))

    rmssd = time_m.get("rmssd")
    if rmssd == rmssd:
        if rmssd < 15:
            f.append(("warn", "副交感（迷走）神经活性明显偏低（RMSSD<15ms）"))
        elif rmssd < 19:
            f.append(("info", "副交感神经活性偏低（RMSSD 15~19ms，常见范围19~56ms）"))
        else:
            f.append(("good", "副交感神经活性在常见范围内（RMSSD≥19ms）"))

    pnn50 = time_m.get("pnn50")
    if pnn50 == pnn50 and pnn50 < 2.0:
        f.append(("info", "pNN50 低于常见范围（2%~24%），提示副交感活性偏弱"))

    if freq_m:
        lf_hf = freq_m.get("lf_hf")
        if lf_hf == lf_hf:
            if lf_hf > 2.5:
                f.append(("warn", f"LF/HF={lf_hf:.2f}>2.5，交感神经占优势，身体可能处于紧张/压力状态"))
            elif lf_hf > 2.0:
                f.append(("info", f"LF/HF={lf_hf:.2f} 偏高（常见平衡范围1.5~2.0），略偏交感"))
            elif lf_hf < 1.5:
                f.append(("info", f"LF/HF={lf_hf:.2f} 偏低（常见平衡范围1.5~2.0），副交感相对占优，放松状态常见"))
            else:
                f.append(("good", f"交感/副交感平衡在常见范围（LF/HF={lf_hf:.2f}，1.5~2.0）"))

    alpha1 = (nonlin_m or {}).get("alpha1")
    if alpha1 is not None:
        if alpha1 < 0.75:
            f.append(("warn", f"DFA α1={alpha1:.2f} 低于健康参考（≈1.0，<0.75 提示心脏调节能力下降）"))
        else:
            f.append(("good", f"DFA α1={alpha1:.2f} 在健康参考范围内"))

    if qrs_stats:
        n_wide = qrs_stats.get("n_wide", 0)
        mean_ms = qrs_stats.get("mean_ms")
        if n_wide:
            f.append(("warn", f"发现 {n_wide} 次宽QRS（>120ms），可能是干扰或异位搏动，建议回看波形核对"))
        elif mean_ms:
            f.append(("good", f"平均QRS宽度 {mean_ms:.0f}ms，在正常范围（80~120ms）"))
    return f


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
    # ---- v1.3.0 新增（默认值保证旧用法不受影响） ----
    q_onset: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    s_off: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    qrs_ms: np.ndarray = field(default_factory=lambda: np.array([]))
    qrs_valid: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    qrs_stats: dict = field(default_factory=dict)    # mean_ms / n_wide / n_valid
    hr_series: dict = field(default_factory=dict)    # inst / m60 / m300 心率序列
    hr_spectral: Optional[float] = None              # 频谱峰值法心率（对照值）
    nonlinear: dict = field(default_factory=dict)    # sd1/sd2/alpha1/alpha2/sampen
    findings: list = field(default_factory=list)     # 白话解读 [(级别, 文本), ...]
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

    kt, kr = times[ok], rr[ok]   # 有效心跳的时间与间期
    base.time = time_domain(kr)
    base.sd1, base.sd2 = poincare(kr)
    base.freq = frequency_domain(kt, kr)

    # QRS 波群定位（对全部检出心跳做，与RR有效性无关）
    base.q_onset, base.s_off, base.qrs_ms, base.qrs_valid = delineate_qrs(x, peaks, fs)
    widths = base.qrs_ms[base.qrs_valid & ~np.isnan(base.qrs_ms)]
    base.qrs_stats = {
        "mean_ms": float(widths.mean()) if len(widths) else None,
        "n_wide": int(np.sum(widths > QRS_WIDE_MS)),
        "n_valid": int(len(widths)),
    }

    base.hr_series = hr_series(kt, kr)
    base.hr_spectral = spectral_hr(x, fs)
    base.time.update(extra_time_domain(kt, kr))

    a1, a2 = dfa(kr)
    base.nonlinear = {"sd1": base.sd1, "sd2": base.sd2,
                      "alpha1": a1, "alpha2": a2,
                      "sampen": sample_entropy(kr)}
    base.findings = interpret(base.time, base.freq, base.nonlinear,
                              base.qrs_stats, base.removed_ratio, base.duration_s)
    return base

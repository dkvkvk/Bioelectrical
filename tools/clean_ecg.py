"""离线验证：对上位机导出的心电数据做标准滤波，输出洗前/洗后对比图。

不改设备固件，纯粹在电脑上验证"洗杂波"能洗到什么程度。
滤波链：0.5Hz 高通(去基线漂移) + 50Hz 陷波(去工频) + 40Hz 低通(去高频毛刺)。
"""
import sys
import numpy as np
from scipy.signal import butter, filtfilt, iirnotch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FS = 500.0  # 采样率, sps


def load(path):
    rows = []
    for ln in open(path, encoding="utf-8", errors="ignore").read().splitlines():
        p = ln.split()
        if len(p) == 2:
            try:
                rows.append((float(p[0]), float(p[1])))
            except ValueError:
                pass
    return np.array(rows)


def clean(x, fs=FS):
    # 1) 去基线漂移: 0.5Hz 高通
    b, a = butter(2, 0.5 / (fs / 2), btype="high")
    y = filtfilt(b, a, x)
    # 2) 去 50Hz 工频
    b, a = iirnotch(50.0, 30.0, fs)
    y = filtfilt(b, a, y)
    # 3) 去高频毛刺: 40Hz 低通
    b, a = butter(4, 40.0 / (fs / 2), btype="low")
    y = filtfilt(b, a, y)
    return y


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "datafile.txt"
    out = sys.argv[2] if len(sys.argv) > 2 else "ecg_compare.png"
    d = load(src)
    raw = d[:, 0]
    cleaned = clean(raw)

    # 取中间一段 (8 秒) 看细节
    seg = slice(int(4 * FS), int(12 * FS))
    t = np.arange(len(raw))[seg] / FS

    fig, ax = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    ax[0].plot(t, raw[seg], color="red", lw=0.6)
    ax[0].set_title("Before (raw) - channel 1")
    ax[0].set_ylabel("V")
    ax[1].plot(t, cleaned[seg], color="green", lw=0.8)
    ax[1].set_title("After (filtered): 0.5Hz HP + 50Hz notch + 40Hz LP")
    ax[1].set_ylabel("V")
    ax[1].set_xlabel("time (s)")
    for a_ in ax:
        a_.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print("saved:", out)


if __name__ == "__main__":
    main()

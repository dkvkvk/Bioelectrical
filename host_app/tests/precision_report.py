"""精度验证报告：对分析引擎做系统性"体检"，人工复核用。

运行: python tests/precision_report.py
覆盖: R波检测(多随机种子/采样率/心率范围/噪声干扰/信号反转) →
QRS定位稳定性 → HRV指标对真值误差 → 频域波段方向 → 非线性指标
数学基准 → 滤波性能 → 大数据耗时 → 长时指标门槛。

模拟心电由 core/demo_source.py 生成，RR 序列是预设的"标准答案"，
所以每个指标都能和真值对账。
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from core.demo_source import make_rr_series, synthesize_ecg
from core import hrv

FS = 500.0
ROWS = []


def row(name, value, expect):
    ROWS.append((name, value, expect))


def sec(title):
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


# ---------------------------------------------------------------- A. R波检测

def r_wave_detection():
    sec("A. R波检测精度（Pan-Tompkins类，课件第8页指标）")

    # A1 多随机种子（10段各约5分钟）
    ses, ppvs, errs = [], [], []
    for seed in range(10):
        rr = make_rr_series(350, seed=seed)
        ecg, r_true = synthesize_ecg(rr, FS, seed=7 + seed)
        peaks = hrv.detect_r_peaks(hrv.clean_ecg(ecg, FS), FS)
        s = hrv.detection_scores(peaks, r_true, FS)
        ses.append(s["se"]); ppvs.append(s["ppv"]); errs.append(s["mean_err_ms"])
    row("10段随机数据 灵敏度Se", f"最小 {min(ses)*100:.2f}% / 平均 {np.mean(ses)*100:.2f}%", "≥99%")
    row("10段随机数据 阳性预测值PPV", f"最小 {min(ppvs)*100:.2f}%", "≥99%")
    row("10段随机数据 平均定位误差", f"最大 {max(errs):.2f} ms", "<5ms")

    # A2 不同采样率
    for fs in (250.0, 1000.0):
        rr = make_rr_series(350, seed=42)
        ecg, r_true = synthesize_ecg(rr, fs, seed=7)
        peaks = hrv.detect_r_peaks(hrv.clean_ecg(ecg, fs), fs)
        s = hrv.detection_scores(peaks, r_true, fs)
        row(f"采样率{fs:.0f}Hz Se/PPV/误差",
            f"{s['se']*100:.2f}% / {s['ppv']*100:.2f}% / {s['mean_err_ms']:.2f}ms",
            "≥99% / ≥99% / <5ms")

    # A3 心率范围（40~180bpm，带变异）
    for bpm in (40, 60, 90, 120, 150, 180):
        base = 60000.0 / bpm
        if base < 320:  # 接近生理下限时减小变异幅度
            lf, hf, nz = 4.0, 3.0, 2.0
        else:
            lf, hf, nz = 15.0, 10.0, 6.0
        rr = make_rr_series(int(300 * bpm / 60), base_ms=base,
                            lf_amp_ms=lf, hf_amp_ms=hf, noise_ms=nz, seed=3)
        ecg, r_true = synthesize_ecg(rr, FS, seed=7)
        peaks = hrv.detect_r_peaks(hrv.clean_ecg(ecg, FS), FS)
        s = hrv.detection_scores(peaks, r_true, FS)
        row(f"心率{bpm}bpm Se/PPV",
            f"{s['se']*100:.2f}% / {s['ppv']*100:.2f}%", "≥98% / ≥98%")

    # A4 噪声/干扰条件（默认: 白噪8mV 工频4mV 漂移30mV）
    conds = [
        ("白噪声×2 (16mV)", dict(noise_v=0.016)),
        ("白噪声×4 (32mV)", dict(noise_v=0.032)),
        ("工频50Hz×2 (8mV)", dict(mains_v=0.008)),
        ("基线漂移×2 (60mV)", dict(wander_v=0.06)),
        ("运动伪差3%心跳", dict(artifact_prob=0.03)),
        ("运动伪差8%心跳", dict(artifact_prob=0.08)),
        ("组合恶劣(噪×2+伪差5%)", dict(noise_v=0.016, artifact_prob=0.05)),
    ]
    for name, kw in conds:
        rr = make_rr_series(350, seed=42)
        ecg, r_true = synthesize_ecg(rr, FS, seed=7, **kw)
        peaks = hrv.detect_r_peaks(hrv.clean_ecg(ecg, FS), FS)
        s = hrv.detection_scores(peaks, r_true, FS)
        row(f"{name} Se/PPV", f"{s['se']*100:.2f}% / {s['ppv']*100:.2f}%",
            "≥95% / ≥95%")

    # A5 信号极性反转（R波向下）
    rr = make_rr_series(350, seed=42)
    ecg, r_true = synthesize_ecg(rr, FS, seed=7)
    peaks = hrv.detect_r_peaks(hrv.clean_ecg(-ecg, FS), FS)
    s = hrv.detection_scores(peaks, r_true, FS)
    row("信号反转(R波向下) Se", f"{s['se']*100:.2f}%", "≥98%")


# ---------------------------------------------------------------- B. QRS定位

def qrs_delineation():
    sec("B. QRS波群定位稳定性（课件第13页）")
    for name, kw in (("标准条件", {}), ("噪声×2", dict(noise_v=0.016)),
                     ("伪差3%", dict(artifact_prob=0.03))):
        rr = make_rr_series(350, seed=42)
        ecg, r_true = synthesize_ecg(rr, FS, seed=7, **kw)
        x = hrv.clean_ecg(ecg, FS)
        q, s, w, valid = hrv.delineate_qrs(x, r_true, FS)
        wv = w[valid]
        order_ok = np.all(q[valid] < r_true[valid]) and np.all(s[valid] > r_true[valid])
        row(f"{name} 有效定位率", f"{valid.mean()*100:.1f}%", "≥95%")
        row(f"{name} QRS宽度", f"{wv.mean():.0f}±{wv.std():.1f} ms (Q在R前/S在R后: {'是' if order_ok else '否'})",
            "宽度稳定、顺序正确")
    # 宽QRS误报：合成心电QRS全部正常，任何"宽QRS"判定都是误报
    for name, kw in (("标准条件宽QRS误报", {}), ("噪声×2宽QRS误报", dict(noise_v=0.016)),
                     ("伪差3%宽QRS误报", dict(artifact_prob=0.03))):
        rr = make_rr_series(350, seed=42)
        ecg, _ = synthesize_ecg(rr, FS, seed=7, **kw)
        res = hrv.analyze(ecg, FS)
        row(name, f"{res.qrs_stats['n_wide']} 次 / {res.qrs_stats['n_valid']} 拍",
            "0次")


# ---------------------------------------------------------------- C. HRV指标对真值

def hrv_vs_truth():
    sec("C. HRV指标与真值的偏差（分析整段含噪心电 vs 预设RR序列）")
    errs = {k: [] for k in ("mean_rr", "mean_hr", "sdnn", "rmssd", "sdsd", "cv")}
    pnn_err, hr_gap, spec_gap = [], [], []
    for seed in range(5):
        rr = make_rr_series(400, seed=100 + seed)
        ecg, _ = synthesize_ecg(rr, FS, seed=7)
        res = hrv.analyze(ecg, FS)
        assert res.error is None, res.error
        truth = hrv.time_domain(rr)
        for k in errs:
            errs[k].append(abs(res.time[k] - truth[k]) / truth[k] * 100)
        pnn_err.append(abs(res.time["pnn50"] - truth["pnn50"]))
        hr_gap.append(max(abs(res.time["hr_min"] - truth["hr_min"]),
                          abs(res.time["hr_max"] - truth["hr_max"])))
        spec_gap.append(abs(res.hr_spectral - res.time["mean_hr"]))
    for k, label in (("mean_rr", "平均RR间期"), ("mean_hr", "平均心率"),
                     ("sdnn", "SDNN"), ("rmssd", "RMSSD"),
                     ("sdsd", "SDSD"), ("cv", "变异系数CV")):
        row(f"{label} 相对误差", f"最大 {max(errs[k]):.2f}%", "<5%")
    row("pNN50 绝对偏差", f"最大 {max(pnn_err):.1f} 个百分点", "<3")
    row("最慢/最快心率 偏差", f"最大 {max(hr_gap):.1f} bpm", "<2")
    row("频域法心率 vs 逐拍法", f"最大差 {max(spec_gap):.1f} bpm", "<3")


# ---------------------------------------------------------------- D. 频域波段

def freq_bands():
    sec("D. 频域分析波段判断（已知调制 → 应落在正确波段）")
    for name, lf_a, hf_a in (("HF主导(0.25Hz呼吸调制)", 2.0, 25.0),
                             ("LF主导(0.1Hz血压调制)", 25.0, 2.0)):
        rr = make_rr_series(450, lf_amp_ms=lf_a, hf_amp_ms=hf_a, seed=5)
        t = np.cumsum(rr) / 1000.0
        out = hrv.frequency_domain(t, rr)
        ratio = out["hf"] / out["lf"] if name.startswith("HF") else out["lf"] / out["hf"]
        row(name, f"对应波段功率是另一波段的 {ratio:.1f} 倍", "≥3倍")


# ---------------------------------------------------------------- E. 非线性基准

def nonlinear():
    sec("E. 非线性指标数学基准")
    rng = np.random.default_rng(11)
    a1, _ = hrv.dfa(850 + rng.normal(0, 40, 2000))
    row("DFA α1: 白噪声", f"{a1:.3f}", "理论0.5±0.15")
    # 1/f 噪声（FFT造形）→ 理论 α≈1.0
    n = 4000
    f = np.fft.rfftfreq(n)
    spec = np.random.default_rng(3).standard_normal(n // 2 + 1) + 0j
    spec[1:] /= f[1:] ** 0.5 / f[1]
    frac = np.fft.irfft(np.abs(np.fft.rfft(
        np.random.default_rng(3).standard_normal(n)) * 0j + spec), n)
    a1f, _ = hrv.dfa(frac)
    row("DFA α1: 1/f噪声", f"{a1f:.3f}", "理论1.0±0.2")
    se_reg = hrv.sample_entropy(850 + 10 * np.sin(2 * np.pi * 0.1 * np.arange(800) * 0.85)
                                + np.random.default_rng(9).normal(0, 6, 800))
    se_rnd = hrv.sample_entropy(850 + np.random.default_rng(9).normal(0, 30, 800))
    row("样本熵: 规律 vs 随机", f"{se_reg:.3f} vs {se_rnd:.3f}", "规律<随机")
    sd1, sd2 = hrv.poincare(800 + rng.normal(0, 30, 3000))
    row("Poincaré: 纯随机SD1≈SD2", f"SD1={sd1:.1f} SD2={sd2:.1f}", "比值0.9~1.1")


# ---------------------------------------------------------------- F. 滤波性能

def filtering():
    sec("F. 滤波链性能（0.5Hz高通 + 50Hz陷波 + 40Hz低通）")
    t = np.arange(int(FS * 60)) / FS
    rng = np.random.default_rng(2)
    # 50Hz 工频抑制
    tone = 0.004 * np.sin(2 * np.pi * 50.0 * t)
    after = hrv.clean_ecg(tone, FS)
    gain_db = 20 * np.log10(np.sqrt(np.mean(after ** 2)) / np.sqrt(np.mean(tone ** 2)))
    row("50Hz工频抑制", f"{gain_db:.1f} dB", "≤-20dB(衰减90%以上)")
    # 基线漂移抑制（0.3Hz）
    wander = 0.03 * np.sin(2 * np.pi * 0.3 * t)
    after_w = hrv.clean_ecg(wander, FS)
    atten = 100 * (1 - np.sqrt(np.mean(after_w ** 2)) / 0.03 * np.sqrt(2))
    row("0.3Hz基线漂移衰减", f"{atten:.0f}%", "≥80%")
    # R波幅度保持
    rr = np.full(60, 850.0)
    ecg_clean, r_true = synthesize_ecg(rr, FS, r_amp_v=0.15, noise_v=0, mains_v=0, wander_v=0)
    x = hrv.clean_ecg(ecg_clean, FS)
    amp0 = np.median(ecg_clean[r_true])
    amp1 = np.median(x[r_true] - np.median(x))
    keep = amp1 / amp0 * 100
    row("R波幅度保持率", f"{keep:.1f}%", "85%~115%")


# ---------------------------------------------------------------- G. 耗时与长时指标

def performance():
    sec("G. 大数据分析耗时与长时指标门槛")
    for minutes in (5, 30, 120):
        rr = make_rr_series(int(minutes * 60 * 70 / 60) + 10)
        ecg, _ = synthesize_ecg(rr, FS, seed=1)
        t0 = time.perf_counter()
        res = hrv.analyze(ecg, FS)
        dt = time.perf_counter() - t0
        assert res.error is None
        row(f"{minutes}分钟数据 analyze() 耗时", f"{dt:.2f} s", "秒级")
    rr12 = make_rr_series(int(12 * 60 * 70 / 60), seed=6)   # 12分钟
    ecg, _ = synthesize_ecg(rr12, FS, seed=1)
    res = hrv.analyze(ecg, FS)
    t = res.time
    row("12分钟: SDANN/SDNN指数/三角指数",
        f"{t['sdann']:.1f} / {t['sdnn_index']:.1f} / {t['tri_index']:.1f}",
        "均为数值(非None)")


def main():
    t0 = time.perf_counter()
    r_wave_detection()
    qrs_delineation()
    hrv_vs_truth()
    freq_bands()
    nonlinear()
    filtering()
    performance()
    print(f"\n{'=' * 64}\n汇总\n{'=' * 64}")
    for name, value, expect in ROWS:
        print(f"  {name:32s} {value:38s} （期望 {expect}）")
    print(f"\n共 {len(ROWS)} 项，总耗时 {time.perf_counter()-t0:.1f} 秒")


if __name__ == "__main__":
    main()

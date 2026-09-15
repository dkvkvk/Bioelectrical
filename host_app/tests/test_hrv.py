"""HRV 分析引擎测试：用"已知答案"的模拟心电验证每个环节。

模拟信号由 core/demo_source.py 生成，其中 RR 序列是预先设定的，
所以各项指标的正确答案可以直接从 RR 序列算出来对照。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.demo_source import DemoSource, make_rr_series, synthesize_ecg  # noqa: E402
from core.hrv import (  # noqa: E402
    analyze, clean_ecg, clean_rr, detect_r_peaks, frequency_domain,
    poincare, time_domain,
)

FS = 500.0


def _make(minutes=5.0, seed=42):
    n_beats = int(minutes * 60.0 * 70.0)
    rr = make_rr_series(n_beats, seed=seed)
    ecg, r_idx = synthesize_ecg(rr, FS, seed=7)
    return rr, ecg, r_idx


def test_r_peak_accuracy():
    """R 波定位：检出率 ≥99%，平均时间误差 <2ms。"""
    rr, ecg, r_true = _make()
    peaks = detect_r_peaks(clean_ecg(ecg, FS), FS)
    assert len(peaks) >= 0.98 * len(r_true), \
        f"检出过少: {len(peaks)}/{len(r_true)}"

    tol = int(0.025 * FS)  # 25ms 内算匹配
    used = set()
    matched_true = []
    errs_ms = []
    for r in r_true:
        for p in peaks:
            if p not in used and abs(int(p) - int(r)) <= tol:
                used.add(int(p))
                matched_true.append(r)
                errs_ms.append(abs(int(p) - int(r)) / FS * 1000.0)
                break
    rate = len(matched_true) / len(r_true)
    assert rate >= 0.99, f"匹配率过低: {rate:.3f}"
    mean_err = float(np.mean(errs_ms))
    assert mean_err < 2.0, f"平均定位误差过大: {mean_err:.2f}ms"


def test_time_domain_vs_truth():
    """时域指标应接近按真实 RR 序列算出的答案（误差 <5%）。"""
    rr, ecg, _ = _make()
    res = analyze(ecg, FS)
    assert res.error is None, res.error
    truth = time_domain(rr)
    for key in ("mean_rr", "sdnn", "rmssd"):
        got = res.time[key]
        want = truth[key]
        assert abs(got - want) / want < 0.05, \
            f"{key}: 分析={got:.2f} 真值={want:.2f}"
    # pNN50 量级一致（允许 3 个百分点差异）
    assert abs(res.time["pnn50"] - truth["pnn50"]) < 3.0


def test_poincare_identity():
    """SD1 = SDSD/√2 的数学关系；纯随机序列 SD1≈SD2，真实心率有记忆性时 SD1<SD2。"""
    rng = np.random.default_rng(3)
    rr = 800 + rng.normal(0, 30, 3000)
    sd1, sd2 = poincare(rr)
    sdsd = np.diff(rr).std(ddof=1)
    assert abs(sd1 - sdsd / np.sqrt(2)) < 1e-6
    assert 0 < sd1 and sd1 <= sd2 * 1.10
    # 带低频调制的序列（更接近真实心率）应有 SD1 < SD2
    t = np.arange(600)
    rr2 = 800 + 25 * np.sin(2 * np.pi * 0.1 * t * 0.8) + rng.normal(0, 8, 600)
    s1, s2 = poincare(rr2)
    assert s1 < s2


def test_clean_rr_removes_artifacts():
    """伪差剔除：短毛刺/倍长间期/超出生理范围都应被剔除。"""
    rr = np.full(100, 800.0)
    rr[20] = 80.0     # 毛刺短间期（超出生理范围）
    rr[50] = 1600.0   # 漏检造成的倍长间期（范围内但相邻偏差>20%）
    rr[70] = 200.0    # 超下限
    rr[85] = 2200.0   # 超上限
    ok = clean_rr(rr)
    for i in (20, 50, 70, 85):
        assert not ok[i], f"伪差 {i} 未被剔除"
    assert ok.sum() == 96


def test_frequency_domain_bands():
    """只有 0.25Hz 高频调制的 RR → HF 功率应明显大于 LF。"""
    t_end = 300.0
    beat_t = np.arange(0.5, t_end, 0.8)     # 约 75bpm
    rr = 800 + 20.0 * np.sin(2 * np.pi * 0.25 * beat_t)
    out = frequency_domain(beat_t, rr)
    assert out is not None
    assert out["hf"] > 3 * out["lf"], \
        f"HF={out['hf']:.1f} 应明显大于 LF={out['lf']:.1f}"
    assert out["tp"] >= out["vlf"] + out["lf"] + out["hf"] * 0.9

    # 不足 2 分钟 → 不计算
    short = frequency_domain(beat_t[:60], rr[:60])
    assert short is None


def test_analyze_guards():
    """数据太短/信号全平 应给出中文错误而不是崩溃。"""
    res = analyze(np.zeros(int(FS * 10)), FS)
    assert res.error is not None
    res2 = analyze(np.zeros(int(FS * 60)), FS)
    assert res2.error is not None


def test_full_pipeline_on_demo_signal():
    """端到端：合成 5 分钟含伪差心电 → analyze 正常出全部指标。"""
    rr, ecg, _ = _make(minutes=5.0, seed=11)
    ecg_noisy = ecg.copy()
    rng = np.random.default_rng(5)
    for _ in range(3):  # 插入几段运动伪差
        a = int(rng.integers(1000, len(ecg_noisy) - 2000))
        ecg_noisy[a:a + 400] += 0.5 * rng.standard_normal(400)
    res = analyze(ecg_noisy, FS)
    assert res.error is None, res.error
    assert res.time["n_beats"] > 300
    assert res.removed_ratio < 0.10, "伪差比例异常偏高"
    assert res.freq is not None and res.freq["tp"] > 0
    assert np.isfinite(res.sd1) and res.sd1 > 0


def test_demo_source_batches():
    """演示信号源输出格式与帧解析结果一致。"""
    demo = DemoSource(seed=1)
    batches = demo.next_batches(20)
    assert len(batches) == 5
    for b in batches:
        assert len(b["ch1"]) == 4 and len(b["ch2"]) == 4
        assert 0.5 < b["ch1"][0] < 2.0
        assert 55 <= b["heart_rate"] <= 100
        assert b["lead_off"] == 0
    assert demo.next_batches(3)[0]["ch1"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_hrv 全部通过")

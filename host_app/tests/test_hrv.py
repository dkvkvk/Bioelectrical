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
    analyze, clean_ecg, clean_rr, delineate_qrs, detect_r_peaks,
    detection_scores, dfa, extra_time_domain, frequency_domain, hr_series,
    interpret, poincare, sample_entropy, spectral_hr, time_domain,
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


# ================= v1.3.0 新增功能 =================

def test_detection_scores_metrics():
    """检测性能指标（课件第8页）：Se/PPV/F1 ≥99%，平均误差 <5ms。"""
    rr, ecg, r_true = _make()
    peaks = detect_r_peaks(clean_ecg(ecg, FS), FS)
    s = detection_scores(peaks, r_true, FS, tol_ms=75.0)
    assert s["se"] >= 0.99, f"灵敏度 {s['se']:.4f}"
    assert s["ppv"] >= 0.99, f"阳性预测值 {s['ppv']:.4f}"
    assert s["f1"] >= 0.99, f"F1 {s['f1']:.4f}"
    assert s["mean_err_ms"] < 5.0, f"平均误差 {s['mean_err_ms']:.2f}ms"


def test_qrs_delineation():
    """QRS定位（课件第13页）：Q在R前、S在R后，宽度合理且逐拍稳定。"""
    rr, ecg, r_true = _make(minutes=2.0)
    x = clean_ecg(ecg, FS)
    q, s, widths, valid = delineate_qrs(x, r_true, FS)
    n = len(r_true)
    assert valid.sum() >= 0.95 * n, f"有效定位比例过低: {valid.sum()}/{n}"
    w = widths[valid]
    assert np.all(q[valid] < r_true[valid]) and np.all(s[valid] > r_true[valid]), \
        "Q/S 相对 R 波的位置不对"
    assert 40.0 <= w.mean() <= 150.0, f"平均QRS宽度异常: {w.mean():.1f}ms"
    assert w.std() < 20.0, f"QRS宽度逐拍波动过大: {w.std():.1f}ms"
    # Q/S 不越过搜索窗（Q 最远 R 前150ms，S 最远 R 后300ms）
    assert np.all(r_true[valid] - q[valid] <= 0.15 * FS + 2)
    assert np.all(s[valid] - r_true[valid] <= 0.30 * FS + 2)
    # 空输入不崩溃
    q0, s0, w0, v0 = delineate_qrs(x, [], FS)
    assert len(q0) == 0 and not v0.any()


def test_dfa_white_noise():
    """DFA（课件第17页）：不相关的白噪声序列 α≈0.5。"""
    rng = np.random.default_rng(2)
    rr = 850.0 + rng.normal(0.0, 40.0, 2000)
    a1, a2 = dfa(rr)
    assert a1 is not None and abs(a1 - 0.5) < 0.15, f"白噪声 α1={a1}"
    assert a2 is not None and abs(a2 - 0.5) < 0.20, f"白噪声 α2={a2}"
    # 拍数不足 → None
    a1s, _ = dfa(rr[:50])
    assert a1s is None


def test_sample_entropy_ordering():
    """样本熵：规律序列熵低，随机序列熵高。"""
    rng = np.random.default_rng(9)
    t = np.arange(800)
    rr_regular = 850 + 10 * np.sin(2 * np.pi * 0.1 * t * 0.85) + rng.normal(0, 6, 800)
    rr_random = 850 + rng.normal(0, 30, 800)
    se_r = sample_entropy(rr_regular)
    se_n = sample_entropy(rr_random)
    assert se_r is not None and se_n is not None
    assert se_n > se_r, f"随机序列熵应更高: 规律={se_r:.3f} 随机={se_n:.3f}"
    assert sample_entropy(rr_regular[:100]) is None  # 拍数不足


def test_hr_series():
    """心率序列（课件第9~12页）：恒定RR→逐拍心率恒定；滑动平均正确。"""
    rr = np.full(120, 800.0)                      # 75 bpm
    t = np.cumsum(rr) / 1000.0
    hs = hr_series(t, rr)
    assert np.allclose(hs["inst"], 75.0)
    assert np.isnan(hs["m60"][0])                 # 开头窗口内心跳不足
    assert abs(hs["m60"][10] - 75.0) < 1e-9
    assert abs(hs["m300"][10] - 75.0) < 1e-9
    # 变心率：第81拍起 RR 变 600ms（100bpm），1分钟均值应逐步下移
    rr2 = np.concatenate([np.full(80, 800.0), np.full(80, 600.0)])
    t2 = np.cumsum(rr2) / 1000.0
    hs2 = hr_series(t2, rr2)
    assert hs2["inst"][100] > 95.0                    # 后段逐拍心率 ≈100
    assert 75.0 < hs2["m60"][100] < hs2["inst"][100]  # 混合窗口均值介于两者之间
    assert hs2["m60"][159] > hs2["m60"][100]          # 快心跳占比升高，均值心率上升


def test_spectral_hr():
    """频谱峰值法心率（课件第10页）：与逐拍法对账（±3bpm）。"""
    rr = np.full(300, 850.0)                      # 70.6 bpm
    ecg, _ = synthesize_ecg(rr, FS, seed=3)
    hr = spectral_hr(clean_ecg(ecg, FS), FS)
    beat_hr = 60000.0 / 850.0
    assert hr is not None and abs(hr - beat_hr) < 3.0, f"频谱法={hr} 逐拍法={beat_hr}"
    assert spectral_hr(np.zeros(int(FS * 5)), FS) is None  # 数据太短


def test_extra_time_domain_gating():
    """SDANN/SDNN指数/三角指数（课件第14页）：5分钟数据不给，≥10分钟给。"""
    t_end = 300.0
    t5 = np.arange(0.8, t_end, 0.85)
    rr5 = 850.0 + np.random.default_rng(4).normal(0, 20, len(t5))
    out5 = extra_time_domain(t5, rr5)
    assert out5["sdann"] is None and out5["sdnn_index"] is None and out5["tri_index"] is None

    t11 = np.arange(0.8, 660.0, 0.85)
    rr11 = 850.0 + np.random.default_rng(4).normal(0, 20, len(t11))
    out11 = extra_time_domain(t11, rr11)
    assert out11["sdann"] is not None and out11["sdann"] > 0
    assert out11["sdnn_index"] is not None and out11["sdnn_index"] > 0
    assert out11["tri_index"] is not None and out11["tri_index"] > 1.0


def test_interpret_findings():
    """白话解读（课件第18页）：低HRV数据应出现警示条目，正常数据有正面条目。"""
    rng = np.random.default_rng(6)
    rr_low = 800.0 + rng.normal(0, 5, 400)        # SDNN≈5ms，明显偏低
    f_low = interpret(time_domain(rr_low), None, {"alpha1": 0.7}, None, 0.0, 300.0)
    levels_low = [lv for lv, _ in f_low]
    assert "alert" in levels_low or "warn" in levels_low
    assert any("偏低" in txt for _, txt in f_low)

    rr_ok = make_rr_series(400, seed=8)           # 正常变异的合成序列
    f_ok = interpret(time_domain(rr_ok), None, {"alpha1": 1.05}, None, 0.0, 300.0)
    assert any(lv == "good" for lv, _ in f_ok), f_ok


def test_analyze_new_fields():
    """端到端：analyze 结果包含 v1.3.0 新字段且类型正确。"""
    rr, ecg, _ = _make(minutes=3.0)
    res = analyze(ecg, FS)
    assert res.error is None, res.error
    assert res.qrs_stats and res.qrs_stats["n_valid"] > 0
    assert len(res.q_onset) == len(res.r_peaks) == len(res.qrs_ms)
    assert res.hr_series and "inst" in res.hr_series and "m60" in res.hr_series
    assert res.hr_spectral is not None and 40 < res.hr_spectral < 150
    assert res.nonlinear["alpha1"] is not None
    assert res.nonlinear["sampen"] is not None and res.nonlinear["sampen"] > 0
    assert res.findings, "解读列表不应为空"
    assert res.time["hr_min"] < res.time["hr_max"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_hrv 全部通过")

"""分析结果窗口：6 张图 + 指标表（含参考范围）+ 白话解读 + 一键导出。

v1.3.0 按课件第7章前四部分扩充：QRS波群定位标记、心率趋势图
（逐拍/1分钟/5分钟）、RR直方图、SDANN/SDNN指数/三角指数、
DFA α1/α2 与样本熵、规则化解读。
"""

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)
from core import recorder as rec
from core.hrv import QRS_WIDE_MS, HrvResult, analyze
from core.theme import (
    ACCENT, DANGER, INK, LINE, MARK_R, MUTED, RR_LINE, SUCCESS, WARNING,
    WAVE_CH2, PlotHint, mono_font, pathtag,
)

Q_MARK = MUTED        # Q 点标记色
S_MARK = WAVE_CH2     # S 点标记色

# 指标定义: (结果键, 显示名+单位, 参考范围, 含义)。参考范围来自课件第7章。
_METRIC_ROWS = [
    ("", "—— 基本信息 ——", "", ""),
    ("duration_s", "录制时长 (秒)", "—", "本次录制的数据长度"),
    ("fs", "采样率 (Hz)", "—", "每秒采集的数据点数"),
    ("n_detected", "检出心跳数 (次)", "—", "算法在波形中识别出的全部心跳"),
    ("n_kept", "有效心跳数 (次)", "—", "通过质量把关、用于计算指标的心跳"),
    ("removed_pct", "剔除比例 (%)", "越低越好", "被判定为伪差而剔除的心跳间隔占比"),
    ("hr_spectral", "心率·频域法 (bpm)", "—", "从波形周期性推算的心率，与逐拍法互相印证"),
    ("hr_min", "最慢心率 (bpm)", "—", "按最长RR间期折算的心率"),
    ("hr_max", "最快心率 (bpm)", "—", "按最短RR间期折算的心率"),
    ("qrs_mean", "平均QRS宽度 (ms)", "80~120", "每次心跳电激动扫过心室的时长，宽QRS提示传导异常"),
    ("qrs_wide", "宽QRS次数 (次)", "0", f"QRS宽度超过{QRS_WIDE_MS:.0f}ms的心跳次数"),
    ("", "—— 时域指标 ——", "", ""),
    ("mean_hr", "平均心率 (bpm)", "60~100", "每分钟平均心跳次数（时间加权标准算法）"),
    ("mean_rr", "平均RR间期 (ms)", "600~1000", "相邻心跳的平均时间间隔"),
    ("sdnn", "SDNN (ms)", "102~180", "全部心跳间隔的标准差，反映整体变异"),
    ("sdann", "SDANN (ms)", "92~162", "每5分钟平均RR的标准差，长时程变异（需≥10分钟数据）"),
    ("sdnn_index", "SDNN指数 (ms)", "72~118", "每5分钟SDNN的平均，短时程变异（需≥10分钟数据）"),
    ("tri_index", "HRV三角指数", "21~43", "RR直方图总次数÷最高一栏次数（需≥10分钟数据）"),
    ("rmssd", "RMSSD (ms)", "19~56", "相邻心跳间隔差异的均方根，反映短期变异（副交感）"),
    ("pnn50", "pNN50 (%)", "2~24", "相邻间隔相差超过50毫秒的比例（副交感）"),
    ("sdsd", "SDSD (ms)", "19~56", "相邻间隔差值的标准差"),
    ("cv", "变异系数 CV (%)", "—", "SDNN 相对平均RR 的百分比"),
    ("", "—— 非线性指标 ——", "", ""),
    ("sd1", "SD1 (ms)", "—", "散点图短轴，反映短期变异（副交感）"),
    ("sd2", "SD2 (ms)", "—", "散点图长轴，反映长期变异"),
    ("alpha1", "DFA α1", "≈1.0", "短期复杂度：健康心脏≈1.0，<0.75提示调节能力下降"),
    ("alpha2", "DFA α2", "—", "长期复杂度（需要更长的录制才可靠）"),
    ("sampen", "样本熵", "—", "心跳间隔复杂度：越规律越低；个体差异大，宜自身前后对比"),
    ("", "—— 频域指标 ——", "", ""),
    ("vlf", "VLF 极低频功率 (ms²)", "—", "0.003–0.04Hz，慢调节波段"),
    ("lf", "LF 低频功率 (ms²)", "—", "0.04–0.15Hz，交感+副交感共同作用"),
    ("hf", "HF 高频功率 (ms²)", "—", "0.15–0.4Hz，主要反映副交感/呼吸"),
    ("tp", "总功率 TP (ms²)", "—", "0–0.4Hz 全部功率之和"),
    ("lf_hf", "LF/HF 比值", "1.5~2.0", "低频与高频功率之比，交感-副交感平衡"),
    ("lfnu", "LF 归一化 (nu)", "—", "LF 占 (LF+HF) 的百分比"),
    ("hfnu", "HF 归一化 (nu)", "—", "HF 占 (LF+HF) 的百分比"),
]

_LEVEL_COLORS = {"good": SUCCESS, "info": MUTED, "warn": WARNING, "alert": DANGER}


def _fmt(v, nd: int = 1) -> str:
    """数值格式化：None/NaN → '—'（数据不足不算错，界面上明示）。"""
    if v is None or v != v:
        return "—"
    return f"{v:.{nd}f}"


class AnalysisWindow(QMainWindow):
    def __init__(self, session_folder, parent=None) -> None:
        super().__init__(parent)
        self.folder = Path(session_folder)
        self.setWindowTitle(f"HRV 分析 — {self.folder.name}")
        self.resize(1560, 900)
        self.result: HrvResult | None = None

        session = rec.load_session(self.folder)
        self.data = session
        self.ch1 = session["ch1"]
        self.fs = session["fs"]

        self._build_ui()

    # ================================================================ 界面

    def _build_ui(self) -> None:
        pg.setConfigOptions(antialias=False, background="#FFFFFF",
                            foreground="#14171C")
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- 左侧 2×3 图 ----
        left = QVBoxLayout()
        strip_bar = QHBoxLayout()
        strip_bar.addWidget(pathtag("HRV / ANALYSIS"))
        strip_bar.addWidget(QLabel("心电片段:"))
        self.cmb_strip = QComboBox()
        self.cmb_strip.addItems(["开头 10 秒", "中间 10 秒", "结尾 10 秒", "全部波形"])
        self.cmb_strip.setCurrentIndex(1)
        self.cmb_strip.currentIndexChanged.connect(self.draw_ecg_strip)
        strip_bar.addWidget(self.cmb_strip)
        strip_bar.addWidget(QLabel("（鼠标拖动平移、滚轮缩放）"))
        self.btn_reset_view = QPushButton("重置视图")
        self.btn_reset_view.setToolTip("六张图都恢复到默认显示")
        self.btn_reset_view.clicked.connect(self.reset_views)
        strip_bar.addWidget(self.btn_reset_view)
        strip_bar.addStretch(1)
        left.addLayout(strip_bar)

        grid = QGridLayout()
        self.plot_ecg = pg.PlotWidget(title="心电波形与QRS定位（Q·R·S）")
        self.plot_rr = pg.PlotWidget(title="心跳间隔曲线（RR间期）")
        self.plot_hr = pg.PlotWidget(title="心率趋势（逐拍/1分钟/5分钟）")
        self.plot_psd = pg.PlotWidget(title="心率变异频谱（功率谱密度）")
        self.plot_poin = pg.PlotWidget(title="Poincaré 散点图")
        self.plot_hist = pg.PlotWidget(title="RR间期分布直方图")
        for p in (self.plot_ecg, self.plot_rr, self.plot_hr,
                  self.plot_psd, self.plot_poin, self.plot_hist):
            p.showGrid(x=True, y=True, alpha=0.18)
            p.getAxis("bottom").setPen(LINE)
            p.getAxis("left").setPen(LINE)
        self.psd_hint = PlotHint(
            "数据不足2分钟，未计算频域指标\n（标准短时HRV分析建议录制5分钟）",
            self.plot_psd, point_size=10)
        self.psd_hint.hide()
        self.legend_ecg = self.plot_ecg.addLegend(offset=(10, 10), labelTextSize="8pt")
        self.legend_hr = self.plot_hr.addLegend(offset=(10, 10), labelTextSize="8pt")
        grid.addWidget(self.plot_ecg, 0, 0)
        grid.addWidget(self.plot_rr, 0, 1)
        grid.addWidget(self.plot_hr, 0, 2)
        grid.addWidget(self.plot_psd, 1, 0)
        grid.addWidget(self.plot_poin, 1, 1)
        grid.addWidget(self.plot_hist, 1, 2)
        left.addLayout(grid, stretch=1)
        root.addLayout(left, stretch=5)

        # ---- 右侧 解读 + 指标表 ----
        right = QVBoxLayout()

        box_read = QGroupBox("白话解读（参考提示，非医疗诊断）")
        read_layout = QVBoxLayout(box_read)
        self.lbl_findings = QLabel("尚未分析")
        self.lbl_findings.setProperty("muted", True)
        self.lbl_findings.setWordWrap(True)
        read_layout.addWidget(self.lbl_findings)
        right.addWidget(box_read)

        box = QGroupBox("分析指标")
        box_layout = QVBoxLayout(box)
        self.lbl_summary = QLabel("尚未分析")
        self.lbl_summary.setProperty("muted", True)
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setFont(mono_font())
        self.table = QTableWidget(len(_METRIC_ROWS), 4)
        self.table.setHorizontalHeaderLabels(["指标", "数值", "参考范围", "含义"])
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 175)
        self.table.setColumnWidth(1, 95)
        self.table.setColumnWidth(2, 95)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.lbl_ref_note = QLabel(
            "注：参考范围多来自24小时动态心电标准；短时录制（约5分钟）的数值通常偏低，"
            "重点看趋势变化和上方解读。")
        self.lbl_ref_note.setProperty("muted", True)
        self.lbl_ref_note.setWordWrap(True)
        box_layout.addWidget(self.lbl_summary)
        box_layout.addWidget(self.table)
        box_layout.addWidget(self.lbl_ref_note)
        right.addWidget(box, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("导出全部结果到录制文件夹")
        self.btn_export.setProperty("variant", "primary")
        self.btn_export.clicked.connect(self.export_results)
        self.btn_export.setEnabled(False)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_export)
        btn_row.addWidget(btn_close)
        right.addLayout(btn_row)
        root.addLayout(right, stretch=2)

    # ================================================================ 分析

    def run_analysis(self) -> None:
        """同步执行分析（数据量在分钟级时耗时不到1秒）。"""
        try:
            result = analyze(self.ch1, self.fs)
        except Exception as exc:
            QMessageBox.critical(self, "分析失败", f"分析过程出错：{exc}")
            self.lbl_summary.setText("分析失败：" + str(exc))
            return
        self.result = result
        if result.error:
            QMessageBox.warning(self, "无法完成分析", result.error)
            self.lbl_summary.setText(result.error)
            # 仍然画能画的部分（比如只看波形）
            if len(result.ecg_clean):
                self.draw_ecg_strip()
            return

        self.lbl_summary.setText(
            f"录制 {result.duration_s/60:.1f} 分钟 · 采样率 {self.fs:.0f}Hz · "
            f"检出心跳 {len(result.r_peaks)} 次 · 有效 {int(result.rr_ok_mask.sum())} 次 · "
            f"剔除 {result.removed_ratio*100:.1f}%"
            + ("" if result.freq else " · 数据不足2分钟，未计算频域指标（建议录满5分钟）"))
        self.fill_findings()
        self.fill_table()
        self.draw_ecg_strip()
        self.draw_rr()
        self.draw_hr()
        self.draw_psd()
        self.draw_poincare()
        self.draw_hist()
        self.btn_export.setEnabled(True)

    # ================================================================ 解读

    def fill_findings(self) -> None:
        """把引擎输出的规则化解读渲染成带状态色的白话条目。"""
        r = self.result
        parts = []
        for lv, txt in (r.findings if r else []):
            c = _LEVEL_COLORS.get(lv, INK)
            parts.append(f'<div style="color:{c};margin:1px 0;">● {txt}</div>')
        if not parts:
            parts.append(f'<div style="color:{MUTED};">本次未生成解读条目</div>')
        parts.append(f'<div style="color:{MUTED};font-size:8pt;margin-top:4px;">'
                     f'以上为基于公开人群统计的规则化提示，不构成医疗诊断。</div>')
        self.lbl_findings.setText("".join(parts))

    # ================================================================ 指标表

    def fill_table(self) -> None:
        r = self.result
        f = r.freq or {}
        q = r.qrs_stats or {}
        nl = r.nonlinear or {}
        values = {
            "duration_s": (f"{r.duration_s:.0f}"),
            "fs": (f"{r.fs:.0f}"),
            "n_detected": (f"{len(r.r_peaks)}"),
            "n_kept": (f"{int(r.rr_ok_mask.sum())}"),
            "removed_pct": (f"{r.removed_ratio*100:.1f}"),
            "hr_spectral": _fmt(r.hr_spectral),
            "hr_min": _fmt(r.time.get("hr_min")),
            "hr_max": _fmt(r.time.get("hr_max")),
            "qrs_mean": _fmt(q.get("mean_ms"), 0),
            "qrs_wide": (str(q.get("n_wide")) if q else "—"),
            "mean_hr": (f"{r.time['mean_hr']:.1f}"),
            "mean_rr": (f"{r.time['mean_rr']:.1f}"),
            "sdnn": (f"{r.time['sdnn']:.1f}"),
            "sdann": _fmt(r.time.get("sdann")),
            "sdnn_index": _fmt(r.time.get("sdnn_index")),
            "tri_index": _fmt(r.time.get("tri_index")),
            "rmssd": (f"{r.time['rmssd']:.1f}"),
            "pnn50": (f"{r.time['pnn50']:.1f}"),
            "sdsd": (f"{r.time['sdsd']:.1f}"),
            "cv": (f"{r.time['cv']:.1f}"),
            "sd1": (f"{r.sd1:.1f}"),
            "sd2": (f"{r.sd2:.1f}"),
            "alpha1": _fmt(nl.get("alpha1"), 2),
            "alpha2": _fmt(nl.get("alpha2"), 2),
            "sampen": _fmt(nl.get("sampen"), 2),
            "vlf": (f"{f.get('vlf', float('nan')):.1f}" if r.freq else "—"),
            "lf": (f"{f.get('lf', float('nan')):.1f}" if r.freq else "—"),
            "hf": (f"{f.get('hf', float('nan')):.1f}" if r.freq else "—"),
            "tp": (f"{f.get('tp', float('nan')):.1f}" if r.freq else "—"),
            "lf_hf": (f"{f.get('lf_hf', float('nan')):.2f}" if r.freq else "—"),
            "lfnu": (f"{f.get('lfnu', float('nan')):.1f}" if r.freq else "—"),
            "hfnu": (f"{f.get('hfnu', float('nan')):.1f}" if r.freq else "—"),
        }
        for row, (key, name, ref, desc) in enumerate(_METRIC_ROWS):
            is_section = key == ""
            item_name = QTableWidgetItem(name)
            item_val = QTableWidgetItem(values.get(key, "") if not is_section else "")
            item_ref = QTableWidgetItem(ref if not is_section else "")
            item_desc = QTableWidgetItem(desc)
            item_desc.setForeground(QColor(MUTED))
            item_ref.setForeground(QColor(MUTED))
            if is_section:
                item_name.setForeground(QColor(ACCENT))
                font = item_name.font()
                font.setBold(True)
                item_name.setFont(font)
            else:
                item_val.setFont(mono_font())
            item_val.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_ref.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_val)
            self.table.setItem(row, 2, item_ref)
            self.table.setItem(row, 3, item_desc)
        self.table.resizeRowsToContents()

    # ================================================================ 绘图

    def draw_ecg_strip(self) -> None:
        """画全程心电 + Q/R/S 定位标记；下拉框只是快速跳转视野，之后可自由拖动缩放。

        视野范围全部显式计算后设定（不用 autoRange/enableAutoRange——
        与手工 setXRange 混用时偶发刻度不刷新，时间数字会消失）。
        """
        r = self.result
        self.plot_ecg.clear()
        self.legend_ecg.clear()
        if r is None or len(r.ecg_clean) == 0:
            return
        x = np.arange(len(r.ecg_clean)) / r.fs
        self.plot_ecg.plot(x, r.ecg_clean,
                           pen=pg.mkPen(ACCENT, width=1))
        peaks = r.r_peaks
        if len(peaks):
            wide = r.qrs_wide if len(r.qrs_wide) == len(peaks) else np.zeros(len(peaks), dtype=bool)
            normal = ~wide
            t_peaks = peaks / r.fs
            if normal.any():
                self.plot_ecg.plot(
                    t_peaks[normal], r.ecg_clean[peaks[normal]],
                    pen=None, symbol="t", symbolSize=10,
                    symbolBrush=MARK_R, symbolPen=None, name="R波")
            if wide.any():
                self.plot_ecg.plot(
                    t_peaks[wide], r.ecg_clean[peaks[wide]],
                    pen=None, symbol="d", symbolSize=14,
                    symbolBrush=DANGER, symbolPen=None,
                    name=f"宽QRS(>{QRS_WIDE_MS:.0f}ms)")
            q_ok = r.q_onset > 0
            if q_ok.any():
                self.plot_ecg.plot(
                    r.q_onset[q_ok] / r.fs, r.ecg_clean[r.q_onset[q_ok]],
                    pen=None, symbol="o", symbolSize=5,
                    symbolBrush=Q_MARK, symbolPen=None, name="Q点")
            s_ok = r.s_off > 0
            if s_ok.any():
                self.plot_ecg.plot(
                    r.s_off[s_ok] / r.fs, r.ecg_clean[r.s_off[s_ok]],
                    pen=None, symbol="s", symbolSize=5,
                    symbolBrush=S_MARK, symbolPen=None, name="S点")
        self.plot_ecg.setLabel("bottom", "时间", units="s")
        self.plot_ecg.setLabel("left", "电压", units="V")

        choice = max(0, self.cmb_strip.currentIndex())
        dur = float(x[-1])
        if choice == 3:  # 全部
            x0, x1 = 0.0, dur
        else:
            pos = (0.0, 0.45, 0.9)[choice]
            center = pos * dur
            x0, x1 = max(0.0, center - 5.0), min(dur, center + 5.0)
        i0 = max(0, int(x0 * r.fs))
        i1 = min(len(r.ecg_clean), int(x1 * r.fs) + 1)
        seg = r.ecg_clean[i0:i1]
        if len(seg) == 0:
            return
        ymin, ymax = float(seg.min()), float(seg.max())
        pad = (ymax - ymin) * 0.1 or 1e-4
        self.plot_ecg.setXRange(x0, x1, padding=0)
        self.plot_ecg.setYRange(ymin - pad, ymax + pad, padding=0)

    def reset_views(self) -> None:
        """六张图全部恢复默认显示（心电图回到当前下拉框选的片段视野）。"""
        self.draw_ecg_strip()
        for p in (self.plot_rr, self.plot_hr, self.plot_psd,
                  self.plot_poin, self.plot_hist):
            p.autoRange()

    def draw_rr(self) -> None:
        r = self.result
        self.plot_rr.clear()
        if r is None or len(r.rr_ms) == 0:
            return
        ok = r.rr_ok_mask
        self.plot_rr.plot(r.rr_times_s[ok], r.rr_ms[ok],
                          pen=pg.mkPen(RR_LINE, width=1),
                          symbol="o", symbolSize=3,
                          symbolBrush=RR_LINE, symbolPen=None)
        if (~ok).any():
            self.plot_rr.plot(r.rr_times_s[~ok], r.rr_ms[~ok],
                              pen=None, symbol="x", symbolSize=9,
                              symbolBrush=DANGER, symbolPen=DANGER)
        self.plot_rr.setLabel("bottom", "时间", units="s")
        self.plot_rr.setLabel("left", "RR间期", units="ms")

    def draw_hr(self) -> None:
        """心率趋势：逐拍瞬时心率（淡点）+ 1分钟/5分钟滑动平均（课件第9~12页）。"""
        r = self.result
        self.plot_hr.clear()
        self.legend_hr.clear()
        if r is None or not r.hr_series or "inst" not in r.hr_series:
            return
        t = r.kept_times
        hs = r.hr_series
        self.plot_hr.plot(t, hs["inst"], pen=None, symbol="o", symbolSize=3,
                          symbolBrush=(36, 88, 211, 110), symbolPen=None,
                          name="逐拍心率")
        for key, color, label in (("m60", WARNING, "1分钟均值"),
                                  ("m300", SUCCESS, "5分钟均值")):
            v = hs.get(key)
            if v is None:
                continue
            ok = np.isfinite(v)
            if ok.sum() >= 2:
                self.plot_hr.plot(t[ok], v[ok],
                                  pen=pg.mkPen(color, width=2), name=label)
        self.plot_hr.setLabel("bottom", "时间", units="s")
        self.plot_hr.setLabel("left", "心率", units="bpm")

    def draw_psd(self) -> None:
        r = self.result
        self.plot_psd.clear()
        if r is None or r.freq is None:
            self.plot_psd.setXRange(0, 0.4)
            self.plot_psd.setYRange(0, 1)
            self.psd_hint.show()
            return
        self.psd_hint.hide()
        freqs = r.freq["_freqs"]
        psd = r.freq["_psd"]
        self.plot_psd.plot(freqs, psd, pen=pg.mkPen(ACCENT, width=1),
                           fillLevel=0, fillBrush=(36, 88, 211, 40))
        for f0, f1, color in (
            (0.003, 0.04, (146, 153, 164, 45)),
            (0.04, 0.15, (185, 104, 25, 55)),
            (0.15, 0.40, (22, 116, 81, 55)),
        ):
            region = pg.LinearRegionItem(
                values=[f0, f1], movable=False, brush=color)
            self.plot_psd.addItem(region)
        self.plot_psd.setLabel("bottom", "频率", units="Hz")
        self.plot_psd.setLabel("left", "功率谱密度", units="ms²/Hz")

    def draw_poincare(self) -> None:
        r = self.result
        self.plot_poin.clear()
        if r is None or len(r.kept_rr) < 3:
            return
        rr = r.kept_rr
        self.plot_poin.plot(rr[:-1], rr[1:], pen=None, symbol="o",
                            symbolSize=4, symbolBrush=(36, 88, 211, 170),
                            symbolPen=None)
        lo, hi = float(rr.min()), float(rr.max())
        pad = (hi - lo) * 0.1 + 1
        line = np.array([lo - pad, hi + pad])
        self.plot_poin.plot(line, line, pen=pg.mkPen(MUTED, style=Qt.DashLine))
        self.plot_poin.setLabel("bottom", "RR(n) ", units="ms")
        self.plot_poin.setLabel("left", "RR(n+1)", units="ms")
        self.plot_poin.setAspectLocked(True)

    def draw_hist(self) -> None:
        """RR直方图（与三角指数同口径：1/128秒 ≈ 7.8125ms 一栏）。"""
        r = self.result
        self.plot_hist.clear()
        if r is None or len(r.kept_rr) < 5:
            return
        rr = r.kept_rr
        bin_ms = 1000.0 / 128.0
        lo = np.floor(rr.min() / bin_ms) * bin_ms
        hi = np.ceil(rr.max() / bin_ms) * bin_ms
        n_bins = max(1, int(round((hi - lo) / bin_ms)))
        counts, edges = np.histogram(rr, bins=n_bins, range=(lo, hi))
        self.plot_hist.plot(edges, counts, stepMode=True, fillLevel=0,
                            fillBrush=(36, 88, 211, 60),
                            pen=pg.mkPen(ACCENT, width=1))
        self.plot_hist.setLabel("bottom", "RR间期", units="ms")
        self.plot_hist.setLabel("left", "心跳次数")

    # ================================================================ 导出

    def export_results(self) -> None:
        r = self.result
        if r is None or r.error:
            return
        out = self.folder
        plots = [
            (self.plot_ecg, "HRV_图1_心电图与QRS定位.png"),
            (self.plot_rr, "HRV_图2_心跳间隔曲线.png"),
            (self.plot_hr, "HRV_图3_心率趋势.png"),
            (self.plot_psd, "HRV_图4_频谱.png"),
            (self.plot_poin, "HRV_图5_散点图.png"),
            (self.plot_hist, "HRV_图6_RR直方图.png"),
        ]
        from pyqtgraph.exporters import ImageExporter
        saved = []
        for widget, name in plots:
            try:
                exporter = ImageExporter(widget.getPlotItem())
                exporter.parameters()["width"] = 1400
                exporter.export(str(out / name))
                saved.append(name)
            except Exception:
                pass

        csv_path = out / "HRV指标.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["指标", "数值", "参考范围", "含义"])
            for row in range(self.table.rowCount()):
                vals = [self.table.item(row, c).text() if self.table.item(row, c) else ""
                        for c in range(4)]
                w.writerow(vals)
        saved.append(csv_path.name)

        beats_path = out / "逐拍明细.csv"
        with open(beats_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["R波时间(秒)", "RR间期(ms)", "间期是否有效",
                        "Q点时间(秒)", "S点时间(秒)", "QRS宽度(ms)",
                        f"是否宽QRS(>{QRS_WIDE_MS:.0f}ms)"])
            for i, rp in enumerate(r.r_peaks):
                rr_v = f"{r.rr_ms[i-1]:.2f}" if i >= 1 else ""
                ok_v = ("有效" if r.rr_ok_mask[i-1] else "剔除") if i >= 1 else ""
                q_v = f"{r.q_onset[i]/r.fs:.3f}" if i < len(r.q_onset) and r.q_onset[i] > 0 else "—"
                s_v = f"{r.s_off[i]/r.fs:.3f}" if i < len(r.s_off) and r.s_off[i] > 0 else "—"
                qrs_v = f"{r.qrs_ms[i]:.1f}" if i < len(r.qrs_ms) and r.qrs_ms[i] == r.qrs_ms[i] else "—"
                wide_v = "是" if i < len(r.qrs_wide) and r.qrs_wide[i] else "否"
                w.writerow([f"{rp/r.fs:.3f}", rr_v, ok_v, q_v, s_v, qrs_v, wide_v])
        saved.append(beats_path.name)

        txt_path = out / "分析解读.txt"
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(f"HRV 分析解读 — {self.folder.name}\n")
            fh.write(f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write(self.lbl_summary.text().replace(" · ", "\n") + "\n\n")
            fh.write("—— 解读 ——\n")
            if r.findings:
                for lv, txt in r.findings:
                    tag = {"good": "[正常]", "info": "[提示]",
                           "warn": "[注意]", "alert": "[警示]"}.get(lv, "")
                    fh.write(f"{tag} {txt}\n")
            else:
                fh.write("（无）\n")
            fh.write("\n以上为基于公开人群统计的规则化参考提示，不构成医疗诊断。\n")
        saved.append(txt_path.name)

        QMessageBox.information(
            self, "导出完成",
            "已保存到录制文件夹：\n" + str(out) + "\n\n" + "\n".join(saved))

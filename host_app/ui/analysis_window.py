"""分析结果窗口：4 张图 + 指标表 + 一键导出。"""

import csv
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
from core.hrv import HrvResult, analyze

# 指标定义: (结果键, 显示名+单位, 含义)
_METRIC_ROWS = [
    ("", "—— 基本信息 ——", ""),
    ("duration_s", "录制时长 (秒)", "本次录制的数据长度"),
    ("fs", "采样率 (Hz)", "每秒采集的数据点数"),
    ("n_detected", "检出心跳数 (次)", "算法在波形中识别出的全部心跳"),
    ("n_kept", "有效心跳数 (次)", "通过质量把关、用于计算指标的心跳"),
    ("removed_pct", "剔除比例 (%)", "被判定为伪差而剔除的心跳间隔占比"),
    ("", "—— 时域指标 ——", ""),
    ("mean_hr", "平均心率 (bpm)", "每分钟平均心跳次数"),
    ("mean_rr", "平均RR间期 (ms)", "相邻心跳的平均时间间隔"),
    ("sdnn", "SDNN (ms)", "全部心跳间隔的标准差，反映整体变异"),
    ("rmssd", "RMSSD (ms)", "相邻心跳间隔差异的均方根，反映短期变异"),
    ("pnn50", "pNN50 (%)", "相邻间隔相差超过50毫秒的比例"),
    ("sdsd", "SDSD (ms)", "相邻间隔差值的标准差"),
    ("cv", "变异系数 CV (%)", "SDNN 相对平均RR 的百分比"),
    ("", "—— 非线性指标 ——", ""),
    ("sd1", "SD1 (ms)", "散点图短轴，反映短期变异"),
    ("sd2", "SD2 (ms)", "散点图长轴，反映长期变异"),
    ("", "—— 频域指标 ——", ""),
    ("vlf", "VLF 极低频功率 (ms²)", "0.003–0.04Hz，慢调节波段"),
    ("lf", "LF 低频功率 (ms²)", "0.04–0.15Hz，交感+副交感共同作用"),
    ("hf", "HF 高频功率 (ms²)", "0.15–0.4Hz，主要反映副交感/呼吸"),
    ("tp", "总功率 TP (ms²)", "0–0.4Hz 全部功率之和"),
    ("lf_hf", "LF/HF 比值", "低频与高频功率之比"),
    ("lfnu", "LF 归一化 (nu)", "LF 占 (LF+HF) 的百分比"),
    ("hfnu", "HF 归一化 (nu)", "HF 占 (LF+HF) 的百分比"),
]


class AnalysisWindow(QMainWindow):
    def __init__(self, session_folder, parent=None) -> None:
        super().__init__(parent)
        self.folder = Path(session_folder)
        self.setWindowTitle(f"HRV 分析 — {self.folder.name}")
        self.resize(1250, 780)
        self.result: HrvResult | None = None

        session = rec.load_session(self.folder)
        self.data = session
        self.ch1 = session["ch1"]
        self.fs = session["fs"]

        self._build_ui()

    # ================================================================ 界面

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- 左侧 2×2 图 ----
        left = QVBoxLayout()
        strip_bar = QHBoxLayout()
        strip_bar.addWidget(QLabel("心电片段:"))
        self.cmb_strip = QComboBox()
        self.cmb_strip.addItems(["开头 10 秒", "中间 10 秒", "结尾 10 秒"])
        self.cmb_strip.setCurrentIndex(1)
        self.cmb_strip.currentIndexChanged.connect(self.draw_ecg_strip)
        strip_bar.addWidget(self.cmb_strip)
        strip_bar.addStretch(1)
        left.addLayout(strip_bar)

        grid = QGridLayout()
        self.plot_ecg = pg.PlotWidget(title="心电波形与R波（心跳）位置")
        self.plot_rr = pg.PlotWidget(title="心跳间隔曲线（RR间期）")
        self.plot_psd = pg.PlotWidget(title="心率变异频谱（功率谱密度）")
        self.plot_poin = pg.PlotWidget(title="Poincaré 散点图")
        grid.addWidget(self.plot_ecg, 0, 0)
        grid.addWidget(self.plot_rr, 0, 1)
        grid.addWidget(self.plot_psd, 1, 0)
        grid.addWidget(self.plot_poin, 1, 1)
        left.addLayout(grid, stretch=1)
        root.addLayout(left, stretch=5)

        # ---- 右侧 指标表 ----
        right = QVBoxLayout()
        box = QGroupBox("分析指标")
        box_layout = QVBoxLayout(box)
        self.lbl_summary = QLabel("尚未分析")
        self.lbl_summary.setWordWrap(True)
        self.table = QTableWidget(len(_METRIC_ROWS), 3)
        self.table.setHorizontalHeaderLabels(["指标", "数值", "含义"])
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 110)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        box_layout.addWidget(self.lbl_summary)
        box_layout.addWidget(self.table)
        right.addWidget(box, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("导出全部结果到录制文件夹")
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
        self.fill_table()
        self.draw_ecg_strip()
        self.draw_rr()
        self.draw_psd()
        self.draw_poincare()
        self.btn_export.setEnabled(True)

    # ================================================================ 指标表

    def fill_table(self) -> None:
        r = self.result
        f = r.freq or {}
        values = {
            "duration_s": (f"{r.duration_s:.0f}"),
            "fs": (f"{r.fs:.0f}"),
            "n_detected": (f"{len(r.r_peaks)}"),
            "n_kept": (f"{int(r.rr_ok_mask.sum())}"),
            "removed_pct": (f"{r.removed_ratio*100:.1f}"),
            "mean_hr": (f"{r.time['mean_hr']:.1f}"),
            "mean_rr": (f"{r.time['mean_rr']:.1f}"),
            "sdnn": (f"{r.time['sdnn']:.1f}"),
            "rmssd": (f"{r.time['rmssd']:.1f}"),
            "pnn50": (f"{r.time['pnn50']:.1f}"),
            "sdsd": (f"{r.time['sdsd']:.1f}"),
            "cv": (f"{r.time['cv']:.1f}"),
            "sd1": (f"{r.sd1:.1f}"),
            "sd2": (f"{r.sd2:.1f}"),
            "vlf": (f"{f.get('vlf', float('nan')):.1f}" if r.freq else "—"),
            "lf": (f"{f.get('lf', float('nan')):.1f}" if r.freq else "—"),
            "hf": (f"{f.get('hf', float('nan')):.1f}" if r.freq else "—"),
            "tp": (f"{f.get('tp', float('nan')):.1f}" if r.freq else "—"),
            "lf_hf": (f"{f.get('lf_hf', float('nan')):.2f}" if r.freq else "—"),
            "lfnu": (f"{f.get('lfnu', float('nan')):.1f}" if r.freq else "—"),
            "hfnu": (f"{f.get('hfnu', float('nan')):.1f}" if r.freq else "—"),
        }
        for row, (key, name, desc) in enumerate(_METRIC_ROWS):
            is_section = key == ""
            item_name = QTableWidgetItem(name)
            item_val = QTableWidgetItem(values.get(key, "") if not is_section else "")
            item_desc = QTableWidgetItem(desc)
            if is_section:
                item_name.setForeground(QColor("#15539e"))
                font = item_name.font()
                font.setBold(True)
                item_name.setFont(font)
            item_val.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_val)
            self.table.setItem(row, 2, item_desc)
        self.table.resizeRowsToContents()

    # ================================================================ 绘图

    def draw_ecg_strip(self) -> None:
        r = self.result
        self.plot_ecg.clear()
        if r is None or len(r.ecg_clean) == 0:
            return
        x = np.arange(len(r.ecg_clean)) / r.fs
        pos = (0, 0.45, 0.9)[max(0, self.cmb_strip.currentIndex())]
        center = int(pos * len(x))
        half = int(5.0 * r.fs)
        i0, i1 = max(0, center - half), min(len(x), center + half)
        self.plot_ecg.plot(x[i0:i1], r.ecg_clean[i0:i1],
                           pen=pg.mkPen("#1f77b4", width=1))
        m = (r.r_peaks >= i0) & (r.r_peaks < i1)
        if m.any():
            self.plot_ecg.plot(
                r.r_peaks[m] / r.fs, r.ecg_clean[r.r_peaks[m]],
                pen=None, symbol="t", symbolSize=10,
                symbolBrush="#d62728", symbolPen=None)
        self.plot_ecg.setLabel("bottom", "时间", units="s")
        self.plot_ecg.setLabel("left", "电压", units="V")

    def draw_rr(self) -> None:
        r = self.result
        self.plot_rr.clear()
        if r is None or len(r.rr_ms) == 0:
            return
        ok = r.rr_ok_mask
        self.plot_rr.plot(r.rr_times_s[ok], r.rr_ms[ok],
                          pen=pg.mkPen("#1f77b4", width=1),
                          symbol="o", symbolSize=3,
                          symbolBrush="#1f77b4", symbolPen=None)
        if (~ok).any():
            self.plot_rr.plot(r.rr_times_s[~ok], r.rr_ms[~ok],
                              pen=None, symbol="x", symbolSize=9,
                              symbolBrush="#d62728", symbolPen="#d62728")
        self.plot_rr.setLabel("bottom", "时间", units="s")
        self.plot_rr.setLabel("left", "RR间期", units="ms")

    def draw_psd(self) -> None:
        r = self.result
        self.plot_psd.clear()
        if r is None or r.freq is None:
            text = pg.TextItem(
                "数据不足2分钟，未计算频域指标\n（标准短时HRV分析建议录制5分钟）",
                color="#b80", anchor=(0.5, 0.5))
            self.plot_psd.addItem(text)
            self.plot_psd.setXRange(0, 0.4)
            self.plot_psd.setYRange(0, 1)
            return
        freqs = r.freq["_freqs"]
        psd = r.freq["_psd"]
        self.plot_psd.plot(freqs, psd, pen=pg.mkPen("#1f77b4", width=1),
                           fillLevel=0, fillBrush=(31, 119, 180, 40))
        for f0, f1, color, name in (
            (0.003, 0.04, (150, 150, 150, 40), "VLF"),
            (0.04, 0.15, (255, 127, 14, 50), "LF"),
            (0.15, 0.40, (44, 160, 44, 50), "HF"),
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
                            symbolSize=4, symbolBrush=(31, 119, 180, 160),
                            symbolPen=None)
        lo, hi = float(rr.min()), float(rr.max())
        pad = (hi - lo) * 0.1 + 1
        line = np.array([lo - pad, hi + pad])
        self.plot_poin.plot(line, line, pen=pg.mkPen("#888", style=Qt.DashLine))
        self.plot_poin.setLabel("bottom", "RR(n) ", units="ms")
        self.plot_poin.setLabel("left", "RR(n+1)", units="ms")
        self.plot_poin.setAspectLocked(True)

    # ================================================================ 导出

    def export_results(self) -> None:
        r = self.result
        if r is None or r.error:
            return
        out = self.folder
        plots = [
            (self.plot_ecg, "HRV_图1_心电图与心跳位置.png"),
            (self.plot_rr, "HRV_图2_心跳间隔曲线.png"),
            (self.plot_psd, "HRV_图3_频谱.png"),
            (self.plot_poin, "HRV_图4_散点图.png"),
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
            w.writerow(["指标", "数值", "含义"])
            for row in range(self.table.rowCount()):
                vals = [self.table.item(row, c).text() if self.table.item(row, c) else ""
                        for c in range(3)]
                w.writerow(vals)
        saved.append(csv_path.name)

        rr_path = out / "RR间期.csv"
        with open(rr_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["时间(秒)", "RR间期(ms)", "是否有效"])
            for t, v, ok in zip(r.rr_times_s, r.rr_ms, r.rr_ok_mask):
                w.writerow([f"{t:.3f}", f"{v:.2f}", "有效" if ok else "剔除"])
        saved.append(rr_path.name)

        QMessageBox.information(
            self, "导出完成",
            "已保存到录制文件夹：\n" + str(out) + "\n\n" + "\n".join(saved))

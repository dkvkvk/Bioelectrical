"""主界面：连接设备 / 实时波形 / 设备控制 / 录制 / 入口分析。"""

import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from core.ble_link import (
    BleLink, ST_CONNECTED, ST_CONNECTING, ST_DISCONNECTED, ST_IDLE,
    ST_SCANNING,
)
from core.demo_source import DemoSource
from core.frame_parser import FrameParser
from core.paths import recordings_dir
from core.serial_link import SerialLink, available_ports
from core.version import APP_NAME, __version__
from core import recorder as rec
from ui.analysis_window import AnalysisWindow

# 增益档位（显示名, CH1SET, CH2SET），与协议文档一致
GAINS = [
    ("360x（默认）", 0x20, 0x00),
    ("540x", 0x30, 0x10),
    ("680x", 0x22, 0x02),
    ("720x", 0x34, 0x14),
    ("1020x", 0x32, 0x12),
    ("1080x", 0x38, 0x18),
    ("1360x", 0x36, 0x16),
    ("1440x", 0x3C, 0x1C),
    ("2040x", 0x3A, 0x1A),
    ("2720x", 0x3E, 0x1E),
]
# 采样率（显示名, SR 字节, 实际Hz）
SAMPLE_RATES = [
    ("250 Hz", 0x04, 250.0),
    ("500 Hz（推荐）", 0x02, 500.0),
    ("1000 Hz", 0x01, 1000.0),
]
DISPLAY_SECONDS = [("5 秒", 5), ("10 秒", 10), ("30 秒", 30), ("60 秒", 60)]

_RING_SECONDS = 120          # 环形缓冲保留时长
_MAX_FS = 1000.0             # 缓冲按最高采样率分配


class RingBuffer:
    """定长环形缓冲，支持按全局序号取最近 n 个样本。"""

    def __init__(self, capacity: int) -> None:
        self.cap = capacity
        self.buf = np.zeros(capacity)
        self.start = 0
        self.count = 0
        self.total = 0

    def clear(self) -> None:
        self.start = 0
        self.count = 0
        self.total = 0

    def append(self, arr) -> None:
        arr = np.asarray(arr, dtype=float)
        n = len(arr)
        self.total += n
        if n >= self.cap:
            self.buf[:] = arr[n - self.cap:]
            self.start = 0
            self.count = self.cap
            return
        pos = (self.start + self.count) % self.cap
        first = min(n, self.cap - pos)
        self.buf[pos:pos + first] = arr[:first]
        if n > first:
            self.buf[:n - first] = arr[first:]
        if self.count + n <= self.cap:
            self.count += n
        else:
            shift = self.count + n - self.cap
            self.start = (self.start + shift) % self.cap
            self.count = self.cap

    def tail(self, n: int):
        n = min(n, self.count)
        if n <= 0:
            return 0, self.buf[:0]
        idx = (self.start + self.count - n) % self.cap
        if idx + n <= self.cap:
            data = self.buf[idx:idx + n].copy()
        else:
            k = self.cap - idx
            data = np.concatenate([self.buf[idx:], self.buf[:n - k]])
        return self.total - n, data


class MainWindow(QMainWindow):
    def __init__(self, demo_on_start: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1280, 800)

        self.sessions_dir = recordings_dir()

        self.parser = FrameParser()
        self.ble = BleLink(self.parser)
        self.ble.frames.connect(self.on_batch)
        self.ble.state_changed.connect(self.on_link_state)
        self.ble.scan_hit.connect(self.on_scan_hit)
        self.ble.log.connect(self.log)
        self.ble.start()

        self.serial = SerialLink(self.parser)
        self.serial.frames.connect(self.on_batch)
        self.serial.state_changed.connect(self.on_link_state)
        self.serial.log.connect(self.log)

        self.fs = 500.0
        self.demo = None
        self.demo_timer = QTimer(self)
        self.demo_timer.setInterval(40)  # 40ms ≈ 20 个样本 @500Hz
        self.demo_timer.timeout.connect(self.on_demo_tick)
        self.demo_elapsed = 0.0

        self.recorder = rec.Recorder(self.sessions_dir)
        self.last_session: Path | None = None
        self.analysis_windows: list = []

        cap = int(_MAX_FS * _RING_SECONDS)
        self.ring1 = RingBuffer(cap)
        self.ring2 = RingBuffer(cap)
        self.batch_count = 0          # 供自检用
        self._last_batch = None

        self.paused = False
        self._build_ui()
        self._set_connected_ui(False)

        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(40)
        self.plot_timer.timeout.connect(self.refresh_plots)
        self.plot_timer.start()

        self.slow_timer = QTimer(self)
        self.slow_timer.setInterval(500)
        self.slow_timer.timeout.connect(self.refresh_status)
        self.slow_timer.start()

        self.log("程序已启动。请先点「扫描设备」连接真机，或点「演示模式」体验全部功能。")
        if demo_on_start:
            self.toggle_demo(True)

    # ================================================================ 界面搭建

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # ---- 顶部：连接区 ----
        top = QHBoxLayout()
        self.cmb_transport = QComboBox()
        self.cmb_transport.addItems(["无线蓝牙", "串口（USB线）"])
        self.cmb_transport.currentIndexChanged.connect(self.on_transport_changed)
        self.btn_scan = QPushButton("扫描设备")
        self.btn_scan.clicked.connect(self.ble.scan)
        self.cmb_device = QComboBox()
        self.cmb_device.setMinimumWidth(200)
        self.btn_ports = QPushButton("刷新端口")
        self.btn_ports.clicked.connect(self.refresh_ports)
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(200)
        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.connect_selected)
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.clicked.connect(self.disconnect_link)
        self.btn_demo = QPushButton("演示模式")
        self.btn_demo.setCheckable(True)
        self.btn_demo.toggled.connect(self.toggle_demo)
        self.lbl_state = QLabel("● 未连接")
        for w in (self.cmb_transport, self.btn_scan, self.cmb_device,
                  self.btn_ports, self.cmb_port, self.btn_connect,
                  self.btn_disconnect, self.btn_demo, self.lbl_state):
            top.addWidget(w)
        self.lbl_state.setStyleSheet("color:#888; font-weight:bold;")
        top.addStretch(1)
        root.addLayout(top)
        self._apply_transport_visibility()

        # ---- 状态行 ----
        status = QHBoxLayout()
        self.lbl_battery = QLabel("电量：—")
        self.lbl_hr = QLabel("心率：—")
        self.lbl_lead = QLabel("电极：—")
        self.lbl_frames = QLabel("数据帧：0（坏 0）")
        for w in (self.lbl_battery, self.lbl_hr, self.lbl_lead, self.lbl_frames):
            status.addWidget(w)
        status.addStretch(1)
        root.addLayout(status)

        # ---- 中部：波形 + 右侧面板 ----
        mid = QHBoxLayout()
        pg.setConfigOptions(antialias=False)
        self.plot1 = pg.PlotWidget(title="通道1 (V)")
        self.plot2 = pg.PlotWidget(title="通道2 (V)")
        for p in (self.plot1, self.plot2):
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setLabel("bottom", "时间", units="s")
        self.plot2.setXLink(self.plot1)
        self.curve1 = self.plot1.plot(pen=pg.mkPen("#1f77b4", width=1))
        self.curve2 = self.plot2.plot(pen=pg.mkPen("#2ca02c", width=1))
        for c in (self.curve1, self.curve2):
            c.setDownsampling(auto=True, method="peak")
            c.setClipToView(True)

        waves = QVBoxLayout()
        wave_bar = QHBoxLayout()
        self.btn_pause = QPushButton("暂停显示")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.set_paused)
        lbl_win = QLabel("时间窗")
        self.cmb_window = QComboBox()
        for name, _ in DISPLAY_SECONDS:
            self.cmb_window.addItem(name)
        self.cmb_window.setCurrentIndex(1)
        self.cmb_window.currentIndexChanged.connect(
            lambda _: self.refresh_plots())
        wave_bar.addWidget(self.btn_pause)
        wave_bar.addWidget(lbl_win)
        wave_bar.addWidget(self.cmb_window)
        wave_bar.addStretch(1)
        waves.addLayout(wave_bar)
        waves.addWidget(self.plot1, stretch=5)
        waves.addWidget(self.plot2, stretch=3)
        mid.addLayout(waves, stretch=5)

        side = QVBoxLayout()
        side.addWidget(self._build_control_group())
        side.addWidget(self._build_record_group())
        side.addStretch(1)
        mid.addLayout(side, stretch=1)
        root.addLayout(mid, stretch=1)

        # ---- 底部：日志 ----
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(110)
        root.addWidget(self.txt_log)

    def _build_control_group(self) -> QGroupBox:
        g = QGroupBox("设备设置")
        lay = QGridLayout(g)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(6)

        self.cmb_gain = QComboBox()
        for name, _, _ in GAINS:
            self.cmb_gain.addItem(name)
        self.cmb_sr = QComboBox()
        for name, _, _ in SAMPLE_RATES:
            self.cmb_sr.addItem(name)
        self.cmb_sr.setCurrentIndex(1)
        self.chk_f1 = QCheckBox("通道1 滤波")
        self.chk_f1.setChecked(True)
        self.chk_f2 = QCheckBox("通道2 滤波")
        self.chk_f2.setChecked(True)
        self.btn_apply = QPushButton("应用设置（并开始数据流）")
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_stop_stream = QPushButton("暂停数据流")
        self.btn_stop_stream.clicked.connect(self.stop_stream)

        lay.addWidget(QLabel("增益"), 0, 0)
        lay.addWidget(self.cmb_gain, 0, 1)
        lay.addWidget(QLabel("采样率"), 1, 0)
        lay.addWidget(self.cmb_sr, 1, 1)
        lay.addWidget(self.chk_f1, 2, 0, 1, 2)
        lay.addWidget(self.chk_f2, 3, 0, 1, 2)
        lay.addWidget(self.btn_apply, 4, 0, 1, 2)
        lay.addWidget(self.btn_stop_stream, 5, 0, 1, 2)
        return g

    def _build_record_group(self) -> QGroupBox:
        g = QGroupBox("录制与分析")
        lay = QGridLayout(g)
        self.btn_record = QPushButton("● 开始录制")
        self.btn_record.clicked.connect(self.toggle_record)
        self.btn_record.setStyleSheet(
            "QPushButton{color:#b00; font-weight:bold;}")
        self.lbl_rec = QLabel("未在录制")
        self.btn_analyze_last = QPushButton("分析最近一次录制")
        self.btn_analyze_last.clicked.connect(self.analyze_last)
        self.btn_analyze_hist = QPushButton("分析历史录制…")
        self.btn_analyze_hist.clicked.connect(self.analyze_history)
        lay.addWidget(self.btn_record, 0, 0)
        lay.addWidget(self.lbl_rec, 0, 1)
        lay.addWidget(self.btn_analyze_last, 1, 0, 1, 2)
        lay.addWidget(self.btn_analyze_hist, 2, 0, 1, 2)
        return g

    # ================================================================ 数据流

    def on_batch(self, batch: dict) -> None:
        self.batch_count += 1
        self._last_batch = batch
        self.ring1.append(batch["ch1"])
        self.ring2.append(batch["ch2"])
        if self.recorder.active:
            self.recorder.append(batch)

    def on_demo_tick(self) -> None:
        if self.demo is None:
            return
        self.demo_elapsed += 0.04
        self.demo.tick_minutes(self.demo_elapsed)
        for batch in self.demo.next_batches(20):
            self.on_batch(batch)

    # ================================================================ 连接

    @property
    def serial_mode(self) -> bool:
        return self.cmb_transport.currentIndex() == 1

    def _apply_transport_visibility(self) -> None:
        ble_mode = not self.serial_mode
        self.btn_scan.setVisible(ble_mode)
        self.cmb_device.setVisible(ble_mode)
        self.btn_ports.setVisible(not ble_mode)
        self.cmb_port.setVisible(not ble_mode)

    def on_transport_changed(self, _index: int) -> None:
        if self.ble._state == ST_CONNECTED or self.serial.isRunning():
            self.cmb_transport.blockSignals(True)
            self.cmb_transport.setCurrentIndex(1 if self.serial_mode else 0)
            self.cmb_transport.blockSignals(False)
            self.log("已连接时不能切换连接方式，请先断开。")
            return
        self._apply_transport_visibility()
        self.log("连接方式已切换为：" +
                 ("串口（USB线）" if self.serial_mode else "无线蓝牙"))

    def refresh_ports(self) -> None:
        self.cmb_port.clear()
        ports = available_ports()
        for name, desc in ports:
            self.cmb_port.addItem(f"{name}（{desc}）" if desc else name, name)
        if ports:
            self.cmb_port.setCurrentIndex(0)
            self.log(f"发现 {len(ports)} 个串口，选择设备对应的端口后点「连接」。")
        else:
            self.log("没有发现串口。请确认设备已用USB线插到电脑上。")

    def connect_selected(self) -> None:
        if self.serial_mode:
            port = self.cmb_port.currentData()
            if not port:
                QMessageBox.information(
                    self, "提示", "请先点「刷新端口」，并选择设备对应的串口。")
                return
            self.serial.connect_to(port)
            return
        addr = self.cmb_device.currentData()
        if addr:
            self.ble.connect_to(addr)
        else:
            QMessageBox.information(
                self, "提示", "请先点「扫描设备」，并从下拉框选择设备。")

    def disconnect_link(self) -> None:
        if self.serial_mode:
            self.serial.disconnect()
        else:
            self.ble.disconnect()

    def on_scan_hit(self, addr: str, name: str) -> None:
        # 同一地址去重
        for i in range(self.cmb_device.count()):
            if self.cmb_device.itemData(i) == addr:
                return
        self.cmb_device.addItem(f"{name}（{addr}）", addr)
        self.cmb_device.setCurrentIndex(self.cmb_device.count() - 1)

    def on_link_state(self, state: str, msg: str) -> None:
        colors = {ST_IDLE: "#888", ST_SCANNING: "#b80", ST_CONNECTING: "#b80",
                  ST_CONNECTED: "#080", ST_DISCONNECTED: "#b00"}
        dot = "●"
        names = {ST_IDLE: "未连接", ST_SCANNING: "扫描中", ST_CONNECTING: "连接中",
                 ST_CONNECTED: "已连接", ST_DISCONNECTED: "连接断开"}
        label = names.get(state, state)
        self.lbl_state.setText(f"{dot} {label}")
        self.lbl_state.setStyleSheet(
            f"color:{colors.get(state, '#888')}; font-weight:bold;")
        if msg:
            self.log(msg)
        connected = state == ST_CONNECTED
        self._set_connected_ui(connected)
        if state == ST_DISCONNECTED and self.recorder.active:
            self.log("连接断开，自动结束录制。")
            self.toggle_record(force_stop=True)
        if state == ST_CONNECTED:
            # 连接成功后把当前界面设置发给设备，保证双方状态一致；
            # 串口模式下这也是设备开始发数据的第一条命令
            self.apply_settings()

    def _set_connected_ui(self, connected: bool) -> None:
        self.btn_disconnect.setEnabled(connected)
        self.btn_scan.setEnabled(not connected and not self.serial_mode)
        self.btn_connect.setEnabled(not connected)
        self.cmb_device.setEnabled(not connected and not self.serial_mode)
        self.btn_ports.setEnabled(not connected and self.serial_mode)
        self.cmb_port.setEnabled(not connected and self.serial_mode)
        self.cmb_transport.setEnabled(not connected)

    # ================================================================ 演示模式

    def toggle_demo(self, on: bool) -> None:
        if on:
            if self.ble._state == ST_CONNECTED or self.serial.isRunning():
                self.disconnect_link()
            if self.recorder.active:
                self.toggle_record(force_stop=True)
            self.demo = DemoSource()
            self.demo_elapsed = 0.0
            self.ring1.clear()
            self.ring2.clear()
            self.parser.filter_ch1 = False
            self.parser.filter_ch2 = False
            self.demo_timer.start()
            self.btn_demo.setText("退出演示模式")
            self.btn_scan.setEnabled(False)
            self.btn_connect.setEnabled(False)
            self.cmb_device.setEnabled(False)
            self.btn_ports.setEnabled(False)
            self.cmb_port.setEnabled(False)
            self.cmb_transport.setEnabled(False)
            self.btn_disconnect.setEnabled(False)
            self.log("演示模式已开启：正在播放模拟心电（可正常录制与分析）。")
        else:
            self.demo_timer.stop()
            self.demo = None
            self.btn_demo.setText("演示模式")
            self.btn_scan.setEnabled(True)
            self.btn_connect.setEnabled(True)
            self.cmb_transport.setEnabled(True)
            self._set_connected_ui(False)
            self.lbl_state.setText("● 未连接")
            self.lbl_state.setStyleSheet("color:#888; font-weight:bold;")
            self.log("演示模式已退出。")

    # ================================================================ 设备设置

    def apply_settings(self) -> None:
        if self.demo is not None:
            self._settings_snapshot = {
                "gain": "演示", "sample_rate": "500Hz",
                "filter_ch1": False, "filter_ch2": False,
                "note": "演示数据（固定500Hz）",
            }
            self.log("演示模式下设置不会发给真实设备（模拟信号固定为 500Hz）。")
            return
        gi = self.cmb_gain.currentIndex()
        name_g, ch1set, ch2set = GAINS[max(0, gi)]
        si = self.cmb_sr.currentIndex()
        name_sr, sr_code, fs = SAMPLE_RATES[max(0, si)]
        f1 = 1 if self.chk_f1.isChecked() else 0
        f2 = 1 if self.chk_f2.isChecked() else 0

        old_fs = self.fs
        self.fs = fs
        self.parser.filter_ch1 = bool(f1)
        self.parser.filter_ch2 = bool(f2)
        if fs != old_fs:
            self.ring1.clear()
            self.ring2.clear()
            self.log(f"采样率从 {old_fs:.0f}Hz 切到 {fs:.0f}Hz，波形已重新开始。")

        settings = {
            "gain": name_g, "ch1set": f"0x{ch1set:02X}",
            "ch2set": f"0x{ch2set:02X}", "sample_rate": f"{fs:.0f}Hz",
            "filter_ch1": bool(f1), "filter_ch2": bool(f2),
        }
        self._settings_snapshot = settings
        if self.serial_mode:
            self.serial.send_command(ch1set, ch2set, sr_code, f1, f2, 1)
        else:
            self.ble.send_command(ch1set, ch2set, sr_code, f1, f2, 1)

    def stop_stream(self) -> None:
        if self.demo is not None:
            self.log("演示模式下没有真实数据流可暂停。")
            return
        gi = max(0, self.cmb_gain.currentIndex())
        _, ch1set, ch2set = GAINS[gi]
        si = max(0, self.cmb_sr.currentIndex())
        _, sr_code, _ = SAMPLE_RATES[si]
        cmd = (ch1set, ch2set, sr_code,
               1 if self.chk_f1.isChecked() else 0,
               1 if self.chk_f2.isChecked() else 0, 0)
        if self.serial_mode:
            self.serial.send_command(*cmd)
        else:
            self.ble.send_command(*cmd)
        self.log("已通知设备暂停发送数据。")

    # ================================================================ 波形

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.btn_pause.setText("继续显示" if paused else "暂停显示")
        if not paused:
            self.refresh_plots()

    def refresh_plots(self) -> None:
        if self.paused:
            return
        secs = DISPLAY_SECONDS[max(0, self.cmb_window.currentIndex())][1]
        n = int(self.fs * secs)
        for ring, curve in ((self.ring1, self.curve1), (self.ring2, self.curve2)):
            gstart, data = ring.tail(n)
            if len(data) == 0:
                curve.setData([])
                continue
            x = (gstart + np.arange(len(data))) / self.fs
            curve.setData(x, data)

    def refresh_status(self) -> None:
        b = self._last_batch
        if b is not None:
            batt = b["battery"]
            self.lbl_battery.setText(
                f"电量：{batt}%" if batt is not None else "电量：—（串口无电量）")
            self.lbl_hr.setText(f"心率：{b['heart_rate']} bpm")
            if b["lead_off"]:
                self.lbl_lead.setText("电极：脱落！")
                self.lbl_lead.setStyleSheet("color:#b00; font-weight:bold;")
            elif self.serial_mode and self.ble._state != ST_CONNECTED:
                self.lbl_lead.setText("电极：—（串口不提供）")
                self.lbl_lead.setStyleSheet("color:#888;")
            else:
                self.lbl_lead.setText("电极：正常")
                self.lbl_lead.setStyleSheet("color:#080;")
        if self.demo is not None:
            self.lbl_frames.setText(f"数据批次：{self.batch_count}（演示）")
        else:
            self.lbl_frames.setText(
                f"数据帧：{self.parser.frames_ok}（坏 {self.parser.frames_bad}）")
        if self.recorder.active:
            self.lbl_rec.setText(
                f"录制中 {self._fmt(self.recorder.elapsed_s())}"
                f"（{self.recorder.sample_count()} 点）")

    @staticmethod
    def _fmt(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    # ================================================================ 录制与分析

    def toggle_record(self, checked=None, force_stop: bool = False) -> None:
        if self.recorder.active or force_stop:
            folder = self.recorder.stop()
            if folder is not None:
                self.last_session = folder
                self.log(f"录制已保存到：{folder}")
            self.btn_record.setText("● 开始录制")
            self.lbl_rec.setText(f"已保存（{folder.name if folder else ''}）")
            self.cmb_gain.setEnabled(True)
            self.cmb_sr.setEnabled(True)
            self.btn_analyze_last.setEnabled(True)
            return
        if self.demo is None and not (self.ble._state == ST_CONNECTED
                                      or self.serial.isRunning()):
            QMessageBox.information(
                self, "无法录制",
                "还没有数据来源：请先连接设备（蓝牙或串口），或开启演示模式。")
            return
        if self.demo is not None:
            self.apply_settings()  # 演示模式下刷新为演示快照
            settings = self._settings_snapshot
        else:
            settings = getattr(self, "_settings_snapshot", None) or {
                "gain": GAINS[max(0, self.cmb_gain.currentIndex())][0],
                "sample_rate": f"{self.fs:.0f}Hz",
                "filter_ch1": self.chk_f1.isChecked(),
                "filter_ch2": self.chk_f2.isChecked(),
            }
        folder = self.recorder.start(
            fs=500.0 if self.demo is not None else self.fs,
            source="demo" if self.demo is not None else "ble",
            settings=settings)
        self.btn_record.setText("■ 停止录制")
        self.lbl_rec.setText("录制中 00:00")
        self.cmb_gain.setEnabled(False)
        self.cmb_sr.setEnabled(False)
        self.btn_analyze_last.setEnabled(False)
        self.log(f"开始录制（保存到 {folder.name}）。建议安静录制 3~5 分钟再做HRV分析。")

    def analyze_last(self) -> None:
        if self.last_session is None or not self.last_session.exists():
            QMessageBox.information(self, "提示", "还没有可分析的录制。")
            return
        self.open_analysis(self.last_session)

    def analyze_history(self) -> None:
        sessions = rec.list_sessions(self.sessions_dir)
        if not sessions:
            QMessageBox.information(self, "提示", "还没有任何历史录制。")
            return
        labels = [s["label"] for s in sessions]
        name, ok = QInputDialog.getItem(
            self, "选择录制", "选择要分析的录制：", labels, 0, False)
        if not ok:
            return
        self.open_analysis(sessions[labels.index(name)]["folder"])

    def open_analysis(self, folder: Path) -> None:
        try:
            win = AnalysisWindow(folder, parent=self)
        except Exception as exc:
            QMessageBox.critical(self, "分析失败", f"读取录制数据失败：{exc}")
            return
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.destroyed.connect(lambda _=None, w=win: self._forget_window(w))
        win.show()
        self.analysis_windows.append(win)
        win.run_analysis()

    def _forget_window(self, w) -> None:
        if w in self.analysis_windows:
            self.analysis_windows.remove(w)

    # ================================================================ 其他

    def log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{stamp}] {msg}")

    def closeEvent(self, event) -> None:
        if self.recorder.active:
            self.recorder.stop()
        self.demo_timer.stop()
        self.serial.disconnect()
        self.serial.wait(2000)
        self.ble.shutdown()
        self.ble.wait(2000)
        super().closeEvent(event)

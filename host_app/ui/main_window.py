"""主界面：连接设备 / 实时波形 / 设备控制 / 录制 / 分析入口 / 录制管理。"""

import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer
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
from core.theme import (
    ACCENT, DANGER, LINE, MUTED, QUIET, SUCCESS, SURFACE_SUBTLE, WARNING,
    WAVE_CH1, WAVE_CH2, PlotHint, mono_font, pathtag,
)
from core.version import APP_NAME, __version__
from core import recorder as rec
from ui.analysis_window import AnalysisWindow
from ui.recordings_window import RecordingsWindow

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
    def __init__(self, generator_on_start: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1280, 800)

        self.sessions_dir = recordings_dir()

        self.parser = FrameParser()
        self.ble = BleLink(self.parser)
        self.ble.frames.connect(self.on_batch)
        self.ble.state_changed.connect(self.on_ble_state)
        self.ble.scan_hit.connect(self.on_scan_hit)
        self.ble.log.connect(self.log)
        self.ble.start()

        self.serial = SerialLink(self.parser)
        self.serial.frames.connect(self.on_batch)
        self.serial.state_changed.connect(self.on_serial_state)
        self.serial.log.connect(self.log)

        # 最近一次已下发给设备的命令（按连接方式区分）：
        # 完全相同的命令不再重复下发，避免设备重复重置、波形抖动；
        # 连接状态一变化就清空，保证重连后第一条命令一定下发。
        self._last_ble_cmd: bytes | None = None
        self._last_serial_cmd: bytes | None = None

        self.fs = 500.0
        # 内部信号发生器（仅供打包自检验证，不在界面上出现）
        self.generator = None
        self._gen_timer = QTimer(self)
        self._gen_timer.setInterval(40)
        self._gen_timer.timeout.connect(self._on_generator_tick)

        self.recorder = rec.Recorder(self.sessions_dir)
        self.last_session: Path | None = None
        self.analysis_windows: list = []

        cap = int(_MAX_FS * _RING_SECONDS)
        self.ring1 = RingBuffer(cap)
        self.ring2 = RingBuffer(cap)
        self.batch_count = 0          # 收到的数据批次（所有来源统一计数）
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

        self.log("程序已启动。请选择连接方式（无线蓝牙或串口USB线）后连接设备。")
        if generator_on_start:
            self._start_generator()

    # ================================================================ 界面搭建

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # ---- 顶部：连接区 ----
        top = QHBoxLayout()
        top.addWidget(pathtag("ACQ / LIVE"))
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
        self.btn_connect.setProperty("variant", "primary")
        self.btn_connect.clicked.connect(self.connect_selected)
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.clicked.connect(self.disconnect_link)
        self.lbl_state = QLabel("● 未连接")
        for w in (self.cmb_transport, self.btn_scan, self.cmb_device,
                  self.btn_ports, self.cmb_port, self.btn_connect,
                  self.btn_disconnect, self.lbl_state):
            top.addWidget(w)
        self.lbl_state.setStyleSheet(f"color:{QUIET}; font-weight:bold;")
        top.addStretch(1)
        root.addLayout(top)
        self._apply_transport_visibility()

        # ---- 状态行（数值用等宽字体） ----
        status = QHBoxLayout()
        self.lbl_battery = QLabel("电量：—")
        self.lbl_hr = QLabel("心率：—")
        self.lbl_lead = QLabel("电极：—")
        self.lbl_frames = QLabel("数据批次：0（坏 0）")
        for w in (self.lbl_battery, self.lbl_hr, self.lbl_lead, self.lbl_frames):
            w.setFont(mono_font())
            status.addWidget(w)
        status.addStretch(1)
        root.addLayout(status)

        # ---- 中部：波形 + 右侧面板 ----
        mid = QHBoxLayout()
        pg.setConfigOptions(antialias=False, background="#FFFFFF",
                            foreground="#14171C")
        self.plot1 = pg.PlotWidget(title="通道1（去直流显示）")
        self.plot2 = pg.PlotWidget(title="通道2（去直流显示）")
        self._empty_hints = []
        for p in (self.plot1, self.plot2):
            p.showGrid(x=True, y=True, alpha=0.18)
            p.getAxis("bottom").setPen(LINE)
            p.getAxis("left").setPen(LINE)
            p.setLabel("bottom", "时间", units="s")
            p.disableAutoRange()      # 范围由软件按数据精确控制
            p.setMenuEnabled(False)   # 禁掉右键菜单，避免误操作后视图漂移
        # 两通道 X/Y 全联动：时间窗一致、幅度刻度一致，波形可直接对比
        self.plot2.setXLink(self.plot1)
        self.plot2.setYLink(self.plot1)
        self.plot1.setXRange(0, 10, padding=0)
        self.plot1.setYRange(-1, 1, padding=0)
        for p in (self.plot1, self.plot2):
            self._empty_hints.append(PlotHint("等待设备数据…", p))
            self._empty_hints[-1].hide()
        self.curve1 = self.plot1.plot(pen=pg.mkPen(WAVE_CH1, width=1))
        self.curve2 = self.plot2.plot(pen=pg.mkPen(WAVE_CH2, width=1))
        for c in (self.curve1, self.curve2):
            c.setDownsampling(auto=True, method="peak")
            c.setClipToView(True)

        waves = QVBoxLayout()
        wave_bar = QHBoxLayout()
        self.btn_pause = QPushButton("暂停显示")
        self.btn_pause.setToolTip("暂停滚动后可用鼠标滚轮/拖动放大查看细节")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.set_paused)
        self.btn_clear = QPushButton("清空数据")
        self.btn_clear.setProperty("variant", "danger")
        self.btn_clear.setToolTip("清空当前屏幕显示的波形和统计（不影响正在进行的录制）")
        self.btn_clear.clicked.connect(self.clear_display)
        lbl_win = QLabel("时间窗")
        self.cmb_window = QComboBox()
        for name, _ in DISPLAY_SECONDS:
            self.cmb_window.addItem(name)
        self.cmb_window.setCurrentIndex(1)
        self.cmb_window.currentIndexChanged.connect(
            lambda _: self.refresh_plots())
        wave_bar.addWidget(self.btn_pause)
        wave_bar.addWidget(self.btn_clear)
        wave_bar.addStretch(1)
        wave_bar.addWidget(lbl_win)
        wave_bar.addWidget(self.cmb_window)
        waves.addLayout(wave_bar)
        waves.addWidget(self.plot1, stretch=1)
        waves.addWidget(self.plot2, stretch=1)
        mid.addLayout(waves, stretch=5)

        side = QVBoxLayout()
        side.addWidget(self._build_control_group())
        side.addWidget(self._build_record_group())
        side.addStretch(1)
        mid.addLayout(side, stretch=1)
        root.addLayout(mid, stretch=1)

        # ---- 底部：日志 ----
        self.txt_log = QPlainTextEdit()
        self.txt_log.setObjectName("logPanel")
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
        self.btn_apply.setProperty("variant", "primary")
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
        self.btn_record.setProperty("variant", "danger")
        self.btn_record.clicked.connect(self.toggle_record)
        self.lbl_rec = QLabel("未在录制")
        self.lbl_rec.setProperty("muted", True)
        self.btn_analyze_last = QPushButton("分析最近一次录制")
        self.btn_analyze_last.setProperty("variant", "accent")
        self.btn_analyze_last.clicked.connect(self.analyze_last)
        self.btn_records = QPushButton("录制记录…")
        self.btn_records.clicked.connect(self.open_recordings)
        lay.addWidget(self.btn_record, 0, 0)
        lay.addWidget(self.lbl_rec, 0, 1)
        lay.addWidget(self.btn_analyze_last, 1, 0, 1, 2)
        lay.addWidget(self.btn_records, 2, 0, 1, 2)
        return g

    # ================================================================ 数据流

    def on_batch(self, batch: dict) -> None:
        self.batch_count += 1
        self._last_batch = batch
        self.ring1.append(batch["ch1"])
        self.ring2.append(batch["ch2"])
        if self.recorder.active:
            self.recorder.append(batch)

    def _start_generator(self) -> None:
        self.generator = DemoSource()
        self.parser.filter_ch1 = False
        self.parser.filter_ch2 = False
        self._gen_timer.start()

    def _on_generator_tick(self) -> None:
        if self.generator is None:
            return
        for batch in self.generator.next_batches(20):
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
        for i in range(self.cmb_device.count()):
            if self.cmb_device.itemData(i) == addr:
                return
        self.cmb_device.addItem(f"{name}（{addr}）", addr)
        self.cmb_device.setCurrentIndex(self.cmb_device.count() - 1)

    def on_ble_state(self, state: str, msg: str) -> None:
        self._last_ble_cmd = None
        self.on_link_state(state, msg)

    def on_serial_state(self, state: str, msg: str) -> None:
        self._last_serial_cmd = None
        self.on_link_state(state, msg)

    def on_link_state(self, state: str, msg: str) -> None:
        colors = {ST_IDLE: QUIET, ST_SCANNING: WARNING, ST_CONNECTING: WARNING,
                  ST_CONNECTED: SUCCESS, ST_DISCONNECTED: DANGER}
        dot = "●"
        names = {ST_IDLE: "未连接", ST_SCANNING: "扫描中", ST_CONNECTING: "连接中",
                 ST_CONNECTED: "已连接", ST_DISCONNECTED: "连接断开"}
        label = names.get(state, state)
        self.lbl_state.setText(f"{dot} {label}")
        self.lbl_state.setStyleSheet(
            f"color:{colors.get(state, QUIET)}; font-weight:bold;")
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

    # ================================================================ 设备设置

    def _send_device_command(self, ch1: int, ch2: int, sr: int,
                             f1: int, f2: int, sw: int) -> bool:
        """下发6字节设置命令；与最近一次已下发的完全一致时不重复发送。

        连续点击「应用设置/暂停数据流」但配置没变时，设备不会再收到
        重复命令，也就不会重复重置滤波导致波形抖动。
        返回是否真的发送了。
        """
        data = bytes((ch1 & 0xFF, ch2 & 0xFF, sr & 0xFF,
                      f1 & 0xFF, f2 & 0xFF, sw & 0xFF))
        attr = "_last_serial_cmd" if self.serial_mode else "_last_ble_cmd"
        if getattr(self, attr, None) == data:
            self.log("设置与设备当前一致，未重复下发。")
            return False
        setattr(self, attr, data)
        if self.serial_mode:
            self.serial.send_command(ch1, ch2, sr, f1, f2, sw)
        else:
            self.ble.send_command(ch1, ch2, sr, f1, f2, sw)
        return True

    def apply_settings(self) -> None:
        if self.generator is not None:
            self.log("内部信号源运行中，设置不会发给真实设备。")
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

        self._settings_snapshot = {
            "gain": name_g, "ch1set": f"0x{ch1set:02X}",
            "ch2set": f"0x{ch2set:02X}", "sample_rate": f"{fs:.0f}Hz",
            "filter_ch1": bool(f1), "filter_ch2": bool(f2),
        }
        self._send_device_command(ch1set, ch2set, sr_code, f1, f2, 1)

    def stop_stream(self) -> None:
        if self.generator is not None:
            return
        gi = max(0, self.cmb_gain.currentIndex())
        _, ch1set, ch2set = GAINS[gi]
        si = max(0, self.cmb_sr.currentIndex())
        _, sr_code, _ = SAMPLE_RATES[si]
        if self._send_device_command(
                ch1set, ch2set, sr_code,
                1 if self.chk_f1.isChecked() else 0,
                1 if self.chk_f2.isChecked() else 0, 0):
            self.log("已通知设备暂停发送数据。")

    # ================================================================ 波形

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.btn_pause.setText("继续显示" if paused else "暂停显示")
        if not paused:
            self.refresh_plots()

    def clear_display(self) -> None:
        self.ring1.clear()
        self.ring2.clear()
        self.parser.reset_stats()
        self.batch_count = 0
        self._last_batch = None
        self.curve1.setData([])
        self.curve2.setData([])
        self.lbl_battery.setText("电量：—")
        self.lbl_hr.setText("心率：—")
        self.lbl_lead.setText("电极：—")
        self.lbl_frames.setText("数据批次：0（坏 0）")
        if self.recorder.active:
            self.log("已清空屏幕显示。正在进行的录制不受影响，会继续保存。")
        else:
            self.log("已清空屏幕显示和统计数据。")

    def refresh_plots(self) -> None:
        """显示规则：X轴固定为最新时间窗；两通道共用同一Y刻度。

        - 两通道来自同一路数据流，X/Y 全联动：时间窗一致、幅度刻度
          一致，通道间的幅度大小可以直接对比。
        - 显示时减去各自可见窗口的中位值（去直流），波形围绕0显示；
          只影响显示，录制保存的仍是原始数据。
        - 没有数据时绘图区用浅灰底 + "等待设备数据"提示，不显示空白。
        - 暂停显示时不动视图，可用鼠标自由缩放细看。
        """
        if self.paused:
            return
        secs = DISPLAY_SECONDS[max(0, self.cmb_window.currentIndex())][1]
        n = int(self.fs * secs)
        g1, d1 = self.ring1.tail(n)
        g2, d2 = self.ring2.tail(n)

        if len(d1) == 0 and len(d2) == 0:
            for p, hint in zip((self.plot1, self.plot2), self._empty_hints):
                if not hint.isVisible():
                    p.setBackground(SURFACE_SUBTLE)
                    hint.show()
                    p.setXRange(0, 10, padding=0)
                    p.setYRange(-1, 1, padding=0)
            return
        for p, hint in zip((self.plot1, self.plot2), self._empty_hints):
            if hint.isVisible():
                p.setBackground("#FFFFFF")
                hint.hide()

        x1 = (g1 + np.arange(len(d1))) / self.fs
        disp1 = d1 - float(np.median(d1)) if len(d1) else d1
        disp2 = d2 - float(np.median(d2)) if len(d2) else d2
        self.curve1.setData(x1, disp1)
        self.curve2.setData(x1[-len(d2):] if len(d2) else x1[:0], disp2)

        # 两通道合并计算统一Y范围（Y已联动，只需设在plot1上）
        ymins, ymaxs = [], []
        for d in (disp1, disp2):
            if len(d):
                ymins.append(float(d.min()))
                ymaxs.append(float(d.max()))
        ymin, ymax = min(ymins), max(ymaxs)
        if ymin >= ymax:
            pad = abs(ymin) * 0.1 + 1e-6
        else:
            pad = (ymax - ymin) * 0.15
        self.plot1.setXRange(x1[0], x1[-1], padding=0)
        self.plot1.setYRange(ymin - pad, ymax + pad, padding=0)

    def refresh_status(self) -> None:
        b = self._last_batch
        if b is not None:
            batt = b["battery"]
            self.lbl_battery.setText(
                f"电量：{batt}%" if batt is not None else "电量：—")
            self.lbl_hr.setText(f"心率：{b['heart_rate']} bpm")
            if b["lead_off"]:
                self.lbl_lead.setText("电极：脱落！")
                self.lbl_lead.setStyleSheet(f"color:{DANGER}; font-weight:bold;")
            elif self.serial_mode and self.ble._state != ST_CONNECTED:
                self.lbl_lead.setText("电极：—（串口不提供）")
                self.lbl_lead.setStyleSheet(f"color:{QUIET};")
            else:
                self.lbl_lead.setText("电极：正常")
                self.lbl_lead.setStyleSheet(f"color:{SUCCESS};")
        self.lbl_frames.setText(
            f"数据批次：{self.batch_count}（坏 {self.parser.frames_bad}）")
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
            self.lbl_rec.setText(
                f"已保存（{folder.name if folder else '未录制'}）")
            self.cmb_gain.setEnabled(True)
            self.cmb_sr.setEnabled(True)
            self.btn_analyze_last.setEnabled(True)
            return
        if self.generator is None and not (self.ble._state == ST_CONNECTED
                                           or self.serial.isRunning()):
            QMessageBox.information(
                self, "无法录制",
                "还没有数据来源：请先连接设备（蓝牙或串口）。")
            return
        settings = getattr(self, "_settings_snapshot", None) or {
            "gain": GAINS[max(0, self.cmb_gain.currentIndex())][0],
            "sample_rate": f"{self.fs:.0f}Hz",
            "filter_ch1": self.chk_f1.isChecked(),
            "filter_ch2": self.chk_f2.isChecked(),
        }
        folder = self.recorder.start(
            fs=self.fs,
            source="generator" if self.generator is not None
            else ("serial" if self.serial_mode else "ble"),
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

    def open_recordings(self) -> None:
        win = RecordingsWindow(self)
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.destroyed.connect(lambda _=None: self._forget_window(win, record=True))
        win.show()
        win.reload()

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

    def _forget_window(self, w, record: bool = False) -> None:
        if w in self.analysis_windows:
            self.analysis_windows.remove(w)
        if record:
            self._record_windows = [x for x in getattr(self, "_record_windows", [])
                                    if x is not w]

    def is_open_in_analysis(self, folder: Path) -> bool:
        return any(getattr(w, "folder", None) == folder
                   for w in self.analysis_windows)

    # ================================================================ 其他

    def log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{stamp}] {msg}")

    def closeEvent(self, event) -> None:
        if self.recorder.active:
            self.recorder.stop()
        self._gen_timer.stop()
        self.serial.disconnect()
        self.serial.wait(2000)
        self.ble.shutdown()
        self.ble.wait(2000)
        super().closeEvent(event)

"""录制记录管理窗口：查看 / 重命名备注 / 删除 / 分析 / 打开所在文件夹。"""

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QInputDialog, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import recorder as rec


class RecordingsWindow(QMainWindow):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("录制记录")
        self.resize(760, 480)
        self.sessions = []

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["名称", "开始时间", "时长", "来源"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self.analyze_selected())
        lay.addWidget(self.table, stretch=1)

        btns = QHBoxLayout()
        for text, slot in (
            ("分析", self.analyze_selected),
            ("重命名备注", self.rename_selected),
            ("删除", self.delete_selected),
            ("打开文件夹", self.open_folder),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        btns.addWidget(b_close)
        lay.addLayout(btns)

    # ---------------------------------------------------------------- 数据

    def reload(self) -> None:
        self.sessions = rec.list_sessions(self.main.sessions_dir)
        self.table.setRowCount(len(self.sessions))
        for row, s in enumerate(self.sessions):
            meta = s["meta"]
            items = [
                s["name"],
                meta.get("started_at", "—"),
                f"{s['duration_s'] / 60:.1f} 分钟",
                {"ble": "蓝牙", "serial": "串口",
                 "generator": "内部信号", "demo": "演示"}.get(
                    meta.get("source", ""), meta.get("source", "—")),
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                if col == 0 and meta.get("name"):
                    item.setToolTip(f"文件夹：{s['folder'].name}")
                self.table.setItem(row, col, item)
        if self.sessions:
            self.table.selectRow(0)

    def _selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.sessions):
            return self.sessions[row]
        return None

    # ---------------------------------------------------------------- 操作

    def analyze_selected(self) -> None:
        s = self._selected()
        if s is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一条录制。")
            return
        self.main.open_analysis(s["folder"])

    def rename_selected(self) -> None:
        s = self._selected()
        if s is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一条录制。")
            return
        name, ok = QInputDialog.getText(
            self, "重命名备注", "给这次录制起个好认的名字（只改显示名，不动数据）：",
            text=s["name"])
        if not ok:
            return
        try:
            rec.set_session_name(s["folder"], name)
        except Exception as exc:
            QMessageBox.critical(self, "失败", f"重命名失败：{exc}")
            return
        self.reload()

    def delete_selected(self) -> None:
        s = self._selected()
        if s is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一条录制。")
            return
        folder: Path = s["folder"]
        if self.main.is_open_in_analysis(folder):
            QMessageBox.warning(
                self, "无法删除", "这次录制的分析窗口还开着，请先关闭它再删除。")
            return
        if self.main.recorder.folder == folder:
            QMessageBox.warning(self, "无法删除", "正在录制中，不能删除当前录制。")
            return
        ans = QMessageBox.question(
            self, "确认删除",
            f"确定要删除这条录制吗？\n\n{s['name']}\n{folder}\n\n"
            "里面的波形数据和已有分析结果都会一起删除，无法恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        try:
            rec.delete_session(folder)
        except Exception as exc:
            QMessageBox.critical(self, "失败", f"删除失败：{exc}")
            return
        if self.main.last_session == folder:
            self.main.last_session = None
        self.reload()

    def open_folder(self) -> None:
        s = self._selected()
        if s is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一条录制。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(s["folder"])))

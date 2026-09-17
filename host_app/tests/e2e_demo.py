"""端到端验证：演示模式 → 波形流动 → 录制40秒 → 分析 → 导出 → 截图。

运行: python tests/e2e_demo.py
会短暂弹出主窗口和分析窗口（自动操作，无需人工点击），结束后打印
E2E_OK 并把界面截图保存到 tests/e2e_shots/。
"""
import os
import shutil
import sys
import tempfile

# 端到端测试的数据目录重定向到临时目录（不污染真实"文档\心电HRV数据"）
TEST_DATA_DIR = os.path.join(tempfile.mkdtemp(prefix="hearthrv_e2e_"))
os.environ["HEARTHRV_DATA_DIR"] = TEST_DATA_DIR

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ui.analysis_window import AnalysisWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_shots")
os.makedirs(SHOTS, exist_ok=True)

app = QApplication(sys.argv)
win = MainWindow(generator_on_start=True)
win.show()

state = {"step": 0, "folder": None, "aw": None}


def fail(msg):
    print("E2E_FAIL:", msg)
    app.exit(2)


def step():
    s = state["step"]
    try:
        if s == 0:
            if win.batch_count < 50:
                return fail("演示数据没有流动")
            win.grab().save(os.path.join(SHOTS, "1_主界面_演示波形.png"))
            win.toggle_record()
            if not win.recorder.active:
                return fail("录制没有开始")
            state["step"] = 1
            QTimer.singleShot(40000, step)  # 录40秒（>30秒才能分析）
        elif s == 1:
            win.toggle_record()
            folder = win.last_session
            if folder is None or not (folder / "data.csv").exists():
                return fail("录制文件没有落盘")
            state["folder"] = folder
            aw = AnalysisWindow(folder)
            aw.show()
            aw.run_analysis()
            res = aw.result
            if res is None or res.error:
                return fail("分析失败: " + (res.error if res else "no result"))
            if res.time["n_beats"] < 30:
                return fail("有效心跳过少")
            if res.freq is not None:
                return fail("40秒数据不应计算频域指标")
            state["aw"] = aw
            state["step"] = 2
            QTimer.singleShot(1200, step)
        else:
            aw = state["aw"]
            aw.grab().save(os.path.join(SHOTS, "2_分析窗口.png"))
            QMessageBox.information = staticmethod(lambda *a, **k: None)
            aw.export_results()
            folder = state["folder"]
            expected = ["HRV指标.csv", "逐拍明细.csv", "分析解读.txt"]
            missing = [n for n in expected if not (folder / n).exists()]
            if missing:
                return fail("导出缺少文件: " + ",".join(missing))
            pngs = [p.name for p in folder.glob("HRV_图*.png")]
            print("导出的PNG:", pngs)
            if len(pngs) < 3:
                return fail("PNG导出数量不足")
            print("E2E_OK")
            print("session:", folder)
            app.exit(0)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        fail(str(exc))


QTimer.singleShot(2500, step)
app.exec()

# 清理端到端产生的全部测试数据（临时数据目录整个删掉）
shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
sys.exit(0 if state["step"] == 2 else 2)

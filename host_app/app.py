"""程序入口。

用法:
    HeartHRV.exe              正常启动
    HeartHRV.exe --selfcheck  自检：内部信号源跑几秒自动退出，结果同时
                              写到 数据目录/logs/selfcheck.txt（供云端
                              构建自动验证打包出的exe能否正常运行）
"""

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from core import paths
from core.version import APP_NAME, __version__
from ui.main_window import MainWindow


def _install_crash_handler() -> None:
    """打包成窗口程序后没有控制台，出错必须可见：写日志文件 + 弹窗提示。"""
    def handler(exc_type, exc, tb):
        try:
            log = paths.logs_dir() / f"崩溃日志_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            log.write_text(
                f"{APP_NAME} v{__version__}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                + "".join(traceback.format_exception(exc_type, exc, tb)),
                encoding="utf-8")
        except Exception:
            pass
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("程序出错了")
        msg.setText(
            f"{APP_NAME} 遇到问题需要关闭。\n\n"
            f"错误信息已保存到:\n{paths.logs_dir()}\n\n"
            f"如需帮助，请把该文件夹里的「崩溃日志」发给开发者。")
        msg.setDetailedText("".join(traceback.format_exception(exc_type, exc, tb)))
        msg.exec()

    sys.excepthook = handler


def main() -> int:
    _install_crash_handler()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("HeartHRV")
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(9)
    app.setFont(font)
    icon_path = paths.resource("app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    demo = False
    selfcheck = "--selfcheck" in sys.argv

    win = MainWindow(generator_on_start=demo or selfcheck)
    win.show()

    if selfcheck:
        secs = 5
        for i, a in enumerate(sys.argv):
            if a == "--selfcheck" and i + 1 < len(sys.argv):
                try:
                    secs = max(2, int(float(sys.argv[i + 1])))
                except ValueError:
                    pass
                break

        def report_and_quit():
            batches = win.batch_count
            samples = len(win.ring1.tail(10 ** 9)[1])
            ok = batches > 50 and samples > 1000
            print(f"SELFCHECK batches={batches} plot_samples={samples}")
            try:  # 无控制台（安装版）时以文件为准
                (paths.logs_dir() / "selfcheck.txt").write_text(
                    f"{'OK' if ok else 'FAIL'} batches={batches} "
                    f"plot_samples={samples}\n", encoding="utf-8")
            except Exception:
                pass
            # 先正常关窗（停录制、停蓝牙/串口线程），再退出，保证退出码干净
            win.close()
            app.exit(0 if ok else 3)

        QTimer.singleShot(int(secs * 1000), report_and_quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

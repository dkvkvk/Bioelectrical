"""界面主题：纸白背景、墨色信息、工程蓝交互。

设计语言要点（对齐项目前端规范）：
- 白底面板 + 1px 浅灰边界 + 8px 圆角，不使用常驻阴影和渐变；
- 主按钮墨色实底、次按钮白底灰边、危险按钮白底红字悬停红底；
- 状态色：成功绿/警告橙/危险红；数据、路径、时间用等宽字体；
- 标志性元素：模块路径标签（如 ACQ / LIVE），说明所在位置。
"""

from PySide6.QtGui import QColor, QFont

# ---- 主题令牌（与前端规范一致，禁止在界面代码里另配色）----
INK = "#14171C"          # 主文字
MUTED = "#68707C"        # 次文字
QUIET = "#9299A4"        # 弱文字（占位/禁用）
LINE = "#DFE3E8"         # 边界
LINE_STRONG = "#CBD1D8"  # 输入框边界
SURFACE = "#FFFFFF"      # 页面/面板底色
SURFACE_SUBTLE = "#F5F7F9"  # 表头/悬停/工具栏
ACCENT = "#2458D3"       # 交互蓝
ACCENT_SOFT = "#EDF2FF"  # 当前项背景
SUCCESS = "#167451"      # 成功/正常
WARNING = "#B96819"      # 警告
DANGER = "#C52F2F"       # 危险/失败

# 波形与图表用色（全部来自令牌）
WAVE_CH1 = ACCENT
WAVE_CH2 = "#16867D"     # 成功青，用于第二通道
MARK_R = DANGER          # R波标记
RR_LINE = ACCENT

FONT_UI = "Microsoft YaHei UI"
FONT_TITLE = "Bahnschrift SemiCondensed"   # 展示标题（中文回退雅黑）
FONT_MONO = "Consolas"                     # 数据/路径/时间

QSS = f"""
* {{
    font-family: "{FONT_UI}";
    outline: none;
}}
QMainWindow, QDialog {{
    background: {SURFACE};
}}
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
    color: {INK};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {INK};
}}
QLabel {{
    color: {INK};
    background: transparent;
}}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[pathtag="true"] {{
    font-family: "{FONT_MONO}";
    font-size: 12px;
    font-weight: 600;
    color: {ACCENT};
    background: {ACCENT_SOFT};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 1px 8px;
}}
QPushButton {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {LINE_STRONG};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {SURFACE_SUBTLE}; }}
QPushButton:pressed {{ background: {ACCENT_SOFT}; }}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{
    color: {QUIET};
    background: {SURFACE_SUBTLE};
    border-color: {LINE};
}}
QPushButton:checked {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton[variant="primary"] {{
    background: {INK};
    border: 1px solid {INK};
    color: {SURFACE};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: #2A3240; }}
QPushButton[variant="primary"]:disabled {{
    background: {QUIET};
    border-color: {QUIET};
    color: {SURFACE};
}}
QPushButton[variant="accent"] {{
    color: {ACCENT};
    border: 1px solid {ACCENT};
    background: {SURFACE};
}}
QPushButton[variant="accent"]:hover {{ background: {ACCENT_SOFT}; }}
QPushButton[variant="danger"] {{
    color: {DANGER};
    background: {SURFACE};
    border: 1px solid {LINE_STRONG};
}}
QPushButton[variant="danger"]:hover {{
    background: {DANGER};
    border-color: {DANGER};
    color: {SURFACE};
}}
QComboBox {{
    background: {SURFACE};
    border: 1px solid {LINE_STRONG};
    border-radius: 6px;
    padding: 4px 26px 4px 8px;
    color: {INK};
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: {QUIET}; background: {SURFACE_SUBTLE}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {LINE};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
QCheckBox {{ spacing: 6px; color: {INK}; }}
QPlainTextEdit {{
    background: {SURFACE_SUBTLE};
    border: 1px solid {LINE};
    border-radius: 6px;
    font-family: "{FONT_MONO}";
    font-size: 12px;
    color: {MUTED};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
QTableWidget {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 6px;
    gridline-color: {SURFACE_SUBTLE};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
QHeaderView::section {{
    background: {SURFACE_SUBTLE};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {LINE};
    border-right: 1px solid {SURFACE_SUBTLE};
    padding: 7px 8px;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {LINE_STRONG}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {LINE_STRONG}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {MUTED}; }}
QMessageBox, QInputDialog {{
    background: {SURFACE};
}}
"""


def apply_theme(app) -> None:
    """在 QApplication 上应用全局主题。"""
    font = QFont(FONT_UI)
    font.setPointSize(9)
    app.setFont(font)
    app.setStyleSheet(QSS)


def mono_font(point_size: int = 9) -> QFont:
    f = QFont(FONT_MONO)
    f.setPointSize(point_size)
    f.setStyleHint(QFont.Monospace)
    return f


def pathtag(text: str):
    """模块路径标签控件（标志性元素）：等宽、浅蓝底，说明所在位置。"""
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setProperty("pathtag", True)
    return lbl


def color(hex_str: str) -> QColor:
    return QColor(hex_str)

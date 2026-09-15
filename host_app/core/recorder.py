"""录制保存：每次录制在 sessions/日期_时间/ 目录里写三个文件——
data.csv   逐样本电压数据（分析用）
status.csv 每帧状态（电量/脱落/心率，备查）
meta.json  记录信息（采样率、增益、滤波、时长等）
"""

import csv
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np


class Recorder:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.folder: Optional[Path] = None
        self._data_f = None
        self._status_f = None
        self._data_w = None
        self._status_w = None
        self._n = 0
        self._frames = 0
        self._meta: dict = {}
        self._t0 = 0.0

    @property
    def active(self) -> bool:
        return self._data_f is not None

    def start(self, fs: float, source: str, settings: dict) -> Path:
        """开始一次新录制。settings 里应包含当前增益/采样率/滤波等设置。"""
        if self.active:
            self.stop()
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.folder = self.sessions_dir / time.strftime("%Y%m%d_%H%M%S")
        i = 1
        while self.folder.exists():  # 同一秒内重复开始的极端情况
            i += 1
            self.folder = self.sessions_dir / (
                time.strftime("%Y%m%d_%H%M%S") + f"_{i}")
        self.folder.mkdir(parents=True)

        self._data_f = open(self.folder / "data.csv", "w", newline="",
                            encoding="utf-8")
        self._data_w = csv.writer(self._data_f)
        self._data_w.writerow(["n", "ch1_v", "ch2_v"])
        self._status_f = open(self.folder / "status.csv", "w", newline="",
                              encoding="utf-8")
        self._status_w = csv.writer(self._status_f)
        self._status_w.writerow(["frame", "battery", "lead_off", "heart_rate"])

        self._n = 0
        self._frames = 0
        self._t0 = time.time()
        self._meta = {
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "fs": float(fs),
            "source": source,          # "ble" 或 "demo"
            "settings": settings,
        }
        return self.folder

    def append(self, batch: dict) -> None:
        """写入一个批次（每帧 4 个样本）。"""
        if not self.active:
            return
        for v1, v2 in zip(batch["ch1"], batch["ch2"]):
            self._data_w.writerow([self._n, f"{v1:.6f}", f"{v2:.6f}"])
            self._n += 1
        self._status_w.writerow([self._frames, batch["battery"],
                                 batch["lead_off"], batch["heart_rate"]]
                                if batch["battery"] is not None else
                                [self._frames, "", batch["lead_off"],
                                 batch["heart_rate"]])
        self._frames += 1
        # 每隔一会儿刷一次盘，程序意外退出时最多丢一点尾巴
        if self._frames % 125 == 0:
            self._data_f.flush()
            self._status_f.flush()

    def elapsed_s(self) -> float:
        return time.time() - self._t0 if self.active else 0.0

    def sample_count(self) -> int:
        return self._n

    def stop(self) -> Optional[Path]:
        """结束录制并落盘 meta，返回录制文件夹路径。"""
        if not self.active:
            return None
        duration = time.time() - self._t0
        self._meta["duration_s"] = round(duration, 2)
        self._meta["samples"] = self._n
        try:
            self._data_f.close()
            self._status_f.close()
        except Exception:
            pass
        self._data_f = self._status_f = None
        (self.folder / "meta.json").write_text(
            json.dumps(self._meta, ensure_ascii=False, indent=2),
            encoding="utf-8")
        folder = self.folder
        self.folder = None
        return folder


# ---------------------------------------------------------------- 读取

def load_session(folder) -> dict:
    """读取一次录制的全部数据。返回
    {fs, ch1, ch2, meta, duration_s}。"""
    folder = Path(folder)
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    arr = np.loadtxt(folder / "data.csv", delimiter=",", skiprows=1,
                     ndmin=2)
    fs = float(meta.get("fs", 500.0))
    return {
        "fs": fs,
        "ch1": arr[:, 1] if arr.size else np.array([]),
        "ch2": arr[:, 2] if arr.size else np.array([]),
        "meta": meta,
        "duration_s": (arr.shape[0] / fs) if arr.size else 0.0,
    }


def list_sessions(sessions_dir) -> list:
    """列出全部历史录制（新的在前），返回 [{folder, meta, duration_s, label}]。
    meta 缺失/数据为空的目录跳过。"""
    root = Path(sessions_dir)
    if not root.exists():
        return []
    out = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not (folder / "data.csv").exists():
            continue
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        n_rows = sum(1 for _ in open(folder / "data.csv", encoding="utf-8")) - 1
        fs = float(meta.get("fs", 500.0))
        if n_rows <= 0:
            continue
        name = meta.get("name") or folder.name
        out.append({
            "folder": folder,
            "meta": meta,
            "duration_s": n_rows / fs,
            "name": name,
            "label": f"{name}（{n_rows / fs / 60:.1f} 分钟）",
        })
    return out


def set_session_name(folder, name: str) -> None:
    """修改录制的显示名（写入 meta.json 的 name 字段，不动文件夹）。"""
    folder = Path(folder)
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta["name"] = name.strip() or folder.name
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_session(folder) -> None:
    """删除一次录制的全部文件（不可恢复，调用方需先确认）。"""
    import shutil
    shutil.rmtree(folder, ignore_errors=True)

"""录制模块测试：录制 → 落盘 → 读回，数据一致。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core import recorder as rec  # noqa: E402


def test_recorder_roundtrip():
    tmp = Path(tempfile.mkdtemp())
    try:
        r = rec.Recorder(tmp)
        folder = r.start(fs=500.0, source="demo",
                         settings={"gain": "360x", "sample_rate": "500Hz"})
        batches = [
            {"ch1": [1.0, 1.1, 1.2, 1.3], "ch2": [0.5, 0.5, 0.6, 0.6],
             "battery": 90, "lead_off": 0, "heart_rate": 70},
            {"ch1": [1.4, 1.5, 1.6, 1.7], "ch2": [0.7, 0.7, 0.8, 0.8],
             "battery": 90, "lead_off": 1, "heart_rate": 71},
        ]
        for b in batches:
            r.append(b)
        assert r.sample_count() == 8
        out = r.stop()
        assert out == folder and (folder / "meta.json").exists()

        loaded = rec.load_session(folder)
        assert loaded["fs"] == 500.0
        assert len(loaded["ch1"]) == 8
        assert abs(loaded["ch1"][0] - 1.0) < 1e-6
        assert abs(loaded["ch1"][7] - 1.7) < 1e-6
        assert loaded["meta"]["settings"]["gain"] == "360x"
        assert loaded["duration_s"] > 0

        sessions = rec.list_sessions(tmp)
        assert len(sessions) == 1 and sessions[0]["duration_s"] > 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("test_recorder 全部通过")

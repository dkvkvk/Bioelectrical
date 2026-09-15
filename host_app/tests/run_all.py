"""跑全部测试: python tests/run_all.py（或 cd tests && python run_all.py）"""
import glob
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

failed = []
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    name = os.path.splitext(os.path.basename(path))[0]
    print(f"\n===== {name} =====")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        traceback.print_exc()
        failed.append(name)
        continue
    tests = [(n, f) for n, f in sorted(vars(mod).items())
             if n.startswith("test_") and callable(f)]
    for n, f in tests:
        try:
            f()
            print(f"  PASS {n}")
        except Exception:
            traceback.print_exc()
            failed.append(f"{name}.{n}")

print("\n" + "=" * 46)
if failed:
    print("失败的测试:", ", ".join(failed))
    sys.exit(1)
print("全部测试通过 ✔")

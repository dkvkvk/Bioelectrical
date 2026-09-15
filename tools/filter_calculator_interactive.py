#!/usr/bin/env python3
"""
交互式滤波器系数计算器

自动询问用户需要的参数，无需命令行参数
"""

import sys
import numpy as np
from scipy import signal

# 默认参数
DEFAULT_NOTCH_FREQ = 50
DEFAULT_NOTCH_Q = 5
DEFAULT_LPF_CUTOFF = 100
DEFAULT_LPF_ORDER = 4
DEFAULT_BASELINE_WINDOW = 0.4

def ask_yes_no(question, default=True):
    """询问是/否问题"""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {hint}: ").strip().lower()
        if answer == '':
            return default
        if answer in ['y', 'yes', 'Y', '是']:
            return True
        if answer in ['n', 'no', 'N', '否']:
            return False
        print("请输入 y(是) 或 n(否)")

def ask_number(question, default, min_val=None, max_val=None):
    """询问数字"""
    while True:
        answer = input(f"{question} [默认: {default}]: ").strip()
        if answer == '':
            return default
        try:
            value = float(answer)
            if min_val is not None and value < min_val:
                print(f"错误：值必须 >= {min_val}")
                continue
            if max_val is not None and value > max_val:
                print(f"错误：值必须 <= {max_val}")
                continue
            return value
        except ValueError:
            print("错误：请输入有效的数字")

def ask_sample_rates():
    """询问采样率"""
    print("\n=== 采样率设置 ===")
    print("请输入需要计算滤波器系数的采样率（单位：Hz）")
    print("提示：心电(ECG)推荐500-1000Hz，肌电(EMG)推荐1000-2000Hz，脑电(EEG)推荐250-500Hz")
    print()

    fs_list = []

    # 询问常用采样率
    common_rates = [250, 500, 1000, 2000]
    print("常用采样率：")
    for rate in common_rates:
        if ask_yes_no(f"  是否需要 {rate}Hz?", default=False):
            fs_list.append(rate)

    # 询问是否添加自定义采样率
    if ask_yes_no("\n是否需要添加其他采样率?", default=False):
        while True:
            custom = ask_number("请输入采样率（Hz）", 500, min_val=1)
            fs_list.append(int(custom))
            if not ask_yes_no("继续添加?", default=False):
                break

    if not fs_list:
        print("未选择任何采样率，使用默认: 250, 500, 1000 Hz")
        fs_list = [250, 500, 1000]

    return sorted(list(set(fs_list)))

def ask_filter_params():
    """询问滤波器参数"""
    print("\n=== 滤波器参数设置 ===")

    if ask_yes_no("是否使用默认滤波器参数?", default=True):
        print(f"  - 陷波频率: {DEFAULT_NOTCH_FREQ}Hz (去除工频干扰)")
        print(f"  - 陷波Q值: {DEFAULT_NOTCH_Q} (带宽约{DEFAULT_NOTCH_FREQ/DEFAULT_NOTCH_Q:.1f}Hz)")
        print(f"  - 低通截止: {DEFAULT_LPF_CUTOFF}Hz (保留生物电信号)")
        print(f"  - 低通阶数: {DEFAULT_LPF_ORDER}阶")
        print(f"  - 基线窗口: {DEFAULT_BASELINE_WINDOW}秒")
        return {
            'notch_freq': DEFAULT_NOTCH_FREQ,
            'notch_q': DEFAULT_NOTCH_Q,
            'lpf_cutoff': DEFAULT_LPF_CUTOFF,
            'lpf_order': DEFAULT_LPF_ORDER,
            'baseline_window': DEFAULT_BASELINE_WINDOW
        }

    print("\n自定义参数：")
    notch_freq = ask_number("陷波中心频率（Hz）", DEFAULT_NOTCH_FREQ, min_val=1)
    notch_q = ask_number("陷波Q值（越大带宽越窄）", DEFAULT_NOTCH_Q, min_val=1)
    lpf_cutoff = ask_number("低通截止频率（Hz）", DEFAULT_LPF_CUTOFF, min_val=1)
    lpf_order = int(ask_number("低通滤波器阶数（偶数）", DEFAULT_LPF_ORDER, min_val=2))
    baseline_window = ask_number("基线漂移窗口（秒）", DEFAULT_BASELINE_WINDOW, min_val=0.1)

    return {
        'notch_freq': notch_freq,
        'notch_q': notch_q,
        'lpf_cutoff': lpf_cutoff,
        'lpf_order': lpf_order,
        'baseline_window': baseline_window
    }

def format_coeff_array(name, coeffs_list, fs_list):
    """格式化为 C 语言二维数组"""
    lines = []
    lines.append(f"// {name} - {len(fs_list)} sample rates")
    lines.append(f"static const double {name}[{len(fs_list)}][3] = {{")

    for i, (coeffs, fs) in enumerate(zip(coeffs_list, fs_list)):
        comment = f"  // fs={fs}Hz"
        lines.append(f"    {{{coeffs[0]:.18e}, {coeffs[1]:.18e}, {coeffs[2]:.18e}}},{comment}")

    lines.append("};")
    return "\n".join(lines)

def format_gain_array(name, gains, fs_list):
    """格式化为 C 语言一维数组（增益）"""
    lines = []
    lines.append(f"static const double {name}[{len(fs_list)}] = {{")

    for i, (gain, fs) in enumerate(zip(gains, fs_list)):
        comment = f"  // fs={fs}Hz"
        lines.append(f"    {gain:.18e},{comment}")

    lines.append("};")
    return "\n".join(lines)

def calculate_filters(fs_list, params):
    """计算所有采样率的滤波器系数"""

    print("\n" + "=" * 80)
    print("生物电信号滤波器系数计算结果")
    print("=" * 80)
    print(f"采样率: {fs_list} Hz")
    print()
    print("滤波器设计参数:")
    print(f"  - 陷波中心频率: {params['notch_freq']}Hz (去除工频干扰)")
    print(f"  - 陷波品质因数Q: {params['notch_q']} (带宽约{params['notch_freq']/params['notch_q']:.1f}Hz)")
    print(f"  - 低通截止频率: {params['lpf_cutoff']}Hz (保留生物电信号频段)")
    print(f"  - 低通滤波器阶数: {params['lpf_order']}阶 Butterworth (衰减{params['lpf_order']*6}dB/octave)")
    print(f"  - 基线漂移窗口: {params['baseline_window']}秒")
    print("=" * 80)
    print()

    # ========== 50Hz 陷波滤波器 ==========
    print("// ========== 陷波滤波器 (IIR Notch Filter) ==========")
    print(f"// 作用: 去除{params['notch_freq']}Hz干扰")
    print(f"// Q值: {params['notch_q']} (带宽约{params['notch_freq']/params['notch_q']:.1f}Hz)")
    print("//")
    print()

    notch_b_list = []
    notch_a_list = []

    for fs in fs_list:
        if params['notch_freq'] >= fs / 2:
            print(f"// fs={fs}Hz: 警告！陷波频率{params['notch_freq']}Hz超过奈奎斯特频率({fs/2}Hz)")

        b, a = signal.iirnotch(params['notch_freq'], params['notch_q'], fs)
        notch_b_list.append(b)
        notch_a_list.append(a)

        bandwidth = params['notch_freq'] / params['notch_q']
        f_low = params['notch_freq'] - bandwidth / 2
        f_high = params['notch_freq'] + bandwidth / 2

        print(f"// fs={fs}Hz, f0={params['notch_freq']}Hz, Q={params['notch_q']}")
        print(f"//   带宽: {bandwidth:.2f}Hz (约{f_low:.1f}-{f_high:.1f}Hz)")
        print(f"//   b = [{b[0]:.6f}, {b[1]:.6f}, {b[2]:.6f}]")
        print(f"//   a = [{a[0]:.6f}, {a[1]:.6f}, {a[2]:.6f}]")
        print()

    print(format_coeff_array("IIR_NOTCH_B", notch_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_NOTCH_A", notch_a_list, fs_list))
    print()
    print()

    # ========== 低通滤波器 ==========
    print("// ========== 低通滤波器 (Butterworth LPF) ==========")
    print(f"// 作用: 去除高频噪声，保留0-{params['lpf_cutoff']}Hz信号")
    print(f"// 类型: {params['lpf_order']}阶 Butterworth")
    print(f"// 截止频率: {params['lpf_cutoff']}Hz (-3dB点)")
    print("//")
    print()

    sos1_b_list = []
    sos1_a_list = []
    sos1_gain_list = []

    sos2_b_list = []
    sos2_a_list = []
    sos2_gain_list = []

    for fs in fs_list:
        if params['lpf_cutoff'] >= fs / 2:
            print(f"// fs={fs}Hz: 警告！截止频率{params['lpf_cutoff']}Hz超过奈奎斯特频率({fs/2}Hz)")
            sos1_b_list.append([1.0, 0.0, 0.0])
            sos1_a_list.append([1.0, 0.0, 0.0])
            sos1_gain_list.append(1.0)
            sos2_b_list.append([1.0, 0.0, 0.0])
            sos2_a_list.append([1.0, 0.0, 0.0])
            sos2_gain_list.append(1.0)
            print()
            continue

        sos = signal.butter(params['lpf_order'], params['lpf_cutoff'], btype='low', fs=fs, output='sos')

        b0, b1, b2, a0, a1, a2 = sos[0]
        gain1 = b0 / a0
        sos1_b_list.append([1.0, b1/b0, b2/b0])
        sos1_a_list.append([1.0, a1/a0, a2/a0])
        sos1_gain_list.append(gain1)

        b0, b1, b2, a0, a1, a2 = sos[1]
        gain2 = b0 / a0
        sos2_b_list.append([1.0, b1/b0, b2/b0])
        sos2_a_list.append([1.0, a1/a0, a2/a0])
        sos2_gain_list.append(gain2)

        print(f"// fs={fs}Hz, cutoff={params['lpf_cutoff']}Hz")
        print(f"//   Section 1: gain={gain1:.6f}")
        print(f"//   Section 2: gain={gain2:.6f}")
        print()

    print(format_coeff_array("IIR_LPF_B", sos1_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_LPF_A", sos1_a_list, fs_list))
    print()
    print(format_gain_array("IIR_LPF_Gain", sos1_gain_list, fs_list))
    print()
    print()

    print(format_coeff_array("IIR_LPF_B1", sos2_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_LPF_A1", sos2_a_list, fs_list))
    print()
    print(format_gain_array("IIR_LPF_Gain1", sos2_gain_list, fs_list))
    print()
    print()

    # ========== 移动平均滤波器参数 ==========
    print("// ========== 移动平均滤波器参数 ==========")
    print()

    M_list = [int(fs / params['notch_freq']) for fs in fs_list]
    Q_list = [int(fs * params['baseline_window']) for fs in fs_list]

    for i, fs in enumerate(fs_list):
        print(f"// fs={fs}Hz: M={M_list[i]} ({M_list[i]/fs*1000:.2f}ms), Q={Q_list[i]} ({Q_list[i]/fs:.2f}s)")

    print()
    print(f"static const int M_TABLE[{len(fs_list)}] = {{", ", ".join(str(m) for m in M_list), "};")
    print(f"static const int Q_TABLE[{len(fs_list)}] = {{", ", ".join(str(q) for q in Q_list), "};")
    print(f"#define MAX_M {max(M_list)}")
    print(f"#define MAX_Q {max(Q_list)}")
    print()

def main():
    print("=" * 80)
    print("交互式滤波器系数计算器")
    print("生物电信号采集系统专用")
    print("=" * 80)

    # 询问采样率
    fs_list = ask_sample_rates()

    # 询问滤波器参数
    params = ask_filter_params()

    # 询问是否保存到文件
    print()
    if ask_yes_no("是否将结果保存到文件?", default=False):
        filename = input("请输入文件名 [filter_coeffs.txt]: ").strip()
        if not filename:
            filename = "filter_coeffs.txt"

        # 重定向输出到文件
        original_stdout = sys.stdout
        with open(filename, 'w', encoding='utf-8') as f:
            sys.stdout = f
            calculate_filters(fs_list, params)
        sys.stdout = original_stdout

        print(f"\n结果已保存到: {filename}")
        print("提示：直接复制文件中的C代码到你的项目中即可使用！")
    else:
        # 直接输出
        calculate_filters(fs_list, params)

    print("\n计算完成！")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户取消操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n错误: {e}")
        sys.exit(1)

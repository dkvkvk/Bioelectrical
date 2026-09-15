#!/usr/bin/env python3
"""
通用滤波器系数计算器 - 生物电信号采集系统

用法：
    python filter_calculator.py [采样率1] [采样率2] [采样率3] ...

示例：
    python filter_calculator.py 250 500 1000
    python filter_calculator.py 500
    python filter_calculator.py 125 250 500 1000 2000

输出C语言格式的滤波器系数，包括：
1. 50Hz 陷波滤波器 (IIR notch filter, Q=5)
   - 作用：去除工频干扰（市电50Hz及其谐波）
   - Q值=5：带宽约10Hz（45-55Hz衰减约-20dB）

2. 100Hz 低通滤波器 (4阶 Butterworth)
   - 作用：去除高频噪声，保留有效信号频段（0-100Hz）
   - 截止频率：100Hz（-3dB点）
   - 阻带衰减：>100Hz区域衰减约-24dB/octave

3. 移动平均滤波器参数
   - 50Hz陷波窗口（M）：去除工频干扰
   - 基线漂移窗口（Q）：去除直流漂移（保持0.4秒窗口）
"""

import sys
import numpy as np
from scipy import signal

# 滤波器设计参数
NOTCH_FREQ = 50      # 陷波中心频率（Hz）- 中国工频
NOTCH_Q = 5          # 陷波品质因数 - Q越大带宽越窄
LPF_CUTOFF = 100     # 低通截止频率（Hz）- 保留心电等生物电信号频段
LPF_ORDER = 4        # 低通滤波器阶数
BASELINE_WINDOW = 0.4  # 基线漂移窗口时间（秒）

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

def calculate_filters(fs_list):
    """计算所有采样率的滤波器系数"""

    print("=" * 80)
    print(f"生物电信号滤波器系数计算")
    print("=" * 80)
    print(f"采样率: {fs_list} Hz")
    print()
    print("滤波器设计参数:")
    print(f"  - 陷波中心频率: {NOTCH_FREQ}Hz (去除工频干扰)")
    print(f"  - 陷波品质因数Q: {NOTCH_Q} (带宽约{NOTCH_FREQ/NOTCH_Q:.1f}Hz)")
    print(f"  - 低通截止频率: {LPF_CUTOFF}Hz (保留生物电信号频段)")
    print(f"  - 低通滤波器阶数: {LPF_ORDER}阶 Butterworth (衰减{LPF_ORDER*6}dB/octave)")
    print(f"  - 基线漂移窗口: {BASELINE_WINDOW}秒")
    print("=" * 80)
    print()

    # ========== 50Hz 陷波滤波器 ==========
    print("// ========== 50Hz 陷波滤波器 (IIR Notch Filter) ==========")
    print(f"// 作用: 去除工频干扰 ({NOTCH_FREQ}Hz及其谐波)")
    print(f"// Q值: {NOTCH_Q} (带宽约{NOTCH_FREQ/NOTCH_Q:.1f}Hz，即{NOTCH_FREQ-NOTCH_FREQ/NOTCH_Q/2:.1f}-{NOTCH_FREQ+NOTCH_FREQ/NOTCH_Q/2:.1f}Hz区域衰减)")
    print("//")
    print()

    notch_b_list = []
    notch_a_list = []

    for fs in fs_list:
        # 检查陷波频率是否在有效范围内
        if NOTCH_FREQ >= fs / 2:
            print(f"// fs={fs}Hz: 警告！陷波频率{NOTCH_FREQ}Hz超过奈奎斯特频率({fs/2}Hz)")
            print(f"//           陷波滤波器可能无法正常工作！")

        b, a = signal.iirnotch(NOTCH_FREQ, NOTCH_Q, fs)
        notch_b_list.append(b)
        notch_a_list.append(a)

        # 计算实际带宽
        bandwidth = NOTCH_FREQ / NOTCH_Q
        f_low = NOTCH_FREQ - bandwidth / 2
        f_high = NOTCH_FREQ + bandwidth / 2

        print(f"// fs={fs}Hz, f0={NOTCH_FREQ}Hz, Q={NOTCH_Q}")
        print(f"//   带宽: {bandwidth:.2f}Hz (约{f_low:.1f}-{f_high:.1f}Hz)")
        print(f"//   b = [{b[0]:.6f}, {b[1]:.6f}, {b[2]:.6f}]")
        print(f"//   a = [{a[0]:.6f}, {a[1]:.6f}, {a[2]:.6f}]")
        print()

    print(format_coeff_array("IIR_50HZ_B", notch_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_50HZ_A", notch_a_list, fs_list))
    print()
    print()

    # ========== 100Hz 低通滤波器 ==========
    print("// ========== 100Hz 低通滤波器 (Butterworth LPF) ==========")
    print(f"// 作用: 去除高频噪声，保留有效生物电信号频段 (0-{LPF_CUTOFF}Hz)")
    print(f"// 类型: {LPF_ORDER}阶 Butterworth (最平坦通带响应)")
    print(f"// 截止频率: {LPF_CUTOFF}Hz (-3dB点)")
    print(f"// 阻带衰减: {LPF_ORDER*6}dB/octave (>{LPF_CUTOFF}Hz快速衰减)")
    print(f"// 实现: 拆分为2个双二阶节级联 (Second-Order Sections)")
    print("//")
    print()

    sos1_b_list = []
    sos1_a_list = []
    sos1_gain_list = []

    sos2_b_list = []
    sos2_a_list = []
    sos2_gain_list = []

    for fs in fs_list:
        # 检查是否可以设计低通滤波器
        if LPF_CUTOFF >= fs / 2:
            print(f"// fs={fs}Hz: 警告！截止频率{LPF_CUTOFF}Hz超过奈奎斯特频率({fs/2}Hz)")
            print(f"//           低通滤波器无法设计，使用全通滤波器（无滤波效果）")
            # 使用单位增益的通过滤波器
            sos1_b_list.append([1.0, 0.0, 0.0])
            sos1_a_list.append([1.0, 0.0, 0.0])
            sos1_gain_list.append(1.0)
            sos2_b_list.append([1.0, 0.0, 0.0])
            sos2_a_list.append([1.0, 0.0, 0.0])
            sos2_gain_list.append(1.0)
            print()
            continue

        sos = signal.butter(LPF_ORDER, LPF_CUTOFF, btype='low', fs=fs, output='sos')

        # 第一个双二阶节
        b0, b1, b2, a0, a1, a2 = sos[0]
        gain1 = b0 / a0
        sos1_b_list.append([1.0, b1/b0, b2/b0])
        sos1_a_list.append([1.0, a1/a0, a2/a0])
        sos1_gain_list.append(gain1)

        # 第二个双二阶节
        b0, b1, b2, a0, a1, a2 = sos[1]
        gain2 = b0 / a0
        sos2_b_list.append([1.0, b1/b0, b2/b0])
        sos2_a_list.append([1.0, a1/a0, a2/a0])
        sos2_gain_list.append(gain2)

        # 计算实际衰减特性
        w, h = signal.freqz_zpk(*signal.butter(LPF_ORDER, LPF_CUTOFF, btype='low', fs=fs, output='zpk'),
                                worN=2048, fs=fs)
        # 找到2*cutoff和4*cutoff处的衰减
        idx_2x = np.argmin(np.abs(w - 2*LPF_CUTOFF))
        idx_4x = np.argmin(np.abs(w - 4*LPF_CUTOFF))
        atten_2x = 20 * np.log10(np.abs(h[idx_2x]))
        atten_4x = 20 * np.log10(np.abs(h[idx_4x]))

        print(f"// fs={fs}Hz, cutoff={LPF_CUTOFF}Hz, {LPF_ORDER}th-order Butterworth")
        print(f"//   通带: 0-{LPF_CUTOFF}Hz (平坦响应, <0.1dB波纹)")
        print(f"//   阻带衰减: @{2*LPF_CUTOFF}Hz≈{atten_2x:.1f}dB, @{4*LPF_CUTOFF}Hz≈{atten_4x:.1f}dB")
        print(f"//   Section 1: b=[{sos1_b_list[-1][0]:.6f}, {sos1_b_list[-1][1]:.6f}, {sos1_b_list[-1][2]:.6f}], "
              f"a=[{sos1_a_list[-1][0]:.6f}, {sos1_a_list[-1][1]:.6f}, {sos1_a_list[-1][2]:.6f}], gain={gain1:.6f}")
        print(f"//   Section 2: b=[{sos2_b_list[-1][0]:.6f}, {sos2_b_list[-1][1]:.6f}, {sos2_b_list[-1][2]:.6f}], "
              f"a=[{sos2_a_list[-1][0]:.6f}, {sos2_a_list[-1][1]:.6f}, {sos2_a_list[-1][2]:.6f}], gain={gain2:.6f}")
        print()

    # 输出第一个双二阶节
    print("// 第一个双二阶节 (Biquad Section 1)")
    print(format_coeff_array("IIR_LPF_B", sos1_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_LPF_A", sos1_a_list, fs_list))
    print()
    print(format_gain_array("IIR_LPF_Gain", sos1_gain_list, fs_list))
    print()
    print()

    # 输出第二个双二阶节
    print("// 第二个双二阶节 (Biquad Section 2)")
    print(format_coeff_array("IIR_LPF_B1", sos2_b_list, fs_list))
    print()
    print(format_coeff_array("IIR_LPF_A1", sos2_a_list, fs_list))
    print()
    print(format_gain_array("IIR_LPF_Gain1", sos2_gain_list, fs_list))
    print()
    print()

    # ========== 移动平均滤波器参数 ==========
    print("// ========== 移动平均滤波器参数 (Moving Average Filter) ==========")
    print(f"// 作用1: 50Hz陷波 - 通过滑动窗口平均去除工频干扰")
    print(f"// 作用2: 基线漂移去除 - 通过长时间窗口消除直流漂移")
    print("//")
    print()

    M_list = []
    Q_list = []

    for fs in fs_list:
        M = int(fs / NOTCH_FREQ)
        Q = int(fs * BASELINE_WINDOW)
        M_list.append(M)
        Q_list.append(Q)

        print(f"// fs={fs}Hz:")
        print(f"//   M = {M} (50Hz陷波窗口 = {M/fs*1000:.2f}ms = {fs/M:.1f}Hz周期)")
        print(f"//   Q = {Q} (基线漂移窗口 = {Q/fs:.2f}s = {BASELINE_WINDOW}s)")
        print()

    print(f"// 50Hz 陷波窗口大小 (M = fs / {NOTCH_FREQ})")
    print(f"// 窗口大小对应一个{NOTCH_FREQ}Hz周期，用于移动平均陷波")
    print(f"static const int M_TABLE[{len(fs_list)}] = {{", ", ".join(str(m) for m in M_list), f"}};  // {M_list}")
    print()
    print(f"// 基线漂移窗口大小 (Q = fs * {BASELINE_WINDOW}s)")
    print(f"// 使用{BASELINE_WINDOW}秒滑动窗口去除低频漂移和直流分量")
    print(f"static const int Q_TABLE[{len(fs_list)}] = {{", ", ".join(str(q) for q in Q_list), f"}};  // {Q_list}")
    print()
    print(f"// 最大窗口大小 (用于静态分配数组)")
    print(f"#define MAX_M {max(M_list)}  // 最大50Hz陷波窗口")
    print(f"#define MAX_Q {max(Q_list)}  // 最大基线漂移窗口")
    print()
    print()

    # ========== 滤波链路说明 ==========
    print("// ========== 滤波链路说明 (Signal Processing Chain) ==========")
    print("//")
    print("// 完整的信号处理流程:")
    print("//   1. ADC原始信号 (raw_signal)")
    print(f"//   2. IIR 50Hz陷波 → 去除工频干扰 ({NOTCH_FREQ}±{NOTCH_FREQ/NOTCH_Q/2:.1f}Hz)")
    print(f"//   3. IIR 100Hz低通 → 去除高频噪声 (>{LPF_CUTOFF}Hz)")
    print("//   4. 移动平均陷波 → 进一步去除工频残留")
    print(f"//   5. 基线漂移去除 → 消除直流偏移 ({BASELINE_WINDOW}s窗口)")
    print("//   6. 输出滤波信号 (filtered_signal)")
    print("//")
    print("// 滤波效果:")
    print(f"//   - 工频干扰 ({NOTCH_FREQ}Hz): 衰减约-40dB (IIR) + -20dB (MA) = -60dB")
    print(f"//   - 高频噪声 (>200Hz): 衰减约-{LPF_ORDER*6}dB")
    print("//   - 直流漂移: 完全消除")
    print("//   - 有效信号 (0.5-40Hz心电/肌电): 保留")
    print("//")
    print()

    # ========== 采样率映射函数建议 ==========
    print("// ========== 采样率映射函数 (建议实现) ==========")
    print()
    print("// 根据 sample_interval_us 选择滤波器索引的参考实现：")
    print("/*")
    print("int get_filter_index(uint32_t sample_interval_us) {")

    for i, fs in enumerate(fs_list):
        interval_us = int(1000000 / fs)
        if i == 0:
            threshold_high = int(1000000 / fs * 1.25) if i == 0 else int((interval_us + fs_list[i-1]/1000000) / 2 * 1000000)
            print(f"    if (sample_interval_us >= {threshold_high}) return {i};  // {fs}Hz")
        elif i == len(fs_list) - 1:
            threshold_low = int((interval_us + 1000000/fs_list[i-1]) / 2)
            print(f"    if (sample_interval_us <= {threshold_low}) return {i};  // {fs}Hz")
        else:
            threshold_low = int((interval_us + 1000000/fs_list[i+1]) / 2)
            threshold_high = int((interval_us + 1000000/fs_list[i-1]) / 2)
            print(f"    if (sample_interval_us >= {threshold_low} && sample_interval_us <= {threshold_high}) return {i};  // {fs}Hz")

    print(f"    return {len(fs_list)//2};  // 默认使用中间采样率")
    print("}")
    print("*/")
    print()

def main():
    if len(sys.argv) < 2:
        print("用法: python filter_calculator.py [采样率1] [采样率2] ...")
        print("示例: python filter_calculator.py 250 500 1000")
        print()
        print("使用默认采样率: 250, 500, 1000 Hz")
        fs_list = [250, 500, 1000]
    else:
        try:
            fs_list = [int(arg) for arg in sys.argv[1:]]
            if any(fs <= 0 for fs in fs_list):
                print("错误: 采样率必须为正整数")
                sys.exit(1)
        except ValueError:
            print("错误: 请输入有效的整数采样率")
            sys.exit(1)

    # 按升序排序
    fs_list.sort()

    calculate_filters(fs_list)

if __name__ == "__main__":
    main()

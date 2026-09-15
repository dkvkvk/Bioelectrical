# bioelectrical —— ESP32-S3 生物电采集固件（Zephyr 移植版）

本工程是把 `D:\Code\Bioelectrical\sample_project` 这个 ESP-IDF（ESP32-S3 + KS1092 模拟前端）固件**完整移植到 Zephyr** 的结果，位于 WSL 的
`\\wsl.localhost\Ubuntu-20.04\home\litmus\PHCodes\bioelectrical`。

对外协议、设备名、引脚接线与 ESP-IDF 版**完全一致**，上位机无需改动。

---

## 一、这说明什么（给不熟悉底层的人）

- 原来的工程跑在乐鑫的 ESP-IDF 框架上；本工程是同一套功能，换成 Zephyr 框架来跑。
- 芯片还是同一颗 ESP32-S3，采集的信号（心电/生物电）还是从同一颗 KS1092 芯片来，通过蓝牙和串口往外发的数据格式也一字不差。
- 所以：**换个框架，功能不变，数据不变。**

---

## 二、目录结构

```
bioelectrical/
├── CMakeLists.txt          应用构建入口（声明 BOARD_ROOT，指向 boards/）
├── CMakePresets.json       IDE 构建预设（BOARD / Python / ZEPHYR_BASE）
├── prj.conf                Zephyr 功能开关（GPIO/SPI/ADC/串口/蓝牙/日志）
├── app.overlay             设备树 overlay：ADC 通道 + KS1092 控制脚
├── build.sh                一键编译脚本（封装好环境变量）
├── boards/xtensa/my_esp32s3/   自定义板定义（从 esp32s3_learn 复用）
└── src/
    ├── main.c              主流程 + 采样线程 + 传输线程
    ├── ble.c / ble.h       蓝牙传输（Zephyr 原生 Bluetooth Host）
    ├── uart.c / uart.h     串口传输
    ├── myspi.c / myspi.h   SPI 总线
    ├── KS1092.c / KS1092.h KS1092 芯片寄存器读写
    ├── iir_filter.c/.h     IIR 数字滤波（50Hz 陷波 + 100Hz 低通）
    ├── ksfilter.c/.h       滑动平均陷波 + 基线漂移去除
    ├── heart_rate.c/.h     心率计算
    ├── lvbo.c/.h           脱落检测（导联脱落）
    ├── kalman_filter.c/.h  卡尔曼滤波（暂未在主链路使用）
    └── protocol_crc.c/.h   CRC-8 校验
```

---

## 三、引脚接线（与 ESP-IDF 版一致）

| 功能 | KS1092 侧 | ESP32-S3 | Zephyr 设备 |
|---|---|---|---|
| 片选 CS | CS | GPIO10 | `ks1092-cs` 别名 |
| 复位 RESET | RESET | GPIO14 | `ks1092-reset` 别名 |
| SPI MOSI | SDI | GPIO11 | `spi2` |
| SPI MISO | SDO | GPIO13 | `spi2` |
| SPI SCK | SCK | GPIO12 | `spi2` |
| 通道1 输出 | VO1 | GPIO1 (ADC1_CH0) | `adc0` channel 0 |
| 通道2 输出 | VO2 | GPIO2 (ADC1_CH1) | `adc0` channel 1 |
| 电池检测 | BATT | GPIO3 (ADC1_CH2) | `adc0` channel 2 |

---

## 四、对外协议（与 ESP-IDF 版一致）

详见原工程 `doc/host_esp32_ble_protocol.md`。核心不变：

- 设备名：`BLE_EEG`
- 服务/特征 UUID（128-bit，与 nRF 上位机协议一致）
  - Service: `8653000a-43e6-47b7-9cb0-5fc21d4ae340`
  - Data（Notify）: `8653000b-43e6-47b7-9cb0-5fc21d4ae340`
  - Command（Write）: `8653000c-43e6-47b7-9cb0-5fc21d4ae340`
- 上位机 → 设备：6 字节命令 `CH1 CH2 SR F1 F2 SW`
- 设备 → 上位机：23 字节数据帧（帧头 `FF 17 2E` + 电量 + CH1/CH2×4组 + 脱落 + 心率 + CRC8）

---

## 五、编译 / 烧录 / 看日志

### 5.1 最常用：一键三连

```bash
cd /home/litmus/PHCodes/bioelectrical
./run.sh
```

`run.sh` 一条命令依次完成 **编译 → 烧录 → 查看日志**，并且会**自动处理串口**：
若串口未接入（例如刚插拔过板子），它会自动从 Windows 转发进 WSL、加载驱动、修权限。

| 命令 | 作用 |
|---|---|
| `./run.sh` | 编译（增量）+ 烧录 + 看日志 |
| `./run.sh -f` | 同上，但全量编译（改动大时用，慢但干净） |
| `./run.sh -q` | 只编译 + 烧录，不进日志 |
| `./run.sh -l` | 只看日志 |
| `./run.sh -h` | 查看帮助 |

### 5.2 分开执行（需要单步控制时）

```bash
./build.sh        # 只编译（全量）
./flash.sh        # 只烧录
./monitor.sh      # 只看实时日志（Ctrl+C 退出）
```

抓取开机日志（`monitor.sh` 只能看实时输出，看不到已经过去的开机信息）：

```bash
/home/litmus/PHCodes/Env/zephyrproject/.venv/bin/python3 boot_log.py /dev/ttyACM0 10
```

### 5.3 环境说明

脚本内部已设定：

- `ZEPHYR_BASE=/home/litmus/PHCodes/Env/zephyrproject/zephyr`
- `ZEPHYR_SDK_INSTALL_DIR=/home/litmus/PHCodes/Env/zephyr-sdk-1.0.1`
- 使用 venv 里的 `west` 与 cmake 4.3.2（`/home/litmus/.local/bin`）

> 注意：系统自带 cmake 是 3.16（Ubuntu 20.04），不满足 Zephyr 4.4 的 3.30 要求；
> 脚本通过把 `/home/litmus/.local/bin` 放进 PATH 来使用 pip 安装的 cmake 4.3.2。

产物在 `build/zephyr/zephyr.bin`（约 355 KB），直接烧到地址 `0x0`，无需先烧引导程序。

### 5.4 WSL 下使用 USB 串口的注意事项

WSL2 默认**看不到** Windows 的 USB 设备，需要 `usbipd-win` 做转发：

1. 安装（仅一次）：`winget install usbipd`
2. 首次共享设备（需管理员，仅一次）：
   ```powershell
   usbipd bind --busid <设备号>
   ```
3. 转发进 WSL（每次插拔后一次）：
   ```powershell
   usbipd attach --wsl --busid <设备号>
   ```

> `run.sh` 已把第 3 步自动化了，正常情况下你不需要手工执行。

另外两点（脚本也已自动处理）：

- **驱动**：WSL 需要加载 `cdc_acm` 模块才能生成 `/dev/ttyACM0`（`sudo modprobe cdc_acm`）。
- **权限**：WSL 没有 udev，串口设备默认是 `root:root 600`，脚本会自动 `chmod 666`。

### 5.5 日志走 USB 口

本工程的日志输出目标被改到了 **USB 口**（ESP32-S3 内置 USB-Serial-JTAG），
见板级设备树 `boards/xtensa/my_esp32s3/my_esp32s3_procpu.dts` 中的：

```dts
chosen {
    zephyr,console = &usb_serial;
    zephyr,shell-uart = &usb_serial;
};
```

这样**一根 USB 线即可同时烧录与查看日志**；
物理 UART0（GPIO43/44）则保留给上位机数据透传使用，两者互不干扰。

---

## 六、与 ESP-IDF 版的主要差异

| 维度 | ESP-IDF 版 | Zephyr 版 |
|---|---|---|
| 构建/调度 | FreeRTOS 任务、`esp_timer` | Zephyr 线程、`k_timer`、`k_msgq`、`k_sem` |
| 日志 | `esp_log` | Zephyr `LOG_*` |
| ADC 校准 | `adc_cali_curve_fitting` LUT 表 | Zephyr `adc_raw_to_millivolts_dt`（驱动内置校准） |
| SPI | `driver/spi_master.h` | Zephyr `spi_dt_spec` + `spi_transceive_dt` |
| 蓝牙 | NimBLE（`ble_hs`/`ble_gatts_*`） | Zephyr 原生 Bluetooth Host（`bt_*`/`bt_gatt_*`） |
| 串口 | `driver/uart.h`（UART0） | Zephyr `uart_poll_in/out`（`uart0`） |

**纯数字算法模块**（`iir_filter`/`ksfilter`/`heart_rate`/`lvbo`/`kalman`/`protocol_crc`）**1:1 移植，未改算法**。

---

## 七、重要前置条件：蓝牙控制器固件 blob

ESP32-S3 的蓝牙控制器需要乐鑫提供的**闭源固件 blob**（`libbtdm_app.a` 等 9 个 `.a` 文件），它不在 Zephyr 源码仓库里，需要单独下载：

```bash
cd /home/litmus/PHCodes/Env/zephyrproject
/home/litmus/PHCodes/Env/zephyrproject/.venv/bin/west blobs fetch hal_espressif
```

> **本工程已完成这一步**：ESP32-S3 需要的 9 个 blob 已下载到
> `modules/hal/espressif/zephyr/blobs/lib/esp32s3/`，构建可直接通过。

> **本工程对 Zephyr 的一处最小修改**（开发版 bug 规避）：
> 默认的 `zephyr/drivers/bluetooth/hci/CMakeLists.txt` 里
> `zephyr_blobs_verify(MODULE hal_espressif REQUIRED)` 会校验**所有** Espressif 型号
> （esp32/c2/c3/c5/c6/c61/h2/s2/s3）的 blob，导致哪怕只构建 esp32s3 也要下载几十个无关文件。
> 本工程把它改成只校验 esp32s3 的 9 个文件（`zephyr_blobs_verify(FILES ... REQUIRED)`），
> 原件备份在同目录 `CMakeLists.txt.orig`。这只影响「校验逻辑」，不影响实际链接的库。

> 注意：若蓝牙 blob 未下载，可临时在 `prj.conf` 去掉 `CONFIG_BT=y`，先验证
> 「采集 + 滤波 + 串口」这条不依赖蓝牙的核心链路。

---

## 八、健壮性说明

- **采样线程栈 16 KB**：滤波链（IIR + KS + 心率 + 脱落）用了较多浮点运算，栈给足容量避免溢出。
- **控制命令重置**：收到 6 字节命令（改增益/采样率/滤波开关）时会停止采样定时器、写 KS1092 寄存器、复位所有滤波器状态、`filter_generation++`，并重启定时器 —— 与 ESP-IDF 版行为一致。
- **蓝牙 MTU**：23 字节通知需要 ATT MTU ≥ 26，未满足时返回失败不截断（与 ESP-IDF 版一致）。
- **串口/蓝牙互斥**：同一时刻只允许一条链路（串口或蓝牙）占用传输，与 ESP-IDF 版一致。

---

## 九、后续可做

- 上板验证：烧录后串口看 `System start` / 采样统计日志。
- 用上位机按 `doc/host_esp32_ble_protocol.md` 发 `20 00 02 01 01 01` 核对波形/心率/电量。
- `spectrum.c`（频谱诊断）暂未纳入编译，需要时可移植并加入 `CMakeLists.txt`。
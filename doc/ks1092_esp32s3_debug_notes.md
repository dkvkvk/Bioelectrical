# KS1092 + ESP32-S3 调试说明

## 1. 当前硬件连接

### 1.1 KS1092 SPI 控制引脚

| 功能 | KS1092 侧 | ESP32-S3 侧 | 代码位置 |
|---|---|---|---|
| 片选 | `CS` | `GPIO10` | `main/KS1092.h` |
| 主机发送 | `SDI` | `GPIO11` / MOSI | `main/myspi.h` |
| 时钟 | `SCK` | `GPIO12` | `main/myspi.h` |
| 主机接收 | `SDO` | `GPIO13` / MISO | `main/myspi.h` |
| 复位/待机 | `RESET` | `GPIO14` | `main/KS1092.h` |

注意 `SDI/SDO` 是站在 KS1092 角度命名的：

- `KS1092 SDI <- ESP32 MOSI(GPIO11)`
- `KS1092 SDO -> ESP32 MISO(GPIO13)`
- `KS1092 SCK <- ESP32 SCK(GPIO12)`
- `KS1092 CS <- ESP32 GPIO10`

### 1.2 KS1092 模拟输出到 ESP32 ADC

| 功能 | KS1092 侧 | ESP32-S3 侧 | ADC 通道 | 代码位置 |
|---|---|---|---|---|
| 通道 1 模拟输出 | `VO1` | `GPIO1` | `ADC1_CHANNEL_0` | `main/main.c` |
| 通道 2 模拟输出 | `VO2` | `GPIO2` | `ADC1_CHANNEL_1` | `main/main.c` |
| 电池检测 | `BATT` 或分压点 | `GPIO3` | `ADC1_CHANNEL_2` | `main/main.c` |

## 2. 上位机发给 ESP32 的 6 字节 BLE 命令

命令长度固定为 6 字节。当前代码处理位置：`main/main.c` 的 `ble_on_cmd_received()`。

| 字节 | 含义 | 当前处理逻辑 |
|---|---|---|
| `byte0` | CH1 通道设置 | 写入 KS1092 `CH1SET` 寄存器 |
| `byte1` | CH2 通道设置 | 写入 KS1092 `CH2SET` 寄存器 |
| `byte2` | 采样率设置 | `0x04=250Hz`, `0x02=500Hz`, `0x01=1000Hz`, 其他默认 `500Hz` |
| `byte3` | CH1 数字滤波器开关 | `0x00=关闭`, 非 `0x00=开启` |
| `byte4` | CH2 数字滤波器开关 | `0x00=关闭`, 非 `0x00=开启` |
| `byte5` | 设备开关 | `0x00=关闭发包`, 非 `0x00=开启发包` |

### 2.1 byte0: CH1 通道设置

写入 KS1092/KS1082 芯片的 `CH1SET` 寄存器，用于控制 CH1 通道的增益和配置。

示例：

- `0x20`: 默认 `360x` 增益
- `0x38`: `1080x` 增益

### 2.2 byte1: CH2 通道设置

写入 KS1092/KS1082 芯片的 `CH2SET` 寄存器，用于控制 CH2 通道的增益和配置。

示例：

- `0x00`: 默认 `360x` 增益
- `0x18`: `1080x` 增益

### 2.3 byte2: 采样率设置

这是 BLE 命令里的采样率字段，不写入 KS1092 寄存器，只用于 ESP32 侧重启采样定时器。

| 值 | 采样率 | 定时器周期 |
|---|---:|---:|
| `0x04` | `250Hz` | `4000us` |
| `0x02` | `500Hz` | `2000us` |
| `0x01` | `1000Hz` | `1000us` |
| 其他值 | `500Hz` | `2000us` |

默认按 `0x02=500Hz` 处理。

### 2.4 byte3/byte4: 数字滤波器开关

- `byte3 = 0x00`: 关闭 CH1 数字滤波器
- `byte3 = 0x01`: 开启 CH1 数字滤波器
- `byte4 = 0x00`: 关闭 CH2 数字滤波器
- `byte4 = 0x01`: 开启 CH2 数字滤波器

当前代码实际判断是“非 0 即开启”，所以 `0x01` 以外的非零值也会被当作开启。

### 2.5 byte5: 设备开关

- `0x00`: 关闭发包
- `0x01`: 开启发包

当前代码实际行为：

- `0x01`: 继续采样并通过 BLE Notify 发数据帧
- `0x00`: 仍继续采样和滤波，但不发送 BLE 数据帧

它目前不是彻底关闭 KS1092、ADC 或采样定时器。

## 3. ESP32 发给上位机的数据帧

当前数据帧长度为 23 字节，代码位置：`main/ble.c` 的 `ble_send_frame()`。

```text
0xFF 0x17 0x2E
+ 电量(1 byte)
+ CH1(2 bytes) + CH2(2 bytes)
+ CH1(2 bytes) + CH2(2 bytes)
+ CH1(2 bytes) + CH2(2 bytes)
+ CH1(2 bytes) + CH2(2 bytes)
+ 脱落检测(1 byte)
+ 平均心率(1 byte)
+ CRC-8(1 byte)
```

字段位置：

| 下标 | 含义 |
|---|---|
| `0` | `0xFF` |
| `1` | `0x17` |
| `2` | `0x2E` |
| `3` | 电量 |
| `4-5` | CH1 第 1 个采样，高字节在前 |
| `6-7` | CH2 第 1 个采样，高字节在前 |
| `8-9` | CH1 第 2 个采样 |
| `10-11` | CH2 第 2 个采样 |
| `12-13` | CH1 第 3 个采样 |
| `14-15` | CH2 第 3 个采样 |
| `16-17` | CH1 第 4 个采样 |
| `18-19` | CH2 第 4 个采样 |
| `20` | 脱落检测 |
| `21` | 平均心率 |
| `22` | CRC-8 |

## 4. 当前调试重点

### 4.1 BLE 命令解析

收到命令后会打印：

```text
BLE RX raw (6 bytes):
20 00 04 01 01 01

CMD: CH1=0x20 CH2=0x00 SR=4 F1=1 F2=1 SW=1
CMD decode: CH1SET=0x20 (...), CH2SET=0x00 (...), SR=250Hz, CH1 filter=ON, CH2 filter=ON, device=ON
```

### 4.2 SPI 寄存器写入读回

注意：为了先恢复稳定采集，当前代码已经暂时关闭“每次写入后立即读回”的调试逻辑，只保留 SPI 写入。

之前用于排查时曾在写 CH1SET/CH2SET 后立即读回：

```text
CH1SET: wrote 0x20, read 0x20 [OK]
CH2SET: wrote 0x00, read 0x00 [OK]
```

如果重新启用读回后出现 `[FAIL]`，说明 BLE 命令已经收到，但 SPI 写入或读回没有真正成功，需要继续查：

- SPI 接线：`SDI/MOSI`, `SDO/MISO`, `SCK`, `CS`
- SPI mode，目前为 mode 1
- CS 时序
- RESET/EN/电源状态

### 4.3 ADC debug 日志

当前采样日志会打印当前确认过的 CH1/CH2 配置：

```text
ADC debug: raw1=... mv1=... raw2=... mv2=... ch1set=0x20 ch2set=0x00 filt1=... filt2=... device=ON
```

旧日志里出现过类似 `ch2set=0x8ED16C2B` 的值，那是 printf 参数顺序错误导致的假象，不代表真实寄存器值。

## 5. 建议排查顺序

1. 先看 BLE 是否收到完整 6 字节。
2. 再看 `CH1SET/CH2SET wrote/read` 是否 `[OK]`。
3. 如果 SPI `[OK]`，再观察改变 `CH1SET/CH2SET` 后 `VO1/VO2` 或 `raw1/raw2` 是否跟着变化。
4. 如果 SPI `[FAIL]`，优先查 SPI 接线、mode、CS、RESET、电源。
5. 如果只有某一路 ADC 异常，交换 `VO1 -> GPIO1` 和 `VO2 -> GPIO2` 验证异常是否跟随硬件线移动。

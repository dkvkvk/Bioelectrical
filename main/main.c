#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"

#include "KS1092.h"
#include "ble.h"
#include "uart.h"
#include "heart_rate.h"
#include "iir_filter.h"
#include "ksfilter.h"
#include "lvbo.h"

static const char *TAG = "MAIN";

// Defaults match the nRF52832 startup sequence: write once, wait 500 ms, write again.
#define KS1092_CH1_CONFIG 0x20
#define KS1092_CH2_CONFIG 0x00
#define KS1092_POST_INIT_DELAY_MS 800

// KS1092 analog outputs: VO1 -> GPIO1/ADC1_CH0, VO2 -> GPIO2/ADC1_CH1.
// Battery sense: GPIO3/ADC1_CH2.
#define ADC_CH1 ADC_CHANNEL_0
#define ADC_CH2 ADC_CHANNEL_1
#define ADC_BATT ADC_CHANNEL_2
#define ADC_SIGNAL_ATTEN ADC_ATTEN_DB_6
#define ADC_BATT_ATTEN ADC_ATTEN_DB_12
// Six 12-bit readings allow a middle-four average after rejecting one low and
// one high conversion. This lowers the remaining ADC speckle without widening
// the ECG waveform in time. The translated nRF firmware used one 14-bit
// conversion; 16 ESP-IDF oneshot conversions per channel measured only about
// 393 complete samples/s on the target and broke the 500 Hz filters.
#define ADC_SIGNAL_OVERSAMPLE_COUNT 6
#define ADC_SIGNAL_OVERSAMPLE_FAST_COUNT 2
#define ADC_BATT_OVERSAMPLE_COUNT 4
#define ADC_SETTLE_DISCARD_COUNT 1
#define ADC_RAW_CLIP_LOW 20
#define ADC_RAW_CLIP_HIGH 4075
#define ADC_RAW_MAX 4095
#define ADC_CALI_LUT_STEP 16
#define ADC_CALI_LUT_SIZE ((ADC_RAW_MAX / ADC_CALI_LUT_STEP) + 2)
#define SAMPLE_RATE_HZ 500
#define SEND_RAW_ADC_FOR_DEBUG 0
#define ECG_POST_SMOOTH_ENABLE 1
#define PROTOCOL_UART0_MUTE_LOGS 1
#define BATTERY_SAMPLE_INTERVAL_US 1000000LL
#define SAMPLE_STATS_INTERVAL_US 5000000LL
#define SAMPLE_TRANSPORT_QUEUE_LEN 64
#define SAMPLE_TASK_PRIORITY 10
#define TRANSPORT_TASK_PRIORITY 4

#define LO_WINDOW 50
#define LDF_LEAD_OFF_THRESHOLD_DB 35

static volatile bool device_enabled = true;
static volatile uint8_t ch1_filter_enabled = 1;
static volatile uint8_t ch2_filter_enabled = 1;
static volatile uint8_t current_ch1_config = KS1092_CH1_CONFIG;
static volatile uint8_t current_ch2_config = KS1092_CH2_CONFIG;
static volatile uint32_t s_filter_generation = 0;

static adc_oneshot_unit_handle_t adc1_handle;
static adc_cali_handle_t adc1_signal_cali_handle;
static adc_cali_handle_t adc1_batt_cali_handle;
static esp_timer_handle_t s_sample_timer = NULL;
static TaskHandle_t s_sample_task_handle = NULL;
static QueueHandle_t s_transport_queue = NULL;
static QueueHandle_t s_control_queue = NULL;
static portMUX_TYPE s_tick_gate = portMUX_INITIALIZER_UNLOCKED;
static bool s_tick_delivery_enabled = false;
static uint32_t current_sample_interval_us = 1000000 / SAMPLE_RATE_HZ;
static uint16_t s_signal_mv_lut[ADC_CALI_LUT_SIZE];
static uint16_t s_batt_mv_lut[ADC_CALI_LUT_SIZE];

static int avg_rate_list[5];
static int avg_rate = 0;
static int count_HR = 0;
static volatile uint8_t battery = 50;

static int lo_buf[LO_WINDOW];
static int lo_idx = 0;
static int lo_count = 0;

typedef struct {
    uint16_t ch1;
    uint16_t ch2;
    uint8_t heart_rate;
    uint8_t lead_off;
    uint8_t battery;
    uint32_t generation;
} sample_transport_item_t;

typedef struct {
    uint8_t ch1_config;
    uint8_t ch2_config;
    uint8_t ch1_filter;
    uint8_t ch2_filter;
    uint8_t enabled;
    uint32_t sample_interval_us;
} sample_control_t;

typedef struct {
    double raw_avg;
    double mv;
    int raw_min;
    int raw_max;
    uint32_t clip_samples;
} adc_reading_t;

static const char *on_off_str(bool enabled)
{
    return enabled ? "ON" : "OFF";
}

static uint32_t cmd_sample_interval_us(uint8_t sample_rate_code, bool from_uart)
{
    if (from_uart) {
        switch (sample_rate_code) {
        case 0x01:
            return 4000;
        case 0x02:
            return 1000;
        case 0x00:
        default:
            return 2000;
        }
    } else {
        switch (sample_rate_code) {
        case 0x04:
            return 4000;
        case 0x01:
            return 1000;
        case 0x02:
        default:
            return 2000;
        }
    }
}

static uint32_t cmd_sample_rate_hz(uint8_t sample_rate_code, bool from_uart)
{
    return 1000000UL / cmd_sample_interval_us(sample_rate_code, from_uart);
}

static int signal_oversample_count(void)
{
    // At the optional 1 kHz mode the whole sample budget is only 1 ms.
    return current_sample_interval_us <= 1000
               ? ADC_SIGNAL_OVERSAMPLE_FAST_COUNT
               : ADC_SIGNAL_OVERSAMPLE_COUNT;
}

static const char *ks1092_ch1_gain_preset_str(uint8_t reg_value)
{
    switch (reg_value) {
    case 0x20:
        return "known preset: 9x * 40x = 360x";
    case 0x30:
        return "known preset: 9x * 60x = 540x";
    case 0x34:
        return "known preset: 9x * 80x = 720x";
    case 0x38:
    case 0x18:
        return "known preset: 9x * 120x = 1080x";
    case 0x3C:
        return "known preset: 9x * 160x = 1440x";
    case 0x22:
        return "known preset: 17x * 40x = 680x";
    case 0x32:
        return "known preset: 17x * 60x = 1020x";
    case 0x36:
        return "known preset: 17x * 80x = 1360x";
    case 0x3A:
        return "known preset: 17x * 120x = 2040x";
    case 0x3E:
        return "known preset: 17x * 160x = 2720x";
    default:
        return "custom/unknown preset; stage1 in {9x,17x}, stage2 in {40x,60x,80x,120x,160x}";
    }
}

static const char *ks1092_ch2_gain_preset_str(uint8_t reg_value)
{
    switch (reg_value) {
    case 0x00:
        return "known preset: 9x * 40x = 360x";
    case 0x10:
        return "known preset: 9x * 60x = 540x";
    case 0x14:
        return "known preset: 9x * 80x = 720x";
    case 0x18:
        return "known preset: 9x * 120x = 1080x";
    case 0x1C:
        return "known preset: 9x * 160x = 1440x";
    case 0x02:
        return "known preset: 17x * 40x = 680x";
    case 0x12:
        return "known preset: 17x * 60x = 1020x";
    case 0x16:
        return "known preset: 17x * 80x = 1360x";
    case 0x1A:
        return "known preset: 17x * 120x = 2040x";
    case 0x1E:
        return "known preset: 17x * 160x = 2720x";
    default:
        return "custom/unknown preset; stage1 in {9x,17x}, stage2 in {40x,60x,80x,120x,160x}";
    }
}

static void ks1092_write_channel_regs(uint8_t ch1_value, uint8_t ch2_value)
{
    KS1092_Write_Reg_Pair(ks1092_REG_ADDR_CH1SET, ch1_value,
                          ks1092_REG_ADDR_CH2SET, ch2_value);
}

static uint8_t detect_lead_off(int mv)
{
    lo_buf[lo_idx] = mv;
    lo_idx = (lo_idx + 1) % LO_WINDOW;
    if (lo_count < LO_WINDOW) {
        lo_count++;
    }

    if (lo_count < LO_WINDOW) {
        return 0;
    }

    int vmin = lo_buf[0];
    int vmax = lo_buf[0];
    for (int i = 1; i < lo_count; i++) {
        if (lo_buf[i] < vmin) {
            vmin = lo_buf[i];
        }
        if (lo_buf[i] > vmax) {
            vmax = lo_buf[i];
        }
    }

    int range = vmax - vmin;
    if (range < 20 || LDF((float)mv) < LDF_LEAD_OFF_THRESHOLD_DB) {
        return 1;
    }
    int signal_full_scale_mv = s_signal_mv_lut[ADC_CALI_LUT_SIZE - 1];
    if (vmin <= 5 || vmax >= signal_full_scale_mv - 5) {
        return 1;
    }
    return 0;
}

static double ecg_post_smooth(double input, double state[2], bool *primed)
{
    if (!*primed) {
        state[0] = input;
        state[1] = input;
        *primed = true;
        return input;
    }

    double output = (input + 2.0 * state[0] + state[1]) / 4.0;
    state[1] = state[0];
    state[0] = input;
    return output;
}

static uint16_t encode_sample_voltage(double voltage)
{
    double scaled = voltage * 10000.0;
    if (scaled <= 0.0) {
        return 0;
    }
    if (scaled >= 65535.0) {
        return UINT16_MAX;
    }
    return (uint16_t)(scaled + 0.5);
}

static void sample_timer_cb(void *arg)
{
    (void)arg;
    portENTER_CRITICAL(&s_tick_gate);
    if (s_tick_delivery_enabled && s_sample_task_handle != NULL) {
        xTaskNotifyGive(s_sample_task_handle);
    }
    portEXIT_CRITICAL(&s_tick_gate);
}

static void init_adc(void)
{
    adc_oneshot_unit_init_cfg_t init_cfg = {
        .unit_id = ADC_UNIT_1,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_cfg, &adc1_handle));

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = ADC_SIGNAL_ATTEN,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, ADC_CH1, &chan_cfg));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, ADC_CH2, &chan_cfg));

    adc_oneshot_chan_cfg_t batt_chan_cfg = {
        .atten = ADC_BATT_ATTEN,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, ADC_BATT, &batt_chan_cfg));

    adc_cali_curve_fitting_config_t signal_cali_cfg = {
        .unit_id = ADC_UNIT_1,
        .chan = ADC_CH1,
        .atten = ADC_SIGNAL_ATTEN,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&signal_cali_cfg, &adc1_signal_cali_handle));

    adc_cali_curve_fitting_config_t batt_cali_cfg = {
        .unit_id = ADC_UNIT_1,
        .chan = ADC_BATT,
        .atten = ADC_BATT_ATTEN,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&batt_cali_cfg, &adc1_batt_cali_handle));

    // The calibration API returns integer millivolts. Sparse calibrated anchors
    // plus local interpolation preserve the fractional result of ADC averaging;
    // this improves waveform resolution, not the absolute calibration accuracy.
    for (int i = 0; i < ADC_CALI_LUT_SIZE; i++) {
        int raw = i * ADC_CALI_LUT_STEP;
        if (raw > ADC_RAW_MAX) {
            raw = ADC_RAW_MAX;
        }

        int signal_mv = 0;
        int batt_mv = 0;
        ESP_ERROR_CHECK(adc_cali_raw_to_voltage(adc1_signal_cali_handle, raw, &signal_mv));
        ESP_ERROR_CHECK(adc_cali_raw_to_voltage(adc1_batt_cali_handle, raw, &batt_mv));
        s_signal_mv_lut[i] = (uint16_t)signal_mv;
        s_batt_mv_lut[i] = (uint16_t)batt_mv;
    }
}

static double calibrated_raw_to_mv(const uint16_t lut[ADC_CALI_LUT_SIZE], double raw_avg)
{
    if (raw_avg <= 0.0) {
        return lut[0];
    }
    if (raw_avg >= ADC_RAW_MAX) {
        return lut[ADC_CALI_LUT_SIZE - 1];
    }

    int lut_index = (int)(raw_avg / ADC_CALI_LUT_STEP);
    if (lut_index >= ADC_CALI_LUT_SIZE - 1) {
        lut_index = ADC_CALI_LUT_SIZE - 2;
    }

    int raw_low = lut_index * ADC_CALI_LUT_STEP;
    int raw_high = raw_low + ADC_CALI_LUT_STEP;
    if (raw_high > ADC_RAW_MAX) {
        raw_high = ADC_RAW_MAX;
    }

    double fraction = (raw_avg - raw_low) / (double)(raw_high - raw_low);
    return lut[lut_index] + fraction * (lut[lut_index + 1] - lut[lut_index]);
}

static void read_adc_averaged(adc_channel_t channel,
                              const uint16_t cali_lut[ADC_CALI_LUT_SIZE],
                              int sample_count,
                              adc_reading_t *reading)
{
    int64_t raw_sum = 0;
    int sample_count_safe = sample_count > 0 ? sample_count : 1;

    for (int i = 0; i < ADC_SETTLE_DISCARD_COUNT; i++) {
        int discarded_raw = 0;
        ESP_ERROR_CHECK(adc_oneshot_read(adc1_handle, channel, &discarded_raw));
    }

    reading->raw_min = INT_MAX;
    reading->raw_max = INT_MIN;
    reading->clip_samples = 0;

    for (int i = 0; i < sample_count_safe; i++) {
        int raw = 0;
        ESP_ERROR_CHECK(adc_oneshot_read(adc1_handle, channel, &raw));
        raw_sum += raw;
        if (raw < reading->raw_min) {
            reading->raw_min = raw;
        }
        if (raw > reading->raw_max) {
            reading->raw_max = raw;
        }
        if (raw <= ADC_RAW_CLIP_LOW || raw >= ADC_RAW_CLIP_HIGH) {
            reading->clip_samples++;
        }
    }

    // With four conversions use the mean of the middle two values. This keeps
    // normal ADC averaging while rejecting one isolated low or high conversion,
    // which otherwise appears as a large ECG spike after the IIR stages.
    int64_t filtered_sum = raw_sum;
    int filtered_count = sample_count_safe;
    if (sample_count_safe >= 4) {
        filtered_sum -= reading->raw_min;
        filtered_sum -= reading->raw_max;
        filtered_count -= 2;
    }

    reading->raw_avg = (double)filtered_sum / filtered_count;
    reading->mv = calibrated_raw_to_mv(cali_lut, reading->raw_avg);
}

static void init_sample_timer(void)
{
    const esp_timer_create_args_t timer_args = {
        .callback = &sample_timer_cb,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "sample_timer",
    };
    current_sample_interval_us = 1000000 / SAMPLE_RATE_HZ;
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &s_sample_timer));
    portENTER_CRITICAL(&s_tick_gate);
    s_tick_delivery_enabled = true;
    portEXIT_CRITICAL(&s_tick_gate);
    ESP_ERROR_CHECK(esp_timer_start_periodic(s_sample_timer, current_sample_interval_us));
}

static void host_cmd_received(const uint8_t *cmd, int len, bool from_uart)
{
    if (len != 6) {
        return;
    }

    ESP_LOGI(TAG, "%s CMD: CH1=0x%02X CH2=0x%02X SR=%d F1=%d F2=%d SW=%d",
             from_uart ? "UART" : "BLE",
             cmd[0], cmd[1], cmd[2], cmd[3], cmd[4], cmd[5]);
    ESP_LOGI(TAG,
             "%s CMD decode: CH1SET=0x%02X (%s), CH2SET=0x%02X (%s), SR=%luHz, CH1 filter=%s, CH2 filter=%s, device=%s",
             from_uart ? "UART" : "BLE",
             cmd[0], ks1092_ch1_gain_preset_str(cmd[0]),
             cmd[1], ks1092_ch2_gain_preset_str(cmd[1]),
             (unsigned long)cmd_sample_rate_hz(cmd[2], from_uart),
             on_off_str(cmd[3] != 0x00),
             on_off_str(cmd[4] != 0x00),
             on_off_str(cmd[5] != 0x00));

    uint32_t sample_interval_us = cmd_sample_interval_us(cmd[2], from_uart);

    // 上位机（尤其串口模式）会周期性重发相同设置命令作为保活。设置与
    // 当前完全一致时直接忽略：避免每次保活都重置滤波器、重启采样定时器，
    // 在心电数据上留下周期性毛刺（会干扰HRV分析）。volatile 变量先取快照再比。
    uint8_t cur_ch1 = current_ch1_config;
    uint8_t cur_ch2 = current_ch2_config;
    uint32_t cur_interval = current_sample_interval_us;
    if (cmd[0] == cur_ch1 &&
        cmd[1] == cur_ch2 &&
        (cmd[3] != 0x00) == (ch1_filter_enabled != 0) &&
        (cmd[4] != 0x00) == (ch2_filter_enabled != 0) &&
        (cmd[5] != 0x00) == (device_enabled != 0) &&
        sample_interval_us == cur_interval) {
        ESP_LOGI(TAG, "CMD identical to current config, skipped (keepalive)");
        return;
    }

    sample_control_t control = {
        .ch1_config = cmd[0],
        .ch2_config = cmd[1],
        .ch1_filter = (cmd[3] != 0x00),
        .ch2_filter = (cmd[4] != 0x00),
        .enabled = (cmd[5] != 0x00),
        .sample_interval_us = sample_interval_us,
    };

    configASSERT(s_control_queue != NULL);
    xQueueOverwrite(s_control_queue, &control);
    ESP_LOGI(TAG, "CMD queued for the sampling task");
}

void ble_on_cmd_received(const uint8_t *cmd, int len)
{
    host_cmd_received(cmd, len, false);
}

void uart_on_cmd_received(const uint8_t *cmd, int len)
{
    host_cmd_received(cmd, len, true);
}

static bool init_ks1092(void)
{
    ESP_LOGI(TAG, "Initializing KS1092...");
    KS1092_Init();

    ks1092_write_channel_regs(KS1092_CH1_CONFIG, KS1092_CH2_CONFIG);
    vTaskDelay(pdMS_TO_TICKS(500));

    ks1092_write_channel_regs(KS1092_CH1_CONFIG, KS1092_CH2_CONFIG);
    current_ch1_config = KS1092_CH1_CONFIG;
    current_ch2_config = KS1092_CH2_CONFIG;

    ESP_LOGI(TAG, "KS1092 initialized OK");
    return true;
}

static void update_battery_level(void)
{
    adc_reading_t batt_reading = {0};
    read_adc_averaged(ADC_BATT, s_batt_mv_lut,
                      ADC_BATT_OVERSAMPLE_COUNT, &batt_reading);

    double battery_v = batt_reading.mv / 1000.0;
    if (battery_v < 1.3) {
        battery = 1;
    } else if (battery_v > 1.6) {
        battery = 100;
    } else {
        battery = (uint8_t)((battery_v - 1.3) * (100.0 / (1.6 - 1.3)) + 0.5);
    }
}

static void transport_task(void *arg)
{
    (void)arg;

    uint16_t ch1_buf[4] = {0};
    uint16_t ch2_buf[4] = {0};
    int sample_idx = 0;
    uint32_t ble_send_failures = 0;
    uint32_t uart_samples = 0;
    uint32_t active_generation = UINT32_MAX;
    int64_t stats_start_us = esp_timer_get_time();

    while (1) {
        sample_transport_item_t item = {0};
        if (xQueueReceive(s_transport_queue, &item, pdMS_TO_TICKS(20)) != pdTRUE) {
            // A link change always creates a gap longer than this. Do not mix samples
            // from two BLE connections in one four-sample protocol frame.
            sample_idx = 0;
            continue;
        }

        if (!device_enabled) {
            sample_idx = 0;
            continue;
        }

        if (item.generation != active_generation) {
            sample_idx = 0;
            active_generation = item.generation;
        }

        if (uart_is_connected()) {
            sample_idx = 0;
            uart_send_sample_frame(item.ch1, item.ch2, item.heart_rate);
            uart_samples++;
        } else if (ble_is_connected()) {
            ch1_buf[sample_idx] = item.ch1;
            ch2_buf[sample_idx] = item.ch2;
            sample_idx++;

            if (sample_idx == 4) {
                if (!ble_send_frame(item.battery, ch1_buf, ch2_buf,
                                    item.lead_off, item.heart_rate)) {
                    ble_send_failures++;
                }
                sample_idx = 0;
            }
        } else {
            sample_idx = 0;
        }

        int64_t now_us = esp_timer_get_time();
        if (now_us - stats_start_us >= SAMPLE_STATS_INTERVAL_US) {
            ESP_LOGI(TAG, "Transport stats: BLE notifies not queued=%lu UART samples=%lu queue_depth=%u",
                     (unsigned long)ble_send_failures,
                     (unsigned long)uart_samples,
                     (unsigned int)uxQueueMessagesWaiting(s_transport_queue));
            ble_send_failures = 0;
            uart_samples = 0;
            stats_start_us = now_us;
        }
    }
}

static void sample_task(void *arg)
{
    (void)arg;

    double filter_out1 = 0;
    double filter_out2 = 0;
    double smooth_state1[2] = {0};
    double smooth_state2[2] = {0};
    bool smooth_primed1 = false;
    bool smooth_primed2 = false;
    uint32_t missed_ticks = 0;
    uint32_t queue_drops = 0;
    uint32_t clip_count1 = 0;
    uint32_t clip_count2 = 0;
    uint32_t isolated_low_bursts1 = 0;
    uint32_t rail_low_bursts1 = 0;
    uint32_t completed_samples = 0;
    int stats_raw_min1 = INT_MAX;
    int stats_raw_max1 = INT_MIN;
    int stats_raw_min2 = INT_MAX;
    int stats_raw_max2 = INT_MIN;
    int64_t last_sample_us = 0;
    int64_t last_battery_us = 0;
    int64_t stats_start_us = esp_timer_get_time();
    int64_t max_sample_delta_us = 0;
    int64_t max_processing_us = 0;

    ESP_LOGI(TAG, "sample_task started: VO1->GPIO1/ADC1_CH0, VO2->GPIO2/ADC1_CH1");

    while (1) {
        uint32_t pending_ticks = ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        int64_t sample_start_us = esp_timer_get_time();

        sample_control_t control = {0};
        if (xQueueReceive(s_control_queue, &control, 0) == pdTRUE) {
            /* 按需选择性应用：
             * - 未变化的通道不动它的滤波状态（波形不抖）；
             * - 采样率未变就不重启定时器（不产生采样断点，本tick继续采样）；
             * - 增益未变就不重写SPI寄存器；
             * - 与当前配置完全一致的命令已在 host_cmd_received 拦截，不会到达这里。 */
            bool rate_changed = (control.sample_interval_us != current_sample_interval_us);
            bool ch1_gain_changed = (control.ch1_config != current_ch1_config);
            bool ch2_gain_changed = (control.ch2_config != current_ch2_config);
            bool ch1_changed = ch1_gain_changed || (control.ch1_filter != ch1_filter_enabled);
            bool ch2_changed = ch2_gain_changed || (control.ch2_filter != ch2_filter_enabled);
            bool any_filter_reset = rate_changed || ch1_changed || ch2_changed;

            if (rate_changed) {
                portENTER_CRITICAL(&s_tick_gate);
                s_tick_delivery_enabled = false;
                portEXIT_CRITICAL(&s_tick_gate);

                esp_err_t stop_err = esp_timer_stop(s_sample_timer);
                if (stop_err != ESP_OK && stop_err != ESP_ERR_INVALID_STATE) {
                    ESP_LOGE(TAG, "Failed to stop sample timer: %s", esp_err_to_name(stop_err));
                }
                ulTaskNotifyTake(pdTRUE, 0);
            }

            if (ch1_gain_changed || ch2_gain_changed) {
                ks1092_write_channel_regs(control.ch1_config, control.ch2_config);
            }
            current_ch1_config = control.ch1_config;
            current_ch2_config = control.ch2_config;
            ch1_filter_enabled = control.ch1_filter;
            ch2_filter_enabled = control.ch2_filter;
            device_enabled = control.enabled;

            if (rate_changed) {
                current_sample_interval_us = control.sample_interval_us;
                iir_filter_set_sample_rate(current_sample_interval_us);
                ksfilter_set_sample_rate(current_sample_interval_us);
                heart_rate_set_sample_rate(current_sample_interval_us);
            }
            if (ch1_changed || rate_changed) {
                /* 通道1相关：心率和脱落检测都基于通道1 */
                iir_filter_reset();
                ksfilter_reset();
                lvbo_reset();
                smooth_primed1 = false;
                memset(avg_rate_list, 0, sizeof(avg_rate_list));
                memset(lo_buf, 0, sizeof(lo_buf));
                avg_rate = 0;
                count_HR = 0;
                lo_idx = 0;
                lo_count = 0;
            }
            if (ch2_changed || rate_changed) {
                iir1_filter_reset();
                ksfilter1_reset();
                smooth_primed2 = false;
            }
            if (any_filter_reset) {
                s_filter_generation++;
                last_sample_us = 0;
                xQueueReset(s_transport_queue);
            }

            if (rate_changed) {
                ESP_ERROR_CHECK(esp_timer_start_periodic(s_sample_timer,
                                                         current_sample_interval_us));
                portENTER_CRITICAL(&s_tick_gate);
                s_tick_delivery_enabled = true;
                portEXIT_CRITICAL(&s_tick_gate);
                ESP_LOGI(TAG,
                         "CMD applied (rate %.0fHz): filter1=%s filter2=%s device=%s",
                         1000000.0 / current_sample_interval_us,
                         on_off_str(ch1_filter_enabled != 0),
                         on_off_str(ch2_filter_enabled != 0),
                         on_off_str(device_enabled));
                continue; /* 等新定时器的第一个tick */
            }
            ESP_LOGI(TAG,
                     "CMD applied (selective): changed[rate=%d ch1=%d ch2=%d] device=%s",
                     (int)rate_changed, (int)ch1_changed, (int)ch2_changed,
                     on_off_str(device_enabled));
            /* 采样率未变：本tick照常继续采样，无断点 */
        }

        if (pending_ticks > 1) {
            // Never fabricate back-to-back ADC values for elapsed timer periods.
            // Record the loss and resume from the current physical signal instead.
            missed_ticks += pending_ticks - 1;
        }

        if (last_sample_us != 0) {
            int64_t delta_us = sample_start_us - last_sample_us;
            if (delta_us > max_sample_delta_us) {
                max_sample_delta_us = delta_us;
            }
        }
        last_sample_us = sample_start_us;

        adc_reading_t reading1 = {0};
        adc_reading_t reading2 = {0};
        int signal_samples = signal_oversample_count();
        read_adc_averaged(ADC_CH1, s_signal_mv_lut,
                          signal_samples, &reading1);
        read_adc_averaged(ADC_CH2, s_signal_mv_lut,
                          signal_samples, &reading2);

        clip_count1 += reading1.clip_samples;
        clip_count2 += reading2.clip_samples;
        if (reading1.raw_min <= ADC_RAW_CLIP_LOW) {
            if (reading1.raw_max > ADC_RAW_CLIP_LOW + 100) {
                isolated_low_bursts1++;
            } else {
                rail_low_bursts1++;
            }
        }
        if (reading1.raw_min < stats_raw_min1) stats_raw_min1 = reading1.raw_min;
        if (reading1.raw_max > stats_raw_max1) stats_raw_max1 = reading1.raw_max;
        if (reading2.raw_min < stats_raw_min2) stats_raw_min2 = reading2.raw_min;
        if (reading2.raw_max > stats_raw_max2) stats_raw_max2 = reading2.raw_max;

        double ad_v1 = reading1.mv / 1000.0;
        double ad_v2 = reading2.mv / 1000.0;

#if SEND_RAW_ADC_FOR_DEBUG
        filter_out1 = ad_v1;
        filter_out2 = ad_v2;
#else
        if (ch1_filter_enabled) {
            filter_out1 = filter(IIR_Filter1_All(ad_v1)) + 0.9;
        } else {
            filter_out1 = ad_v1;
        }

        if (ch2_filter_enabled) {
            filter_out2 = filter1(IIR1_Filter1_All(ad_v2)) + 0.9;
        } else {
            filter_out2 = ad_v2;
        }
#endif

#if ECG_POST_SMOOTH_ENABLE
        if (ch1_filter_enabled) {
            filter_out1 = ecg_post_smooth(filter_out1, smooth_state1, &smooth_primed1);
        } else {
            smooth_primed1 = false;
        }

        if (ch2_filter_enabled) {
            filter_out2 = ecg_post_smooth(filter_out2, smooth_state2, &smooth_primed2);
        } else {
            smooth_primed2 = false;
        }
#endif

        int now_rate = get_heart_rate((float)(filter_out1 * 1000.0));
        count_HR++;
        int heart_rate_window = (int)(1000000UL / current_sample_interval_us);
        if (count_HR >= heart_rate_window) {
            avg_rate_list[0] = avg_rate_list[1];
            avg_rate_list[1] = avg_rate_list[2];
            avg_rate_list[2] = avg_rate_list[3];
            avg_rate_list[3] = avg_rate_list[4];
            avg_rate_list[4] = now_rate;
            count_HR = 0;
            avg_rate = 0;
            for (int i = 0; i < 5; i++) {
                avg_rate += avg_rate_list[i];
            }
            avg_rate /= 5;
        }

        uint8_t lead_off = detect_lead_off((int)(reading1.mv + 0.5));

        int64_t now_us = esp_timer_get_time();
        if (last_battery_us == 0 ||
            now_us - last_battery_us >= BATTERY_SAMPLE_INTERVAL_US) {
            update_battery_level();
            last_battery_us = now_us;
        }

        if (device_enabled && (uart_is_connected() || ble_is_connected())) {
            sample_transport_item_t item = {
                .ch1 = encode_sample_voltage(filter_out1),
                .ch2 = encode_sample_voltage(filter_out2),
                .heart_rate = (uint8_t)avg_rate,
                .lead_off = lead_off,
                .battery = battery,
                .generation = s_filter_generation,
            };
            if (xQueueSend(s_transport_queue, &item, 0) != pdTRUE) {
                queue_drops++;
            }
        }

        completed_samples++;
        int64_t processing_us = esp_timer_get_time() - sample_start_us;
        if (processing_us > max_processing_us) {
            max_processing_us = processing_us;
        }

        now_us = esp_timer_get_time();
        if (now_us - stats_start_us >= SAMPLE_STATS_INTERVAL_US) {
            ESP_LOGI(TAG,
                     "Sample stats: done=%lu missed=%lu queue_drop=%lu clip1=%lu clip2=%lu low_outlier1=%lu low_rail1=%lu raw1=%d..%d raw2=%d..%d max_dt=%lldus max_work=%lldus cfg=0x%02X/0x%02X gen=%lu",
                     (unsigned long)completed_samples,
                     (unsigned long)missed_ticks,
                     (unsigned long)queue_drops,
                     (unsigned long)clip_count1,
                     (unsigned long)clip_count2,
                     (unsigned long)isolated_low_bursts1,
                     (unsigned long)rail_low_bursts1,
                     stats_raw_min1, stats_raw_max1,
                     stats_raw_min2, stats_raw_max2,
                     (long long)max_sample_delta_us,
                     (long long)max_processing_us,
                     (unsigned int)current_ch1_config,
                     (unsigned int)current_ch2_config,
                     (unsigned long)s_filter_generation);

            missed_ticks = 0;
            queue_drops = 0;
            clip_count1 = 0;
            clip_count2 = 0;
            isolated_low_bursts1 = 0;
            rail_low_bursts1 = 0;
            completed_samples = 0;
            stats_raw_min1 = INT_MAX;
            stats_raw_max1 = INT_MIN;
            stats_raw_min2 = INT_MAX;
            stats_raw_max2 = INT_MIN;
            max_sample_delta_us = 0;
            max_processing_us = 0;
            stats_start_us = now_us;
        }
    }
}

void app_main(void)
{
#if PROTOCOL_UART0_MUTE_LOGS
    esp_log_level_set("*", ESP_LOG_NONE);
#endif

    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_err);

    ESP_LOGI(TAG, "System start");
    ESP_LOGI(TAG, "ADC samples KS1092 analog outputs; BLE receives commands; SPI writes KS1092 registers");
    ESP_LOGI(TAG, "Pins: SPI MOSI=GPIO%d MISO=GPIO%d SCK=GPIO%d CS=GPIO%d; ADC CH1=GPIO1/ADC%d CH2=GPIO2/ADC%d",
             SPI1_MOSI_PIN, SPI1_MISO_PIN, SPI1_SCK_PIN, KS1092_CS_PIN, ADC_CH1, ADC_CH2);
    ESP_LOGI(TAG, "Default KS1092 config: CH1SET=0x%02X CH2SET=0x%02X",
             KS1092_CH1_CONFIG, KS1092_CH2_CONFIG);
    init_adc();

    if (!init_ks1092()) {
        ESP_LOGE(TAG, "KS1092 SPI control init failed, continuing ADC/BLE for debug");
    }

    vTaskDelay(pdMS_TO_TICKS(KS1092_POST_INIT_DELAY_MS));

    iir_filter_set_sample_rate(current_sample_interval_us);
    ksfilter_set_sample_rate(current_sample_interval_us);
    heart_rate_set_sample_rate(current_sample_interval_us);

    s_transport_queue = xQueueCreate(SAMPLE_TRANSPORT_QUEUE_LEN,
                                     sizeof(sample_transport_item_t));
    s_control_queue = xQueueCreate(1, sizeof(sample_control_t));
    configASSERT(s_transport_queue != NULL);
    configASSERT(s_control_queue != NULL);

    ble_init();
    uart_transport_init();

    ESP_LOGI(TAG, "Sampling at %d Hz, ADC channels %d and %d", SAMPLE_RATE_HZ, ADC_CH1, ADC_CH2);
    BaseType_t transport_ok = xTaskCreatePinnedToCore(transport_task, "transport_task",
                                                     4096, NULL,
                                                     TRANSPORT_TASK_PRIORITY, NULL, 0);
    BaseType_t sample_ok = xTaskCreatePinnedToCore(sample_task, "sample_task", 16384, NULL,
                                                  SAMPLE_TASK_PRIORITY,
                                                  &s_sample_task_handle, 1);
    configASSERT(transport_ok == pdPASS);
    configASSERT(sample_ok == pdPASS);

    // The task handle must exist before the timer can deliver its first notification.
    init_sample_timer();
    ESP_LOGI(TAG, "Sampling at %d Hz, BLE advertising as 'BLE_EEG'", SAMPLE_RATE_HZ);
}

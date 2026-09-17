#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/logging/log.h>

#include "KS1092.h"
#include "ble.h"
#include "uart.h"
#include "heart_rate.h"
#include "iir_filter.h"
#include "ksfilter.h"
#include "lvbo.h"

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

#define KS1092_CH1_CONFIG 0x20
#define KS1092_CH2_CONFIG 0x00
#define KS1092_POST_INIT_DELAY_MS 800

/* ADC1 channels: VO1 -> GPIO1/CH0, VO2 -> GPIO2/CH1, battery -> GPIO3/CH2. */
#define ADC_CH1 0
#define ADC_CH2 1
#define ADC_BATT 2
#define ADC_SIGNAL_OVERSAMPLE_COUNT 6
#define ADC_SIGNAL_OVERSAMPLE_FAST_COUNT 2
#define ADC_BATT_OVERSAMPLE_COUNT 4
#define ADC_SETTLE_DISCARD_COUNT 1
#define ADC_RAW_CLIP_LOW 20
#define ADC_RAW_CLIP_HIGH 4075
#define ADC_RAW_MAX 4095
#define SAMPLE_RATE_HZ 500
#define SEND_RAW_ADC_FOR_DEBUG 0
#define ECG_POST_SMOOTH_ENABLE 1
#define BATTERY_SAMPLE_INTERVAL_MS 1000
#define SAMPLE_STATS_INTERVAL_MS 5000
#define SAMPLE_TRANSPORT_QUEUE_LEN 64
#define SAMPLE_TASK_PRIORITY 10
#define TRANSPORT_TASK_PRIORITY 4

#define LO_WINDOW 50
#define LDF_LEAD_OFF_THRESHOLD_DB 35

#define SAMPLE_THREAD_STACK_SIZE 16384
#define TRANSPORT_THREAD_STACK_SIZE 4096

static volatile bool device_enabled = true;
static volatile uint8_t ch1_filter_enabled = 1;
static volatile uint8_t ch2_filter_enabled = 1;
static volatile uint8_t current_ch1_config = KS1092_CH1_CONFIG;
static volatile uint8_t current_ch2_config = KS1092_CH2_CONFIG;
static volatile uint32_t s_filter_generation = 0;

/* 开机/每次新连接后的第一条命令强制执行并重写KS寄存器：
 * 设备重置后芯片通道2默认是关闭的，必须收到一次寄存器写入才会打开；
 * 同一连接内后续重复的相同命令（保活）仍按需跳过，避免波形抖动。 */
static volatile bool s_force_apply_next_cmd = true;

void main_force_next_cmd(void)
{
	s_force_apply_next_cmd = true;
}

static const struct adc_dt_spec adc_ch1 =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
static const struct adc_dt_spec adc_ch2 =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 1);
static const struct adc_dt_spec adc_batt =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 2);

/* ADC 读取失败计数（用于诊断波形不稳定是否来自读取失败） */
static volatile uint32_t s_adc_err_ch1;
static volatile uint32_t s_adc_err_ch2;
static volatile uint32_t s_adc_err_batt;

static struct k_timer s_sample_timer;
static struct k_sem s_sample_sem;
static uint32_t current_sample_interval_us = 1000000 / SAMPLE_RATE_HZ;

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
	bool force_regs;
} sample_control_t;

typedef struct {
	double raw_avg;
	double mv;
	int raw_min;
	int raw_max;
	uint32_t clip_samples;
} adc_reading_t;

K_MSGQ_DEFINE(s_transport_queue, sizeof(sample_transport_item_t),
	      SAMPLE_TRANSPORT_QUEUE_LEN, 4);
K_MSGQ_DEFINE(s_control_queue, sizeof(sample_control_t), 1, 4);

K_KERNEL_STACK_DEFINE(sample_stack, SAMPLE_THREAD_STACK_SIZE);
K_KERNEL_STACK_DEFINE(transport_stack, TRANSPORT_THREAD_STACK_SIZE);
static struct k_thread sample_thread_data;
static struct k_thread transport_thread_data;

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
	return current_sample_interval_us <= 1000
		       ? ADC_SIGNAL_OVERSAMPLE_FAST_COUNT
		       : ADC_SIGNAL_OVERSAMPLE_COUNT;
}

static const char *ks1092_ch1_gain_preset_str(uint8_t reg_value)
{
	switch (reg_value) {
	case 0x20: return "known preset: 9x * 40x = 360x";
	case 0x30: return "known preset: 9x * 60x = 540x";
	case 0x34: return "known preset: 9x * 80x = 720x";
	case 0x38: case 0x18: return "known preset: 9x * 120x = 1080x";
	case 0x3C: return "known preset: 9x * 160x = 1440x";
	case 0x22: return "known preset: 17x * 40x = 680x";
	case 0x32: return "known preset: 17x * 60x = 1020x";
	case 0x36: return "known preset: 17x * 80x = 1360x";
	case 0x3A: return "known preset: 17x * 120x = 2040x";
	case 0x3E: return "known preset: 17x * 160x = 2720x";
	default: return "custom/unknown preset; stage1 in {9x,17x}, stage2 in {40x,60x,80x,120x,160x}";
	}
}

static const char *ks1092_ch2_gain_preset_str(uint8_t reg_value)
{
	switch (reg_value) {
	case 0x00: return "known preset: 9x * 40x = 360x";
	case 0x10: return "known preset: 9x * 60x = 540x";
	case 0x14: return "known preset: 9x * 80x = 720x";
	case 0x18: return "known preset: 9x * 120x = 1080x";
	case 0x1C: return "known preset: 9x * 160x = 1440x";
	case 0x02: return "known preset: 17x * 40x = 680x";
	case 0x12: return "known preset: 17x * 60x = 1020x";
	case 0x16: return "known preset: 17x * 80x = 1360x";
	case 0x1A: return "known preset: 17x * 120x = 2040x";
	case 0x1E: return "known preset: 17x * 160x = 2720x";
	default: return "custom/unknown preset; stage1 in {9x,17x}, stage2 in {40x,60x,80x,120x,160x}";
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
		if (lo_buf[i] < vmin) vmin = lo_buf[i];
		if (lo_buf[i] > vmax) vmax = lo_buf[i];
	}

	int range = vmax - vmin;
	/* Full-scale millivolt value depends on the gain; approximate using the
	 * 1.1 V full scale with 12-bit resolution (adc_raw_to_millivolts_dt). */
	int signal_full_scale_mv = 1100;
	if (range < 20 || LDF((float)mv) < LDF_LEAD_OFF_THRESHOLD_DB) {
		return 1;
	}
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

static void sample_timer_cb(struct k_timer *timer)
{
	k_sem_give(&s_sample_sem);
}

static int read_adc_raw(const struct adc_dt_spec *spec)
{
	int16_t buf;
	struct adc_sequence seq = {
		.buffer = &buf,
		.buffer_size = sizeof(buf),
	};

	(void)adc_sequence_init_dt(spec, &seq);
	int err = adc_read_dt(spec, &seq);
	if (err < 0) {
		/* 统计 ADC 读取失败次数，用于区分"读取失败返回0"与"真实信号抖动" */
		if (spec == &adc_ch1) {
			s_adc_err_ch1++;
		} else if (spec == &adc_ch2) {
			s_adc_err_ch2++;
		} else {
			s_adc_err_batt++;
		}
		return 0;
	}
	return (int)buf;
}

static double adc_raw_to_mv(const struct adc_dt_spec *spec, int raw)
{
	/* Convert an explicit raw reading to millivolts using the channel's
	 * configured gain/reference, then scale to volts-compatible double. */
	int32_t mv = (int32_t)raw;
	int err = adc_raw_to_millivolts_dt(spec, &mv);
	if (err < 0) {
		/* Fallback: assume Vref = reference and 12-bit resolution. */
		return (double)raw * 1100.0 / ADC_RAW_MAX;
	}
	return (double)mv;
}

static void read_adc_averaged(const struct adc_dt_spec *spec,
			      int sample_count, adc_reading_t *reading)
{
	int64_t raw_sum = 0;
	int sample_count_safe = sample_count > 0 ? sample_count : 1;

	for (int i = 0; i < ADC_SETTLE_DISCARD_COUNT; i++) {
		(void)read_adc_raw(spec);
	}

	reading->raw_min = INT_MAX;
	reading->raw_max = INT_MIN;
	reading->clip_samples = 0;

	for (int i = 0; i < sample_count_safe; i++) {
		int raw = read_adc_raw(spec);
		raw_sum += raw;
		if (raw < reading->raw_min) reading->raw_min = raw;
		if (raw > reading->raw_max) reading->raw_max = raw;
		if (raw <= ADC_RAW_CLIP_LOW || raw >= ADC_RAW_CLIP_HIGH) {
			reading->clip_samples++;
		}
	}

	int64_t filtered_sum = raw_sum;
	int filtered_count = sample_count_safe;
	if (sample_count_safe >= 4) {
		filtered_sum -= reading->raw_min;
		filtered_sum -= reading->raw_max;
		filtered_count -= 2;
	}

	reading->raw_avg = (double)filtered_sum / filtered_count;
	reading->mv = adc_raw_to_mv(spec, (int)reading->raw_avg);
}

static void init_adc(void)
{
	if (!adc_is_ready_dt(&adc_ch1) || !adc_is_ready_dt(&adc_ch2) ||
	    !adc_is_ready_dt(&adc_batt)) {
		LOG_ERR("ADC controller not ready");
		return;
	}

	adc_channel_setup_dt(&adc_ch1);
	adc_channel_setup_dt(&adc_ch2);
	adc_channel_setup_dt(&adc_batt);
	LOG_INF("ADC initialized (CH1/CH2/CH_BATT)");
}

static void init_sample_timer(void)
{
	current_sample_interval_us = 1000000 / SAMPLE_RATE_HZ;
	k_timer_init(&s_sample_timer, sample_timer_cb, NULL);
	k_timer_start(&s_sample_timer,
		      K_USEC(current_sample_interval_us),
		      K_USEC(current_sample_interval_us));
}

static bool init_ks1092(void)
{
	LOG_INF("Initializing KS1092...");
	KS1092_Init();

	ks1092_write_channel_regs(KS1092_CH1_CONFIG, KS1092_CH2_CONFIG);
	k_msleep(500);

	ks1092_write_channel_regs(KS1092_CH1_CONFIG, KS1092_CH2_CONFIG);
	current_ch1_config = KS1092_CH1_CONFIG;
	current_ch2_config = KS1092_CH2_CONFIG;

	LOG_INF("KS1092 initialized OK");
	return true;
}

static void update_battery_level(void)
{
	adc_reading_t batt_reading = {0};
	read_adc_averaged(&adc_batt, ADC_BATT_OVERSAMPLE_COUNT, &batt_reading);

	double battery_v = batt_reading.mv / 1000.0;
	if (battery_v < 1.3) {
		battery = 1;
	} else if (battery_v > 1.6) {
		battery = 100;
	} else {
		battery = (uint8_t)((battery_v - 1.3) * (100.0 / (1.6 - 1.3)) + 0.5);
	}
}

static void host_cmd_received(const uint8_t *cmd, int len, bool from_uart)
{
	if (len != 6) {
		return;
	}

	LOG_INF("%s CMD: CH1=0x%02X CH2=0x%02X SR=%d F1=%d F2=%d SW=%d",
		from_uart ? "UART" : "BLE",
		cmd[0], cmd[1], cmd[2], cmd[3], cmd[4], cmd[5]);
	LOG_INF("%s CMD decode: CH1SET=0x%02X (%s), CH2SET=0x%02X (%s), SR=%luHz, CH1 filter=%s, CH2 filter=%s, device=%s",
		from_uart ? "UART" : "BLE",
		cmd[0], ks1092_ch1_gain_preset_str(cmd[0]),
		cmd[1], ks1092_ch2_gain_preset_str(cmd[1]),
		(unsigned long)cmd_sample_rate_hz(cmd[2], from_uart),
		on_off_str(cmd[3] != 0x00),
		on_off_str(cmd[4] != 0x00),
		on_off_str(cmd[5] != 0x00));

	uint32_t sample_interval_us = cmd_sample_interval_us(cmd[2], from_uart);

	/* 上位机重复命令拦截的例外：开机或新连接后的第一条命令总是强制
	 * 执行——设备重置后通道2默认关闭，需要一次真实的寄存器写入才会
	 * 打开；此时命令与固件默认配置完全相同，不豁免就会被拦截。 */
	bool force_apply = s_force_apply_next_cmd;
	s_force_apply_next_cmd = false;

	/* 上位机（尤其串口模式）会周期性重发相同设置命令作为保活。设置与
	 * 当前完全一致时直接忽略：避免每次保活都重置滤波器、重启采样定时器，
	 * 在心电数据上留下周期性毛刺（会干扰HRV分析）。volatile 变量先取快照再比。 */
	uint8_t cur_ch1 = current_ch1_config;
	uint8_t cur_ch2 = current_ch2_config;
	uint32_t cur_interval = current_sample_interval_us;
	if (!force_apply &&
	    cmd[0] == cur_ch1 &&
	    cmd[1] == cur_ch2 &&
	    (cmd[3] != 0x00) == (ch1_filter_enabled != 0) &&
	    (cmd[4] != 0x00) == (ch2_filter_enabled != 0) &&
	    (cmd[5] != 0x00) == (device_enabled != 0) &&
	    sample_interval_us == cur_interval) {
		LOG_INF("CMD identical to current config, skipped (keepalive)");
		return;
	}

	sample_control_t control = {
		.ch1_config = cmd[0],
		.ch2_config = cmd[1],
		.ch1_filter = (cmd[3] != 0x00),
		.ch2_filter = (cmd[4] != 0x00),
		.enabled = (cmd[5] != 0x00),
		.sample_interval_us = sample_interval_us,
		.force_regs = force_apply,
	};

	k_msgq_put(&s_control_queue, &control, K_NO_WAIT);
	LOG_INF("CMD queued for the sampling task");
}

void ble_on_cmd_received(const uint8_t *cmd, int len)
{
	host_cmd_received(cmd, len, false);
}

void uart_on_cmd_received(const uint8_t *cmd, int len)
{
	host_cmd_received(cmd, len, true);
}

static void transport_thread(void *arg1, void *arg2, void *arg3)
{
	(void)arg1; (void)arg2; (void)arg3;

	uint16_t ch1_buf[4] = {0};
	uint16_t ch2_buf[4] = {0};
	int sample_idx = 0;
	uint32_t ble_send_failures = 0;
	uint32_t uart_samples = 0;
	uint32_t active_generation = UINT32_MAX;
	int64_t stats_start_ms = k_uptime_get();

	while (1) {
		sample_transport_item_t item = {0};
		if (k_msgq_get(&s_transport_queue, &item, K_MSEC(20)) != 0) {
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

		int64_t now_ms = k_uptime_get();
		if (now_ms - stats_start_ms >= SAMPLE_STATS_INTERVAL_MS) {
			LOG_INF("Transport stats: BLE notify failures=%lu UART samples=%lu",
				(unsigned long)ble_send_failures,
				(unsigned long)uart_samples);
			ble_send_failures = 0;
			uart_samples = 0;
			stats_start_ms = now_ms;
		}
	}
}

static void sample_thread(void *arg1, void *arg2, void *arg3)
{
	(void)arg1; (void)arg2; (void)arg3;

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
	int64_t last_sample_ms = 0;
	int64_t last_battery_ms = 0;
	int64_t stats_start_ms = k_uptime_get();

	LOG_INF("sample_thread started: VO1->GPIO1/ADC1_CH0, VO2->GPIO2/ADC1_CH1");

	while (1) {
		/* Wait for a sample tick. */
		k_sem_take(&s_sample_sem, K_FOREVER);
		int64_t sample_start_ms = k_uptime_get();

		sample_control_t control = {0};
		if (k_msgq_get(&s_control_queue, &control, K_NO_WAIT) == 0) {
			/* 按需选择性应用（与ESP-IDF版保持一致）：
			 * - 未变化的通道不动它的滤波状态（波形不抖）；
			 * - 采样率未变就不重启定时器（本tick继续采样，无断点）；
			 * - 增益未变就不重写SPI寄存器；
			 * - 与当前配置完全一致的命令已在 host_cmd_received 拦截。 */
			bool rate_changed = (control.sample_interval_us != current_sample_interval_us);
			bool ch1_gain_changed = (control.ch1_config != current_ch1_config);
			bool ch2_gain_changed = (control.ch2_config != current_ch2_config);
			bool ch1_changed = ch1_gain_changed || (control.ch1_filter != ch1_filter_enabled);
			bool ch2_changed = ch2_gain_changed || (control.ch2_filter != ch2_filter_enabled);
			bool any_filter_reset = rate_changed || ch1_changed || ch2_changed;

			if (rate_changed) {
				k_timer_stop(&s_sample_timer);
				/* drain any pending semaphore */
				while (k_sem_take(&s_sample_sem, K_NO_WAIT) == 0) {
				}
			}

			if (control.force_regs || ch1_gain_changed || ch2_gain_changed) {
				/* force_regs：连接后首条命令无条件重写，确保设备重置后
				 * 通道2被重新打开（即便增益值与固件默认一致） */
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
				last_sample_ms = 0;
				k_msgq_purge(&s_transport_queue);
			}

			if (rate_changed) {
				k_timer_start(&s_sample_timer,
					      K_USEC(current_sample_interval_us),
					      K_USEC(current_sample_interval_us));
				LOG_INF("CMD applied (rate %luHz): filter1=%s filter2=%s device=%s",
					(unsigned long)(1000000UL / current_sample_interval_us),
					on_off_str(ch1_filter_enabled != 0),
					on_off_str(ch2_filter_enabled != 0),
					on_off_str(device_enabled));
				continue; /* 等新定时器的第一个tick */
			}
			LOG_INF("CMD applied (selective): changed[rate=%d ch1=%d ch2=%d] device=%s",
				(int)rate_changed, (int)ch1_changed, (int)ch2_changed,
				on_off_str(device_enabled));
			/* 采样率未变：本tick照常继续采样，无断点 */
		}

		adc_reading_t reading1 = {0};
		adc_reading_t reading2 = {0};
		int signal_samples = signal_oversample_count();
		read_adc_averaged(&adc_ch1, signal_samples, &reading1);
		read_adc_averaged(&adc_ch2, signal_samples, &reading2);

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

		int64_t now_ms = k_uptime_get();
		if (last_battery_ms == 0 ||
		    now_ms - last_battery_ms >= BATTERY_SAMPLE_INTERVAL_MS) {
			update_battery_level();
			last_battery_ms = now_ms;
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
			if (k_msgq_put(&s_transport_queue, &item, K_NO_WAIT) != 0) {
				queue_drops++;
			}
		}

		completed_samples++;

		now_ms = k_uptime_get();
		if (now_ms - stats_start_ms >= SAMPLE_STATS_INTERVAL_MS) {
			LOG_INF("Sample stats: done=%lu missed=%lu queue_drop=%lu clip1=%lu clip2=%lu low_outlier1=%lu low_rail1=%lu raw1=%d..%d raw2=%d..%d cfg=0x%02X/0x%02X gen=%lu adc_err1=%lu adc_err2=%lu",
				(unsigned long)completed_samples,
				(unsigned long)missed_ticks,
				(unsigned long)queue_drops,
				(unsigned long)clip_count1,
				(unsigned long)clip_count2,
				(unsigned long)isolated_low_bursts1,
				(unsigned long)rail_low_bursts1,
				stats_raw_min1, stats_raw_max1,
				stats_raw_min2, stats_raw_max2,
				(unsigned int)current_ch1_config,
				(unsigned int)current_ch2_config,
				(unsigned long)s_filter_generation,
				(unsigned long)s_adc_err_ch1,
				(unsigned long)s_adc_err_ch2);
			ble_dump_state();

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
			stats_start_ms = now_ms;
		}

		(void)last_sample_ms;
		(void)sample_start_ms;
	}
}

int main(void)
{
	LOG_INF("System start");
	LOG_INF("ADC samples KS1092 analog outputs; BLE receives commands; SPI writes KS1092 registers");
	LOG_INF("Pins: SPI MOSI=GPIO%d MISO=GPIO%d SCK=GPIO%d CS=GPIO%d; ADC CH1=GPIO1/ADC%d CH2=GPIO2/ADC%d",
		SPI1_MOSI_PIN, SPI1_MISO_PIN, SPI1_SCK_PIN, 10, ADC_CH1, ADC_CH2);

	init_adc();

	if (!init_ks1092()) {
		LOG_ERR("KS1092 SPI control init failed, continuing ADC/BLE for debug");
	}

	k_msleep(KS1092_POST_INIT_DELAY_MS);

	iir_filter_set_sample_rate(current_sample_interval_us);
	ksfilter_set_sample_rate(current_sample_interval_us);
	heart_rate_set_sample_rate(current_sample_interval_us);

	k_sem_init(&s_sample_sem, 0, K_SEM_MAX_LIMIT);

	ble_init();
	uart_transport_init();

	LOG_INF("Sampling at %d Hz, ADC channels %d and %d", SAMPLE_RATE_HZ, ADC_CH1, ADC_CH2);

	k_thread_create(&transport_thread_data, transport_stack,
			K_KERNEL_STACK_SIZEOF(transport_stack),
			transport_thread, NULL, NULL, NULL,
			TRANSPORT_TASK_PRIORITY, 0, K_NO_WAIT);
	k_thread_create(&sample_thread_data, sample_stack,
			K_KERNEL_STACK_SIZEOF(sample_stack),
			sample_thread, NULL, NULL, NULL,
			SAMPLE_TASK_PRIORITY, 0, K_NO_WAIT);

	init_sample_timer();
	LOG_INF("Sampling at %d Hz, BLE advertising as 'BLE_EEG'", SAMPLE_RATE_HZ);

	return 0;
}
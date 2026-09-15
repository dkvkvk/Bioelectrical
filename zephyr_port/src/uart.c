#include "uart.h"
#include "ble.h"
#include "protocol_crc.h"

#include <zephyr/kernel.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(uart_transport, LOG_LEVEL_INF);

#define UART_DEV DT_ALIAS(uart_0)

#define UART_BAUD 115200
#define UART_CMD_LEN 6
#define UART_SAMPLE_FRAME_LEN 9
#define UART_INTER_BYTE_TIMEOUT_MS 200
#define UART_SESSION_TIMEOUT_MS 30000
#define UART_MAX_READ_SIZE 16

#define UART_RX_THREAD_STACK_SIZE 2048
#define UART_RX_THREAD_PRIORITY 4

static const struct device *const uart_dev = DEVICE_DT_GET(UART_DEV);

static volatile bool s_uart_connected;
static volatile int64_t s_uart_last_rx_us;

static K_KERNEL_STACK_DEFINE(uart_rx_stack, UART_RX_THREAD_STACK_SIZE);
static struct k_thread uart_rx_thread_data;

extern void uart_on_cmd_received(const uint8_t *cmd, int len);

static bool enter_uart_link(void)
{
	if (ble_is_connected()) {
		return false;
	}

	if (!s_uart_connected) {
		s_uart_connected = true;
		ble_stop_advertising();
	}

	s_uart_last_rx_us = k_uptime_get();
	return true;
}

static void leave_uart_link(void)
{
	if (!s_uart_connected) {
		return;
	}

	s_uart_connected = false;
	ble_advertise_restart();
}

static void uart_rx_thread(void *arg1, void *arg2, void *arg3)
{
	(void)arg1;
	(void)arg2;
	(void)arg3;

	uint8_t cmd[UART_CMD_LEN];
	int cmd_len = 0;
	int64_t last_byte_us = 0;
	uint8_t buf[UART_MAX_READ_SIZE];

	while (1) {
		if (ble_is_connected()) {
			if (s_uart_connected) {
				s_uart_connected = false;
			}
			cmd_len = 0;
			k_msleep(100);
			continue;
		}

		/* Non-blocking poll: timeout 100 ms to match the original pacing. */
		int len = 0;
		int64_t now_us = k_uptime_get();

		len = uart_poll_in(uart_dev, &buf[0]);
		if (len < 0) {
			/* no data */
		} else {
			uint8_t byte = buf[0];
			if (cmd_len > 0 &&
			    (now_us - last_byte_us) > UART_INTER_BYTE_TIMEOUT_MS * 1000LL) {
				cmd_len = 0;
			}

			cmd[cmd_len++] = byte;
			last_byte_us = now_us;

			if (cmd_len == UART_CMD_LEN) {
				if (enter_uart_link()) {
					uart_on_cmd_received(cmd, UART_CMD_LEN);
				}
				cmd_len = 0;
			}
			continue;
		}

		if (cmd_len > 0 &&
		    (now_us - last_byte_us) > UART_INTER_BYTE_TIMEOUT_MS * 1000LL) {
			cmd_len = 0;
		}

		if (s_uart_connected &&
		    (now_us - s_uart_last_rx_us) > UART_SESSION_TIMEOUT_MS * 1000LL) {
			leave_uart_link();
		}

		k_msleep(1);
	}
}

void uart_transport_init(void)
{
	if (!device_is_ready(uart_dev)) {
		LOG_ERR("UART device not ready");
		return;
	}

	k_thread_create(&uart_rx_thread_data, uart_rx_stack,
			K_KERNEL_STACK_SIZEOF(uart_rx_stack),
			uart_rx_thread, NULL, NULL, NULL,
			UART_RX_THREAD_PRIORITY, 0, K_NO_WAIT);

	LOG_INF("UART transport initialized: UART0 @ %d 8N1", UART_BAUD);
}

bool uart_is_connected(void)
{
	return s_uart_connected;
}

void uart_send_sample_frame(uint16_t ch1, uint16_t ch2, uint8_t heart_rate)
{
	if (!s_uart_connected || ble_is_connected()) {
		return;
	}

	uint8_t buf[UART_SAMPLE_FRAME_LEN];
	buf[0] = 0xFF;
	buf[1] = 0x09;
	buf[2] = 0x2E;
	buf[3] = (uint8_t)(ch1 >> 8);
	buf[4] = (uint8_t)ch1;
	buf[5] = (uint8_t)(ch2 >> 8);
	buf[6] = (uint8_t)ch2;
	buf[7] = heart_rate;
	buf[8] = Fast_CRC_Cal8Bits(0x00, 8, buf);

	for (int i = 0; i < UART_SAMPLE_FRAME_LEN; i++) {
		uart_poll_out(uart_dev, buf[i]);
	}
}

void uart_send_debug_bytes(const uint8_t *data, size_t len)
{
	if (data == NULL || len == 0) {
		return;
	}

	for (size_t i = 0; i < len; i++) {
		uart_poll_out(uart_dev, data[i]);
	}
}
#include "uart.h"

#include "ble.h"
#include "protocol_crc.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "UART";

#define UART_PORT UART_NUM_0
#define UART_BAUD 115200
#define UART_TX_PIN UART_PIN_NO_CHANGE
#define UART_RX_PIN UART_PIN_NO_CHANGE
#define UART_RTS_PIN UART_PIN_NO_CHANGE
#define UART_CTS_PIN UART_PIN_NO_CHANGE
#define UART_RX_BUF_SIZE 2048
#define UART_TX_BUF_SIZE 2048
#define UART_CMD_LEN 6
#define UART_SAMPLE_FRAME_LEN 9
#define UART_INTER_BYTE_TIMEOUT_MS 200
#define UART_SESSION_TIMEOUT_MS 30000

static volatile bool s_uart_connected;
static volatile int64_t s_uart_last_rx_us;

extern void uart_on_cmd_received(const uint8_t *cmd, int len);
extern void main_force_next_cmd(void);

static bool enter_uart_link(void)
{
    if (ble_is_connected()) {
        return false;
    }

    if (!s_uart_connected) {
        s_uart_connected = true;
        main_force_next_cmd(); /* 新连接的第一条命令强制执行，打开通道2 */
        ble_stop_advertising();
        esp_log_level_set("*", ESP_LOG_NONE);
    }

    s_uart_last_rx_us = esp_timer_get_time();
    return true;
}

static void leave_uart_link(void)
{
    if (!s_uart_connected) {
        return;
    }

    s_uart_connected = false;
    uart_flush_input(UART_PORT);
    ble_advertise_restart();
}

static void uart_rx_task(void *arg)
{
    (void)arg;

    uint8_t cmd[UART_CMD_LEN];
    int cmd_len = 0;
    int64_t last_byte_us = 0;

    while (1) {
        if (ble_is_connected()) {
            if (s_uart_connected) {
                s_uart_connected = false;
            }
            cmd_len = 0;
            uart_flush_input(UART_PORT);
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        uint8_t byte = 0;
        int len = uart_read_bytes(UART_PORT, &byte, 1, pdMS_TO_TICKS(100));
        int64_t now_us = esp_timer_get_time();

        if (len == 1) {
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
    }
}

void uart_transport_init(void)
{
    uart_config_t uart_cfg = {
        .baud_rate = UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &uart_cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT,
                                 UART_TX_PIN,
                                 UART_RX_PIN,
                                 UART_RTS_PIN,
                                 UART_CTS_PIN));

    esp_err_t err = uart_driver_install(UART_PORT,
                                        UART_RX_BUF_SIZE,
                                        UART_TX_BUF_SIZE,
                                        0,
                                        NULL,
                                        0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_ERROR_CHECK(err);
    }

    uart_flush_input(UART_PORT);
    xTaskCreatePinnedToCore(uart_rx_task, "uart_rx_task", 4096, NULL, 4, NULL, 0);
    ESP_LOGI(TAG, "UART transport initialized: UART%d @ %d 8N1, no flow control",
             UART_PORT, UART_BAUD);
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

    uart_write_bytes(UART_PORT, buf, sizeof(buf));
}

void uart_send_debug_bytes(const uint8_t *data, size_t len)
{
    if (data == NULL || len == 0) {
        return;
    }

    uart_write_bytes(UART_PORT, data, len);
}

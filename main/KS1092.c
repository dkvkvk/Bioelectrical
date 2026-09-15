//////////////////////////////////////////////////////////////////////////////////
// KS108X/KS109X SPI test
// Date: 2021/11/27
// Version: V2.0 (ESP-IDF port)
// Copyright(C) Kingsense Electronics
// www.ks-chip.com
// All rights reserved
//////////////////////////////////////////////////////////////////////////////////

#include "KS1092.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define KS1092_RESET_PULSE_MS 20
#define KS1092_INTER_REG_DELAY_MS 2
#define KS1092_REG_WRITE_SETTLE_MS 20
#define KS1092_INIT_SETTLE_MS 500
#define KS1092_RESET_HIGH_SETTLE_MS 20

static void KS1092_Reset_Pulse(void)
{
    gpio_set_level(KS1092_RESET_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(KS1092_RESET_PULSE_MS));
    gpio_set_level(KS1092_RESET_PIN, 1);
    vTaskDelay(pdMS_TO_TICKS(KS1092_RESET_HIGH_SETTLE_MS));
}

static void KS1092_Write_Reg_Raw(uint8_t reg_address, uint8_t data_to_write)
{
    uint8_t tx_buf[3] = {
        (uint8_t)(0x20 | reg_address),
        0x00,
        data_to_write,
    };

    KS1092_CS_Enable();
    SPI1_Transfer(tx_buf, NULL, sizeof(tx_buf));
    KS1092_CS_Disable();
}

void KS1092_Init(void)
{
    gpio_config_t cs_conf = {
        .pin_bit_mask = (1ULL << KS1092_CS_PIN),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cs_conf);

    gpio_config_t reset_conf = {
        .pin_bit_mask = (1ULL << KS1092_RESET_PIN),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&reset_conf);

    KS1092_CS_Disable();
    KS1092_Reset_Pulse();

    SPI1_Init();
    vTaskDelay(pdMS_TO_TICKS(KS1092_INIT_SETTLE_MS));
}

void KS1092_CS_Enable(void)
{
    gpio_set_level(KS1092_CS_PIN, 0);
}

void KS1092_CS_Disable(void)
{
    gpio_set_level(KS1092_CS_PIN, 1);
}

void KS1092_Write_Reg(uint8_t reg_address, uint8_t data_to_write)
{
    KS1092_Write_Reg_Raw(reg_address, data_to_write);
    vTaskDelay(pdMS_TO_TICKS(KS1092_REG_WRITE_SETTLE_MS));
}

void KS1092_Write_Reg_Pair(uint8_t reg1, uint8_t value1, uint8_t reg2, uint8_t value2)
{
    KS1092_Write_Reg_Raw(reg1, value1);
    vTaskDelay(pdMS_TO_TICKS(KS1092_INTER_REG_DELAY_MS));
    KS1092_Write_Reg_Raw(reg2, value2);
    vTaskDelay(pdMS_TO_TICKS(KS1092_REG_WRITE_SETTLE_MS));
}

uint8_t KS1092_Read_Reg(uint8_t reg_address)
{
    uint8_t tx_buf[3] = {
        (uint8_t)(0x10 | reg_address),
        0x00,
        0xDD,
    };
    uint8_t rx_buf[3] = {0};

    KS1092_CS_Enable();
    SPI1_Transfer(tx_buf, rx_buf, sizeof(tx_buf));
    KS1092_CS_Disable();

    return rx_buf[2];
}

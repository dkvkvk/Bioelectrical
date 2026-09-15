//////////////////////////////////////////////////////////////////////////////////
// KS108X/KS109X SPI test
// Date: 2021/11/27
// Version: V2.0 (Zephyr port)
// Copyright(C) Kingsense Electronics
// www.ks-chip.com
// All rights reserved
//////////////////////////////////////////////////////////////////////////////////

#include "KS1092.h"

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(ks1092, LOG_LEVEL_INF);

#define KS1092_RESET_PULSE_MS 20
#define KS1092_INTER_REG_DELAY_MS 2
#define KS1092_REG_WRITE_SETTLE_MS 20
#define KS1092_INIT_SETTLE_MS 500
#define KS1092_RESET_HIGH_SETTLE_MS 20

/* The gpio-leds binding provides the "gpios" property; use GPIO_DT_SPEC_GET
 * with the aliased nodes. */
static const struct gpio_dt_spec ks1092_cs =
	GPIO_DT_SPEC_GET(KS1092_CS_NODE, gpios);
static const struct gpio_dt_spec ks1092_reset =
	GPIO_DT_SPEC_GET(KS1092_RESET_NODE, gpios);

static void KS1092_Reset_Pulse(void)
{
	gpio_pin_set_dt(&ks1092_reset, 0);
	k_msleep(KS1092_RESET_PULSE_MS);
	gpio_pin_set_dt(&ks1092_reset, 1);
	k_msleep(KS1092_RESET_HIGH_SETTLE_MS);
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
	if (!gpio_is_ready_dt(&ks1092_cs) || !gpio_is_ready_dt(&ks1092_reset)) {
		LOG_ERR("KS1092 GPIO not ready");
		return;
	}

	gpio_pin_configure_dt(&ks1092_cs, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&ks1092_reset, GPIO_OUTPUT_INACTIVE);

	KS1092_CS_Disable();
	KS1092_Reset_Pulse();

	SPI1_Init();
	k_msleep(KS1092_INIT_SETTLE_MS);
}

void KS1092_CS_Enable(void)
{
	gpio_pin_set_dt(&ks1092_cs, 1);
}

void KS1092_CS_Disable(void)
{
	gpio_pin_set_dt(&ks1092_cs, 0);
}

void KS1092_Write_Reg(uint8_t reg_address, uint8_t data_to_write)
{
	KS1092_Write_Reg_Raw(reg_address, data_to_write);
	k_msleep(KS1092_REG_WRITE_SETTLE_MS);
}

void KS1092_Write_Reg_Pair(uint8_t reg1, uint8_t value1, uint8_t reg2, uint8_t value2)
{
	KS1092_Write_Reg_Raw(reg1, value1);
	k_msleep(KS1092_INTER_REG_DELAY_MS);
	KS1092_Write_Reg_Raw(reg2, value2);
	k_msleep(KS1092_REG_WRITE_SETTLE_MS);
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
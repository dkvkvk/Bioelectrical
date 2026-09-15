//////////////////////////////////////////////////////////////////////////////////
// KS108X/KS109X SPI test
// Date: 2021/11/27
// Version: V2.0 (Zephyr port)
// Copyright(C) Kingsense Electronics
// www.ks-chip.com
// All rights reserved
//////////////////////////////////////////////////////////////////////////////////

#include "myspi.h"

#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(myspi, LOG_LEVEL_INF);

/* The KS1092 uses manual chip-select, so we bind directly to the SPI2 bus
 * controller and drive CS with the GPIO driver (KS1092 layer). SPI mode 1
 * (CPHA=1, CPOL=0), 8-bit words, master. */
static const struct device *spi_bus = DEVICE_DT_GET(DT_NODELABEL(spi2));

static struct spi_config spi_cfg = {
	.frequency = SPI1_CLK_FREQ,
	.operation = SPI_OP_MODE_MASTER | SPI_MODE_CPHA | SPI_WORD_SET(8),
	.slave = 0,
};

void SPI1_Init(void)
{
	if (!device_is_ready(spi_bus)) {
		LOG_ERR("SPI2 bus is not ready");
		return;
	}
	LOG_INF("SPI1 initialized (SPI2, %u Hz, mode 1)", SPI1_CLK_FREQ);
}

uint8_t SPI1_ReadWriteByte(uint8_t tx_data)
{
	uint8_t rx_data = 0;
	SPI1_Transfer(&tx_data, &rx_data, 1);
	return rx_data;
}

void SPI1_Transfer(const uint8_t *tx_data, uint8_t *rx_data, size_t len)
{
	struct spi_buf tx_buf = {
		.buf = (void *)tx_data,
		.len = len,
	};
	struct spi_buf rx_buf = {
		.buf = rx_data,
		.len = len,
	};
	struct spi_buf_set tx = {
		.buffers = &tx_buf,
		.count = 1,
	};
	struct spi_buf_set rx = {
		.buffers = &rx_buf,
		.count = 1,
	};

	spi_transceive(spi_bus, &spi_cfg, &tx, &rx);
}
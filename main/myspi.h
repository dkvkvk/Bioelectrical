#ifndef MY_SPI_H
#define MY_SPI_H

#include <stddef.h>
#include <stdint.h>
#include "driver/gpio.h"
#include "driver/spi_master.h"

// Board wiring:
// KS1092 SDI <- ESP32-S3 GPIO11, KS1092 SDO -> ESP32-S3 GPIO13.
#define SPI1_MOSI_PIN   11
#define SPI1_MISO_PIN   13
#define SPI1_SCK_PIN    12

#define SPI1_CLK_FREQ   4000000

extern spi_device_handle_t spi1_handle;

void SPI1_Init(void);
uint8_t SPI1_ReadWriteByte(uint8_t tx_data);
void SPI1_Transfer(const uint8_t *tx_data, uint8_t *rx_data, size_t len);

#endif // MY_SPI_H

#ifndef MY_SPI_H
#define MY_SPI_H

#include <stddef.h>
#include <stdint.h>
#include <zephyr/drivers/spi.h>

/*
 * KS1092 SPI wiring (matches the ESP-IDF project):
 *   MOSI = GPIO11, MISO = GPIO13, SCLK = GPIO12 (from spim2_default pinctrl)
 *   CS   = GPIO10 (driven manually by the application)
 */
#define SPI1_MOSI_PIN   11
#define SPI1_MISO_PIN   13
#define SPI1_SCK_PIN    12

#define SPI1_CLK_FREQ   4000000

/* The SPI peripheral used is SPI2 (the "SPI1" naming is kept from the
 * original nRF reference firmware; ESP32-S3 exposes it as spi2). */
#define KS1092_SPI_NODE  DT_NODELABEL(spi2)

void SPI1_Init(void);
uint8_t SPI1_ReadWriteByte(uint8_t tx_data);
void SPI1_Transfer(const uint8_t *tx_data, uint8_t *rx_data, size_t len);

#endif /* MY_SPI_H */
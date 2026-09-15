//////////////////////////////////////////////////////////////////////////////////
//KS108X/KS109X SPI test
//Date:2021/11/27
//Version:V2.0 (ESP-IDF移植版)
//Copyright(C) Kingsense Electronics
//www.ks-chip.com
//All rights reserved
//////////////////////////////////////////////////////////////////////////////////

#include "myspi.h"

#include "esp_log.h"

static const char *TAG = "MYSPI";

spi_device_handle_t spi1_handle;

void SPI1_Init(void)
{
    spi_bus_config_t buscfg = {
        .mosi_io_num   = SPI1_MOSI_PIN,
        .miso_io_num   = SPI1_MISO_PIN,
        .sclk_io_num   = SPI1_SCK_PIN,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
    };

    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = SPI1_CLK_FREQ,
        .mode           = 1,            // KS108X/KS109X reference boards commonly use SPI mode 1
        .spics_io_num   = -1,           // CS由应用层手动控制
        .queue_size     = 1,
    };

    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_DISABLED));
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &devcfg, &spi1_handle));
    ESP_LOGI(TAG, "SPI1 initialized");
}

uint8_t SPI1_ReadWriteByte(uint8_t TxData)
{
    spi_transaction_t t = {
        .flags     = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA,
        .length    = 8,
        .tx_data   = {TxData},
    };
    ESP_ERROR_CHECK(spi_device_transmit(spi1_handle, &t));
    return t.rx_data[0];
}

void SPI1_Transfer(const uint8_t *tx_data, uint8_t *rx_data, size_t len)
{
    spi_transaction_t t = {
        .length = len * 8,
        .tx_buffer = tx_data,
        .rx_buffer = rx_data,
    };
    ESP_ERROR_CHECK(spi_device_transmit(spi1_handle, &t));
}

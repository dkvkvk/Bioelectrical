idf_component_register(SRCS "protocol_crc.c" "lvbo.c" "heart_rate.c" "ksfilter.c" "iir_filter.c" "ble.c" "uart.c" "myspi.c" "KS1092.c" "main.c"
                    INCLUDE_DIRS "."
                    REQUIRES driver esp_driver_uart esp_driver_spi esp_driver_gpio esp_adc esp_timer bt nvs_flash)

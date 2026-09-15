#ifndef UART_TRANSPORT_H
#define UART_TRANSPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void uart_transport_init(void);
bool uart_is_connected(void);
void uart_send_sample_frame(uint16_t ch1, uint16_t ch2, uint8_t heart_rate);
void uart_send_debug_bytes(const uint8_t *data, size_t len);

#endif /* UART_TRANSPORT_H */
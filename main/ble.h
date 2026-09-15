#ifndef BLE_H
#define BLE_H

#include <stdint.h>
#include <stdbool.h>

void ble_init(void);
bool ble_send_frame(uint8_t battery,
                    const uint16_t ch1[4], const uint16_t ch2[4],
                    uint8_t lead_off, uint8_t heart_rate);
bool ble_is_connected(void);
void ble_stop_advertising(void);
void ble_advertise_restart(void);

#endif // BLE_H

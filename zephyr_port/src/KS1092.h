#ifndef KS1092_H
#define KS1092_H

#include <stdint.h>
#include <zephyr/drivers/gpio.h>

#include "myspi.h"

/*
 * KS1092 chip-select and reset pins come from the devicetree aliases
 * ks1092-cs / ks1092-reset defined in app.overlay.
 *
 * Physical mapping (matches the ESP-IDF project):
 *   CS    = GPIO10
 *   RESET = GPIO14
 */
#define KS1092_CS_NODE     DT_ALIAS(ks1092_cs)
#define KS1092_RESET_NODE  DT_ALIAS(ks1092_reset)

#define ks1092_REG_ADDR_CH1SET  0x00
#define ks1092_REG_ADDR_CH2SET  0x01

void KS1092_Init(void);
void KS1092_CS_Enable(void);
void KS1092_CS_Disable(void);
void KS1092_Write_Reg(uint8_t reg_address, uint8_t data_to_write);
void KS1092_Write_Reg_Pair(uint8_t reg1, uint8_t value1, uint8_t reg2, uint8_t value2);
uint8_t KS1092_Read_Reg(uint8_t reg_address);

#endif /* KS1092_H */
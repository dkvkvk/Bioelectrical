#ifndef KS1092_H
#define KS1092_H

#include <stdint.h>

#include "driver/gpio.h"

#include "myspi.h"

// ESP32-S3 FSPI chip-select pin for KS1092.
#define KS1092_CS_PIN      GPIO_NUM_10

// KS1092 reset pin. Pulse low during init, then keep high for normal operation.
#define KS1092_RESET_PIN   GPIO_NUM_14

#define ks1092_REG_ADDR_CH1SET  0x00
#define ks1092_REG_ADDR_CH2SET  0x01

void KS1092_Init(void);
void KS1092_CS_Enable(void);
void KS1092_CS_Disable(void);
void KS1092_Write_Reg(uint8_t reg_address, uint8_t data_to_write);
void KS1092_Write_Reg_Pair(uint8_t reg1, uint8_t value1, uint8_t reg2, uint8_t value2);
uint8_t KS1092_Read_Reg(uint8_t reg_address);

#endif // KS1092_H

#ifndef KS1082_H
#define KS1082_H

#include <Arduino.h>
#include "myspi.h"

// 定义KS1082片选引脚 - 根据实际连接修改
#define KS1082_CS_PIN 10

// KS1082寄存器地址定义
#define ks1082_REG_ADDR_CH1SET 0x00  // 通道1设置寄存器
#define ks1082_REG_ADDR_CH2SET 0x01  // 通道2设置寄存器
// 可以根据需要添加更多寄存器地址

// 函数声明
void KS1082_Init(void);
void KS1082_CS_Enable(void);
void KS1082_CS_Disable(void);
void KS1082_Write_Reg(uint8_t RegAddress, uint8_t DataToWrite);
uint8_t KS1082_Read_Reg(uint8_t RegAddress);

#endif // KS1082_H
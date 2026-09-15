////////////////////////////////////////////////////////////////////////////////// 
//KS108X/KS109X SPI test  
//Date:2021/11/27
//Version:V1.0 (Arduino ESP32-S3移植版)
//Copyright(C) Kingsense Electronics
//www.ks-chip.com
//All rights reserved									  
//////////////////////////////////////////////////////////////////////////////////

#include "KS1082.h"

void KS1082_Init(void)  // 初始化KS1082及SPI接口
{
  // 配置片选CS引脚
  pinMode(KS1082_CS_PIN, OUTPUT);
  digitalWrite(KS1082_CS_PIN, HIGH); // 初始状态为高电平（片选禁用）
  
  SPI1_Init(); // 初始化SPI
  KS1082_CS_Disable();  // 初始失能片选
}

void KS1082_CS_Enable(void)  // 使能片选（低电平）
{
  digitalWrite(KS1082_CS_PIN, LOW);
}

void KS1082_CS_Disable(void)  // 失能片选（高电平）
{
  digitalWrite(KS1082_CS_PIN, HIGH);
}

// 写寄存器：格式为 0010+地址 → 寄存器数量(1) → 数据
void KS1082_Write_Reg(uint8_t RegAddress, uint8_t DataToWrite)//写寄存器
{
  KS1082_CS_Enable(); // 使能片选
  
  SPI1_ReadWriteByte(0x20 | RegAddress);  // 写指令+地址
  SPI1_ReadWriteByte(0x00);               // 操作数量=1
  SPI1_ReadWriteByte(DataToWrite);        // 写入数据
  
  KS1082_CS_Disable();
}

// 读寄存器：格式为 0001+地址 → 寄存器数量(1) → 读数据
uint8_t KS1082_Read_Reg(uint8_t RegAddress)
{
  uint8_t readData;
  
  KS1082_CS_Enable();
  
  SPI1_ReadWriteByte(0x10 | RegAddress);  // 读指令+地址
  SPI1_ReadWriteByte(0x00);               // 操作数量=1
  readData = SPI1_ReadWriteByte(0xDD);    // 读取数据（0xDD为占位符）
  
  KS1082_CS_Disable();
  return readData;
}
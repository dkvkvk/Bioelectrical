////////////////////////////////////////////////////////////////////////////////// 
//KS108X/KS109X SPI test  
//Date:2021/11/27
//Version:V1.0 (Arduino ESP32-S3移植版)
//Copyright(C) Kingsense Electronics
//www.ks-chip.com
//All rights reserved									  
//////////////////////////////////////////////////////////////////////////////////

#include "myspi.h"

// 创建SPI对象（使用SPI2_HOST，对应ESP32-S3的FSPI）
SPIClass SPI1(FSPI);

void SPI1_Init(void)  // 初始化SPI主机模式
{
  // 初始化SPI引脚
  pinMode(SPI1_SCK_PIN, OUTPUT);
  pinMode(SPI1_MOSI_PIN, OUTPUT);
  pinMode(SPI1_MISO_PIN, INPUT);
  pinMode(SPI1_CS_PIN, OUTPUT);
  digitalWrite(SPI1_CS_PIN, HIGH); // 初始状态为高电平（片选禁用）
  
  // 初始化SPI通信，时钟频率设置为5.25MHz
  SPI1.begin(SPI1_SCK_PIN, SPI1_MISO_PIN, SPI1_MOSI_PIN, SPI1_CS_PIN);
}

// SPI读写一个字节
uint8_t SPI1_ReadWriteByte(uint8_t TxData)
{
  uint8_t rx_data;
  
  // 开始SPI事务，使用Mode 1（CPOL=0, CPHA=1），5.25MHz时钟
  SPI1.beginTransaction(SPISettings(5250000, MSBFIRST, SPI_MODE1));
  
  // 发送和接收数据
  rx_data = SPI1.transfer(TxData);
  
  // 结束SPI事务
  SPI1.endTransaction();
  
  return rx_data;
}
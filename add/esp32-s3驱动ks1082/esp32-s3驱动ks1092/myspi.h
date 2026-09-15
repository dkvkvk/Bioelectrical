#ifndef MY_SPI_H
#define MY_SPI_H

#include <Arduino.h>
#include <SPI.h>

// 定义SPI引脚 - 根据实际连接修改
#define SPI1_MOSI_PIN 13
#define SPI1_MISO_PIN 11
#define SPI1_SCK_PIN 12
#define SPI1_CS_PIN 10

// 声明SPI对象为外部变量
extern SPIClass SPI1;

// 函数声明
void SPI1_Init(void);
uint8_t SPI1_ReadWriteByte(uint8_t TxData);

#endif // MY_SPI_H
#ifndef __ks1082_H
#define __ks1082_H
#include <stdint.h>


/*****************************************************************************
**
*****************************************************************************/
//SPI引脚定义
#define  SPI_SS_PIN     15
#define  SPI_SCK_PIN    18
#define  SPI_MISO_PIN   17
#define  SPI_MOSI_PIN   11


#define    SPI_CS_LOW    nrf_gpio_pin_clear(SPI_SS_PIN)   //片选输出低电平：使能芯片
#define    SPI_CS_HIGH   nrf_gpio_pin_set(SPI_SS_PIN)     //片选输出高电平：取消片选


#define ks1082_REG_ADDR_CH1SET	  0x00	//  通道1寄存器的地址
#define ks1082_REG_ADDR_CH2SET	  0x01	//  通道2寄存器的地址



void Ks1802_Init(void);
void KS1082_Write_Reg(uint8_t RegAddress,uint8_t DataToWrite);
uint8_t KS1082_Read_Reg(uint8_t RegAddress);//往KS1082寄存器里读数据，即设置KS1082的寄存器，格式为：先发送0001+寄存器的地址，再发送要读的寄存器的个数，最后通过发送一个字节读回寄存器的数据



#endif

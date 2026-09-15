#include <stdbool.h>
#include <stdint.h>
#include "nrf.h"
#include "nrf_gpio.h"
#include "boards.h"
#include "nrf_delay.h"

#include "nrf_drv_spi.h"
#include "ks1082.h"

//SPI驱动程序实例ID,ID和外设编号对应，0:SPI0  1:SPI1 2:SPI2
#define SPI_INSTANCE    1 
//定义名称为spi的SPI驱动程序实例
//static const nrf_drv_spi_t spi = NRF_DRV_SPI_INSTANCE(SPI_INSTANCE);  

static const nrf_drv_spi_t spi = NRF_DRV_SPI_INSTANCE(SPI_INSTANCE);
//SPI传输完成标志
static volatile bool spi_xfer_done;  
//SPI发送缓存数组，使用EasyDMA时一定要定义为static类型
static uint8_t    spi_tx_buf[6];  
//SPI接收缓存数组，使用EasyDMA时一定要定义为static类型
static uint8_t    spi_rx_buf[6];  

//static uint8_t    spi_rx_data;  


/*****************************************************************************
** 描  述：写入一个字节
** 参  数：Dat：待写入的数据
** 返回值：无
******************************************************************************/
uint8_t Spi_WriteOneByte(uint8_t Dat)
{   
	  spi_tx_buf[0] = Dat;
	  spi_xfer_done = false;
	  //SPI_CS_LOW;
	  APP_ERROR_CHECK(nrf_drv_spi_transfer(&spi, spi_tx_buf, 1, spi_rx_buf, 0));
    while(!spi_xfer_done);
	  //SPI_CS_HIGH;
	  return spi_rx_buf[0];
}

void KS1082_Write_Reg(uint8_t RegAddress,uint8_t DataToWrite)//往KS1082寄存器里写数据，即设置KS1082的寄存器，格式为：先发送0010+寄存器的地址，再发送要写的寄存器的个数，最后发送要写到寄存器的数据
{
	  
//	  SPI_CS_LOW;
//	  Spi_WriteOneByte(0x20|RegAddress);  //发送0020+寄存器的地址(芯片手册上的写寄存器的指令格式)
//	  Spi_WriteOneByte(0);  //发送待操作的寄存器数量是1(芯片手册上的指令格式)
//	  Spi_WriteOneByte(DataToWrite); //发送要写到寄存器的数据
//	  SPI_CS_HIGH;
	
	 	  spi_tx_buf[0] = 0x20|RegAddress;
			spi_tx_buf[1] = 0x00;
	    spi_tx_buf[2] = DataToWrite;
			//传输完成标志设置为false
			//spi_xfer_done = false;
			SPI_CS_LOW;
	    //nrf_drv_spi_transfer(&spi, spi_tx_buf, 3, spi_rx_buf, 3);
			APP_ERROR_CHECK(nrf_drv_spi_transfer(&spi, spi_tx_buf, 3, spi_rx_buf, 3));
			//while(!spi_xfer_done);
			SPI_CS_HIGH;

}

uint8_t KS1082_Read_Reg(uint8_t RegAddress)//往KS1082寄存器里读数据，即设置KS1082的寄存器，格式为：先发送0001+寄存器的地址，再发送要读的寄存器的个数，最后通过发送一个字节读回寄存器的数据
{
//    uint8_t readData;//读取的数据 
//	  
//	  SPI_CS_LOW;  //SPI通信开始时CS引脚要置低，使能片选
//	
//	  Spi_WriteOneByte(0x10|RegAddress);  //发送0010+寄存器的地址(芯片手册上的读寄存器的指令格式)
//	  Spi_WriteOneByte(0x00);  //发送待操作的寄存器数量是1(芯片手册上的指令格式)
//	  readData = Spi_WriteOneByte(0xDD); //通过发送一个字节(如0xDD)来读回寄存器的数据
//	  //readData = Spi_WriteOneByte(0xDD); //通过发送一个字节(如0xDD)来读回寄存器的数据
//	  
//	  SPI_CS_HIGH;  //SPI通信结束时CS引脚要拉高，失能片选
//	
//	  return readData;
	
	    spi_tx_buf[0] = 0x10|RegAddress;
			spi_tx_buf[1] = 0x00;
	    spi_tx_buf[2] = 0xff;
			//传输完成标志设置为false
			//spi_xfer_done = false;
			SPI_CS_LOW;
	    nrf_drv_spi_transfer(&spi, spi_tx_buf, 3, spi_rx_buf, 3);
			//APP_ERROR_CHECK(nrf_drv_spi_transfer(&spi, spi_tx_buf, 3, spi_rx_buf, 3));
			//while(!spi_xfer_done);
			SPI_CS_HIGH;
			
			return spi_rx_buf[2];
}






//
//SPI事件处理函数
//void spi_event_handler(nrf_drv_spi_evt_t const * p_event,
//                       void *                    p_context)
//{
//  //设置SPI传输完成  
//	spi_xfer_done = true;
//}

/*****************************************************************************
** 描  述：配置用于驱动W25Q128的管脚
** 入  参：无
** 返回值：无
******************************************************************************/
void Ks1802_Init(void)
{
    //配置用于SPI片选的引脚为输出
	  nrf_gpio_cfg_output(SPI_SS_PIN);
	  //拉高CS
	  SPI_CS_HIGH;
	  //使用默认配置参数初始化SPI配置结构体
	  nrf_drv_spi_config_t spi_config = NRF_DRV_SPI_DEFAULT_CONFIG;
	  //重写SPI信号连接的引脚配置
    spi_config.ss_pin   = NRF_DRV_SPI_PIN_NOT_USED;
    spi_config.miso_pin = SPI_MISO_PIN;
    spi_config.mosi_pin = SPI_MOSI_PIN;
    spi_config.sck_pin  = SPI_SCK_PIN;
	  //初始化SPI
//    APP_ERROR_CHECK(nrf_drv_spi_init(&spi, &spi_config, spi_event_handler, NULL));
	  APP_ERROR_CHECK(nrf_drv_spi_init(&spi, &spi_config, NULL, NULL));
}
/********************************************END FILE*******************************************/



                                                                                                

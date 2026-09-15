/****************************************Copyright (c)************************************************
**                                      [艾克姆科技]
**                                        IIKMSIK 
**                            官方店铺：https://acmemcu.taobao.com
**                            官方论坛：http://www.e930bbs.com                                 
**--------------File Info-----------------------------------------------------------------------------
** File          name:my_ble_uarts.c
** Last modified Date:          
** Last       Version:		   
** Descriptions      :串口透传服务文件			
**---------------------------------------------------------------------------------------------------*/
#include "sdk_common.h"
//这里设置了串口透传服务程序模块的“编译开关”，所以要在sdk_config.h中启用BLE_MY_UARTS
#if NRF_MODULE_ENABLED(BLE_MY_UARTS)
#include "my_ble_uarts.h"

#include <stdlib.h>
#include <string.h>
#include "app_error.h"
#include "ble_gatts.h"
#include "ble_srv_common.h"

#define BLE_UARTS_MAX_RX_CHAR_LEN        BLE_UARTS_MAX_DATA_LEN //RX特征最大长度（字节数）
#define BLE_UARTS_MAX_TX_CHAR_LEN        BLE_UARTS_MAX_DATA_LEN //TX特征最大长度（字节数）


//SoftDevice提交的"write"事件处理函数
static void on_write(ble_uarts_t * p_uarts, ble_evt_t const * p_ble_evt)
{
    //定义一个串口透传事件结构体变量，用于执行回调时传递参数
	  ble_uarts_evt_t                 evt;
    //定义write事件结构体指针并指向GATT事件中的wirite
    ble_gatts_evt_write_t const * p_evt_write = &p_ble_evt->evt.gatts_evt.params.write;

    //清零evt
    memset(&evt, 0, sizeof(ble_uarts_evt_t));
	  //指向串口透传服务实例
    evt.p_uarts       = p_uarts;
	  //设置连接句柄
    evt.conn_handle = p_ble_evt->evt.gatts_evt.conn_handle;

    //写RX特征值
    if ((p_evt_write->handle == p_uarts->rx_handles.value_handle) &&
             (p_uarts->data_handler != NULL))
    {
        //设置事件类型
			  evt.type                  = BLE_UARTS_EVT_RX_DATA;
			  //设置数据长度
        evt.params.rx_data.p_data = p_evt_write->data;
			  //设置数据长度
        evt.params.rx_data.length = p_evt_write->len;
        //执行回调
        p_uarts->data_handler(&evt);
    }
    else
    {
        //该事件和串口透传服务无关，忽略
    }
}
//SoftDevice提交的"BLE_GATTS_EVT_HVN_TX_COMPLETE"事件处理函数
static void on_hvx_tx_complete(ble_uarts_t * p_uarts, ble_evt_t const * p_ble_evt)
{
    //定义一个串口透传事件结构体变量evt，用于执行回调时传递参数
	  ble_uarts_evt_t              evt;
    //清零evt
    memset(&evt, 0, sizeof(ble_uarts_evt_t));
	  //设置事件类型
    evt.type        = BLE_UARTS_EVT_TX_RDY;
	  //指向串口透传服务实例
    evt.p_uarts     = p_uarts;
	  //设置连接句柄
    evt.conn_handle = p_ble_evt->evt.gatts_evt.conn_handle;

    //执行回调
    p_uarts->data_handler(&evt);
}
//串口透传服务BLE事件监视者的事件回调函数
void ble_uarts_on_ble_evt(ble_evt_t const * p_ble_evt, void * p_context)
{
    //检查参数是否有效
	  if ((p_context == NULL) || (p_ble_evt == NULL))
    {
        return;
    }
    //定义一个串口透传结构体指针并指向串口透传结构体
    ble_uarts_t * p_uarts = (ble_uarts_t *)p_context;
    //判断事件类型
    switch (p_ble_evt->header.evt_id)
    {
        case BLE_GATTS_EVT_WRITE://写事件
					  //处理写事件
            on_write(p_uarts, p_ble_evt);
            break;

        case BLE_GATTS_EVT_HVN_TX_COMPLETE://TX就绪事件
					  //处理TX就绪事件
            on_hvx_tx_complete(p_uarts, p_ble_evt);
            break;

        default:
            break;
    }
}
//初始化串口透传服务
uint32_t ble_uarts_init(ble_uarts_t * p_uarts, ble_uarts_init_t const * p_uarts_init)
{
    ret_code_t            err_code;
	  //定义16位UUID结构体变量
    ble_uuid_t            ble_uuid;
	  //定义128位UUID结构体变量，并初始化为串口透传服务UUID基数
    ble_uuid128_t         nus_base_uuid = UARTS_BASE_UUID;
	  //定义特征参数结构体变量
    ble_add_char_params_t add_char_params;
    //检查指针是否为NULL
    VERIFY_PARAM_NOT_NULL(p_uarts);
    VERIFY_PARAM_NOT_NULL(p_uarts_init);

	  //拷贝串口透传服务初始化结构体中的事件句柄
    p_uarts->data_handler = p_uarts_init->data_handler;

    //将自定义UUID基数添加到SoftDevice
    err_code = sd_ble_uuid_vs_add(&nus_base_uuid, &p_uarts->uuid_type);
    VERIFY_SUCCESS(err_code);
    //UUID类型和数值赋值给ble_uuid变量
    ble_uuid.type = p_uarts->uuid_type;
    ble_uuid.uuid = BLE_UUID_UARTS_SERVICE;

    //添加串口透传服务
    err_code = sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY,
                                        &ble_uuid,
                                        &p_uarts->service_handle);
    VERIFY_SUCCESS(err_code);
    /*---------------------以下代码添加RX特征--------------------*/
    //添加RX特征
		//配置参数之前先清零add_char_params
    memset(&add_char_params, 0, sizeof(add_char_params));
		//RX特征的UUID
    add_char_params.uuid                     = BLE_UUID_UARTS_RX_CHARACTERISTIC;
		//RX特征的UUID类型
    add_char_params.uuid_type                = p_uarts->uuid_type;
		//设置RX特征值的最大长度
    add_char_params.max_len                  = BLE_UARTS_MAX_RX_CHAR_LEN;
		//设置RX特征值的初始长度
    add_char_params.init_len                 = sizeof(uint8_t);
		//设置RX的特征值长度为可变长度
    add_char_params.is_var_len               = true;
		//设置RX特征的性质支持写
    add_char_params.char_props.write         = 1;
		//设置RX特征的性质支持无响应写
    add_char_params.char_props.write_wo_resp = 1;
    //设置读/写RX特征值的安全需求：无安全性
    add_char_params.read_access  = SEC_OPEN;
    add_char_params.write_access = SEC_OPEN;
    //为串口透传服务添加RX特征
    err_code = characteristic_add(p_uarts->service_handle, &add_char_params, &p_uarts->rx_handles);
		//检查返回的错误代码
    if (err_code != NRF_SUCCESS)
    {
        return err_code;
    }
		/*---------------------添加RX特征-END------------------------*/
		
    /*---------------------以下代码添加TX特征--------------------*/
    //添加TX特征
		//配置参数之前先清零add_char_params
    memset(&add_char_params, 0, sizeof(add_char_params));
		//TX特征的UUID
    add_char_params.uuid              = BLE_UUID_UARTS_TX_CHARACTERISTIC;
		//TX特征的UUID类型
    add_char_params.uuid_type         = p_uarts->uuid_type;
		//设置TX特征值的最大长度
    add_char_params.max_len           = BLE_UARTS_MAX_TX_CHAR_LEN;
		//设置TX特征值的初始长度
    add_char_params.init_len          = sizeof(uint8_t);
		//设置TX的特征值长度为可变长度
    add_char_params.is_var_len        = true;
		//设置TX特征的性质：支持通知
    add_char_params.char_props.notify = 1;
    //设置读/写RX特征值的安全需求：无安全性
    add_char_params.read_access       = SEC_OPEN;
    add_char_params.write_access      = SEC_OPEN;
    add_char_params.cccd_write_access = SEC_OPEN;
    //为串口透传服务添加TX特征
    return characteristic_add(p_uarts->service_handle, &add_char_params, &p_uarts->tx_handles);
		/*---------------------添加TX特征-END------------------------*/
}
uint32_t ble_uarts_data_send(ble_uarts_t * p_uarts,
                           uint8_t   * p_data,
                           uint16_t  * p_length,
                           uint16_t    conn_handle)
{
		ret_code_t err_code;
    ble_gatts_hvx_params_t     hvx_params;
    //验证p_uarts没有指向NULL
    VERIFY_PARAM_NOT_NULL(p_uarts);

    //如果连接句柄无效，表示没有和主机建立连接，返回NRF_ERROR_NOT_FOUND
	  if (conn_handle == BLE_CONN_HANDLE_INVALID)
    {
        return NRF_ERROR_NOT_FOUND;
    }

    if (*p_length > BLE_UARTS_MAX_DATA_LEN)
    {
        return NRF_ERROR_INVALID_PARAM;
    }
    //设置之前先清零hvx_params
    memset(&hvx_params, 0, sizeof(hvx_params));
    //TX特征值句柄
    hvx_params.handle = p_uarts->tx_handles.value_handle;
		//发送的数据
    hvx_params.p_data = p_data;
		//发送的数据长度
    hvx_params.p_len  = p_length;
		//类型为通知
    hvx_params.type   = BLE_GATT_HVX_NOTIFICATION;
    //发送TX特征值通知
		
		err_code = sd_ble_gatts_hvx(conn_handle, &hvx_params);
		
		if (err_code == BLE_ERROR_GATTS_SYS_ATTR_MISSING) {
	    err_code = sd_ble_gatts_sys_attr_set(conn_handle, NULL, 0, 0);
	    APP_ERROR_CHECK(err_code);
	    // Try again
    	err_code = sd_ble_gatts_hvx(conn_handle, &hvx_params);
    }
		
    return err_code;
}

#endif // NRF_MODULE_ENABLED(BLE_DIS)

// 引用的C库头文件
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "nrf_delay.h"
// Log需要引用的头文件
#include "nrf_log.h"
#include "nrf_log_ctrl.h"
#include "nrf_log_default_backends.h"


#include "ksfilter.h"
#include "iir_filter.h"
#include "heart_rate.h"

// AD转换要引用的头文件
#include "nrf_drv_saadc.h"

// APP定时器需要引用的头文件
#include "app_timer.h"
#include "bsp_btn_ble.h"
// 电源管理需要引用的头文件
#include "nrf_pwr_mgmt.h"
// SoftDevice handler configuration需要引用的头文件
#include "nrf_sdh.h"
#include "nrf_sdh_soc.h"
#include "nrf_sdh_ble.h"
// 排序写入模块需要引用的头文件
#include "nrf_ble_qwr.h"
// GATT需要引用的头文件
#include "nrf_ble_gatt.h"
// 连接参数协商需要引用的头文件
#include "ble_conn_params.h"
// 广播需要引用的头文件
#include "ble_advdata.h"
#include "ble_advertising.h"
// 串口透传需要引用的头文件
#include "my_ble_uarts.h"

// CRC-8校验
#include "CRC.h"

#if defined(UART_PRESENT)
#include "nrf_uart.h"
#endif
#if defined(UARTE_PRESENT)
#include "nrf_uarte.h"
#endif
#include "app_uart.h"
#include "ks1082.h"

#define LDFIO      23

#define DEVICE_NAME "BLE_EEG"                                // 设备名称字符串
#define UARTS_SERVICE_UUID_TYPE BLE_UUID_TYPE_VENDOR_BEGIN   // 串口透传服务UUID类型：厂商自定义UUID
#define MIN_CONN_INTERVAL MSEC_TO_UNITS(8, UNIT_1_25_MS)     // 最小连接间隔 (8毫秒) 连接间隔决定了数据的吞吐量，连接间隔越小，则数据吞吐量越高，连接间隔越大，则数据吞吐量越高
#define MAX_CONN_INTERVAL MSEC_TO_UNITS(16, UNIT_1_25_MS)    // 最大连接间隔 (16毫秒)
#define SLAVE_LATENCY 0                                      // 从机延迟
#define CONN_SUP_TIMEOUT MSEC_TO_UNITS(4000, UNIT_10_MS)     // 监督超时(4 秒)
#define FIRST_CONN_PARAMS_UPDATE_DELAY APP_TIMER_TICKS(5000) // 定义首次调用sd_ble_gap_conn_param_update()函数更新连接参数延迟时间（5秒）
#define NEXT_CONN_PARAMS_UPDATE_DELAY APP_TIMER_TICKS(30000) // 定义每次调用sd_ble_gap_conn_param_update()函数更新连接参数的间隔时间（30秒）
#define MAX_CONN_PARAMS_UPDATE_COUNT 6                       // 定义放弃连接参数协商前尝试连接参数协商的最大次数（3次）

#define APP_ADV_INTERVAL 320 // 广播间隔 (200ms)，单位0.625 ms
#define APP_ADV_DURATION 0   // 广播持续时间，单位：10ms。设置为0表示不超时

#define APP_BLE_OBSERVER_PRIO 3 // 应用程序BLE事件监视者优先级，应用程序不能修改该数值
#define APP_BLE_CONN_CFG_TAG 1  // SoftDevice BLE配置标志

#define SAMPLES_IN_BUFFER 3

// 使用12位分辨率
#define ADC_RESOLUTION 16383
// VDD电压
#define VDD_VOLTAGE 0.6f
#define HARDFAULT_HANDLER_ENABLED 1

static nrf_saadc_value_t m_buffer_pool[2][SAMPLES_IN_BUFFER];

APP_TIMER_DEF(m_adc_sampling_timer_id);          /* ADC采样应用定时器 */
#define ADC_SAMPLING_INTERVAL APP_TIMER_TICKS(2) /* ADC采样应用定时器定时时间：2ms */

#define UART_TX_BUF_SIZE 256 // 串口发送缓存大小（字节数）
#define UART_RX_BUF_SIZE 256 // 串口接收缓存大小（字节数）

// 用于stack dump的错误代码，可以用于栈回退时确定堆栈位置
#define DEAD_BEEF 0xDEADBEEF

BLE_UARTS_DEF(m_uarts);             // 定义名称为m_uarts的串口透传服务实例
NRF_BLE_GATT_DEF(m_gatt);           // 定义名称为m_gatt的GATT模块实例
NRF_BLE_QWR_DEF(m_qwr);             // 定义一个名称为m_qwr的排队写入实例
BLE_ADVERTISING_DEF(m_advertising); // 定义名称为m_advertising的广播模块实例

// 该变量用于保存连接句柄，初始值设置为无连接
static uint16_t m_conn_handle = BLE_CONN_HANDLE_INVALID;
static uint16_t m_ble_uarts_max_data_len = BLE_GATT_ATT_MTU_DEFAULT - 3; /**< Maximum length of data (in bytes) that can be transmitted to the peer by the Nordic UART service module. */

// uint16_t send_data_count=0;    //设置蓝牙一次发送的数据个数为8个
double R_max[100];
double bigest = 0.0;          // 存储极大值数组中数值R_max中最大的值
uint16_t bigest_position = 0; // 存储极大值数组中数值R_max中最大值的位置
double minest = 10.0;         // 存储极大值数组中数值R_max中最小的值
uint16_t rec_cnt = 0;         // 用于存储接收到的第几个数据
double pre_data, cur_data;    // 存储一阶差分的上一个结果和当前结果
double pre_second_order_data; // 存储二阶差分的上一个结果
double cur_second_order_data; // 存储二阶差分的当前结果
uint16_t max_cnt = 0;         // 存储极大值的个数
double group_space;           // 存储直方图的组距
int group_max_cnt;            // 存放每一幅值段内极大值的个数
int w;


uint8_t R_Wave_cnt = 0;
uint8_t Heart_rate;
uint16_t cur_R_Position; // 存储当前R波的位置
uint16_t pre_R_Position; // 存储上一个R波的位置
int flag = 0;

uint8_t send_cnt = 0;
uint8_t send_flag_cnt = 0;
// uint8_t adc_result[32];
// uint16_t length = 32;


uint8_t adc_result[23];
uint16_t lead_off_length = 5;
uint16_t length = 23;

double AD_value, Filter_Data, AD_value1, Filter_Data1;
uint16_t Send_Data, Send_Data1;
uint8_t receive_bluetooth_data_flag = 0;
uint8_t Channel1_Digital_Filter_Open_flag = 1; // 默认通道1开启滤波
uint8_t Channel2_Digital_Filter_Open_flag = 1; // 默认通道2开启滤波

double battery_value = 0.0;
uint16_t battery_int = 0;
uint8_t battery = 50;
uint8_t current_flag = 1;
uint8_t battery_flag = 1;

uint8_t is_lead_off = 0;
int lead_time = 0;

int num_test = 0;

//心率
int avg_rate_list[5];
int avg_rate=0;
int count_HR=0;



// 定义串口透传服务UUID列表
static ble_uuid_t m_adv_uuids[] =
    {
        {BLE_UUID_UARTS_SERVICE, UARTS_SERVICE_UUID_TYPE}};

// GAP参数初始化，该函数配置需要的GAP参数，包括设备名称，外观特征、首选连接参数
static void gap_params_init(void)
{
    ret_code_t err_code;
    // 定义连接参数结构体变量
    ble_gap_conn_params_t gap_conn_params;
    ble_gap_conn_sec_mode_t sec_mode;
    // 设置GAP的安全模式
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&sec_mode);
    // 设置GAP设备名称
    err_code = sd_ble_gap_device_name_set(&sec_mode,
                                          (const uint8_t *)DEVICE_NAME,
                                          strlen(DEVICE_NAME));
    // 检查函数返回的错误代码
    APP_ERROR_CHECK(err_code);

    // 设置首选连接参数，设置前先清零gap_conn_params
    memset(&gap_conn_params, 0, sizeof(gap_conn_params));

    gap_conn_params.min_conn_interval = MIN_CONN_INTERVAL; // 最小连接间隔
    gap_conn_params.max_conn_interval = MAX_CONN_INTERVAL; // 最小连接间隔
    gap_conn_params.slave_latency = SLAVE_LATENCY;         // 从机延迟
    gap_conn_params.conn_sup_timeout = CONN_SUP_TIMEOUT;   // 监督超时
    // 调用协议栈API sd_ble_gap_ppcp_set配置GAP参数
    err_code = sd_ble_gap_ppcp_set(&gap_conn_params);
    APP_ERROR_CHECK(err_code);
}

// GATT事件处理函数，该函数中处理MTU交换事件
void gatt_evt_handler(nrf_ble_gatt_t *p_gatt, nrf_ble_gatt_evt_t const *p_evt)
{
    // 如果是MTU交换事件
    if ((m_conn_handle == p_evt->conn_handle) && (p_evt->evt_id == NRF_BLE_GATT_EVT_ATT_MTU_UPDATED))
    {
        // 设置串口透传服务的有效数据长度（MTU-opcode-handle）
        m_ble_uarts_max_data_len = p_evt->params.att_mtu_effective - OPCODE_LENGTH - HANDLE_LENGTH;
        NRF_LOG_INFO("Data len is set to 0x%X(%d)", m_ble_uarts_max_data_len, m_ble_uarts_max_data_len);
    }
    NRF_LOG_DEBUG("ATT MTU exchange completed. central 0x%x peripheral 0x%x",
                  p_gatt->att_mtu_desired_central,
                  p_gatt->att_mtu_desired_periph);
}

// 初始化GATT程序模块
static void gatt_init(void)
{
    // 初始化GATT程序模块
    ret_code_t err_code = nrf_ble_gatt_init(&m_gatt, gatt_evt_handler);
    // 检查函数返回的错误代码
    APP_ERROR_CHECK(err_code);
    // 设置ATT MTU的大小,这里设置的值为247
    err_code = nrf_ble_gatt_att_mtu_periph_set(&m_gatt, NRF_SDH_BLE_GATT_MAX_MTU_SIZE);
    APP_ERROR_CHECK(err_code);
}

// 排队写入事件处理函数，用于处理排队写入模块的错误
static void nrf_qwr_error_handler(uint32_t nrf_error)
{
    // 检查错误代码
    APP_ERROR_HANDLER(nrf_error);
}

// 创建的SAADC采样应用定时器回调函数
static void saadc_sampling_timeout_handler(void *p_context)
{
    UNUSED_PARAMETER(p_context);

    // 启动一次ADC采样。
    nrf_drv_saadc_sample();
}

// 串口透传事件回调函数，串口透出服务初始化时注册
static void uarts_data_handler(ble_uarts_evt_t *p_evt)
{
    // 判断事件类型:接收到新数据事件
    if (p_evt->type == BLE_UARTS_EVT_RX_DATA)
    {
        KS1082_Write_Reg(ks1082_REG_ADDR_CH1SET, p_evt->params.rx_data.p_data[0]);
        KS1082_Write_Reg(ks1082_REG_ADDR_CH2SET, p_evt->params.rx_data.p_data[1]);
        Channel1_Digital_Filter_Open_flag = p_evt->params.rx_data.p_data[3];
        Channel2_Digital_Filter_Open_flag = p_evt->params.rx_data.p_data[4];
				
				app_timer_stop(m_adc_sampling_timer_id);
				app_timer_start(m_adc_sampling_timer_id, APP_TIMER_TICKS(p_evt->params.rx_data.p_data[2]), NULL);

		}
}
// 服务初始化，包含初始化排队写入模块和初始化应用程序使用的服务
static void services_init(void)
{
    ret_code_t err_code;
    // 定义串口透传初始化结构体
    ble_uarts_init_t uarts_init;
    // 定义排队写入初始化结构体变量
    nrf_ble_qwr_init_t qwr_init = {0};

    // 排队写入事件处理函数
    qwr_init.error_handler = nrf_qwr_error_handler;
    // 初始化排队写入模块
    err_code = nrf_ble_qwr_init(&m_qwr, &qwr_init);
    // 检查函数返回值
    APP_ERROR_CHECK(err_code);

    /*------------------以下代码初始化串口透传服务-------------*/
    // 清零串口透传服务初始化结构体
    memset(&uarts_init, 0, sizeof(uarts_init));
    // 设置串口透传事件回调函数
    uarts_init.data_handler = uarts_data_handler;
    // 初始化串口透传服务
    err_code = ble_uarts_init(&m_uarts, &uarts_init);
    APP_ERROR_CHECK(err_code);
    /*------------------初始化串口透传服务-END-----------------*/
}

// 连接参数协商模块事件处理函数
static void on_conn_params_evt(ble_conn_params_evt_t *p_evt)
{
    ret_code_t err_code;
    // 判断事件类型，根据事件类型执行动作
    // 连接参数协商失败
    if (p_evt->evt_type == BLE_CONN_PARAMS_EVT_FAILED)
    {
        err_code = sd_ble_gap_disconnect(m_conn_handle, BLE_HCI_CONN_INTERVAL_UNACCEPTABLE);
        APP_ERROR_CHECK(err_code);
    }
    // 连接参数协商成功
    if (p_evt->evt_type == BLE_CONN_PARAMS_EVT_SUCCEEDED)
    {
        // 功能代码;
    }
}

// 连接参数协商模块错误处理事件，参数nrf_error包含了错误代码，通过nrf_error可以分析错误信息
static void conn_params_error_handler(uint32_t nrf_error)
{
    // 检查错误代码
    APP_ERROR_HANDLER(nrf_error);
}

// 连接参数协商模块初始化
static void conn_params_init(void)
{
    ret_code_t err_code;
    // 定义连接参数协商模块初始化结构体
    ble_conn_params_init_t cp_init;
    // 配置之前先清零
    memset(&cp_init, 0, sizeof(cp_init));
    // 设置为NULL，从主机获取连接参数
    cp_init.p_conn_params = NULL;
    // 连接或启动通知到首次发起连接参数更新请求之间的时间设置为5秒
    cp_init.first_conn_params_update_delay = FIRST_CONN_PARAMS_UPDATE_DELAY;
    // 每次调用sd_ble_gap_conn_param_update()函数发起连接参数更新请求的之间的间隔时间设置为：30秒
    cp_init.next_conn_params_update_delay = NEXT_CONN_PARAMS_UPDATE_DELAY;
    // 放弃连接参数协商前尝试连接参数协商的最大次数设置为：3次
    cp_init.max_conn_params_update_count = MAX_CONN_PARAMS_UPDATE_COUNT;
    // 连接参数更新从连接事件开始计时
    cp_init.start_on_notify_cccd_handle = BLE_GATT_HANDLE_INVALID;
    // 连接参数更新失败不断开连接
    cp_init.disconnect_on_fail = false;
    // 注册连接参数更新事件句柄
    cp_init.evt_handler = on_conn_params_evt;
    // 注册连接参数更新错误事件句柄
    cp_init.error_handler = conn_params_error_handler;
    // 调用库函数（以连接参数更新初始化结构体为输入参数）初始化连接参数协商模块
    err_code = ble_conn_params_init(&cp_init);
    APP_ERROR_CHECK(err_code);
}

// 广播事件处理函数
static void on_adv_evt(ble_adv_evt_t ble_adv_evt)
{
    ret_code_t err_code;
    // 判断广播事件类型
    switch (ble_adv_evt)
    {
        // 快速广播启动事件：快速广播启动后会产生该事件
    case BLE_ADV_EVT_FAST:
        NRF_LOG_INFO("Fast advertising.");
        // 设置广播指示灯为正在广播（D1指示灯闪烁）
//        err_code = bsp_indication_set(BSP_INDICATE_ADVERTISING);
//        APP_ERROR_CHECK(err_code);
        break;
    // 广播IDLE事件：广播超时后会产生该事件
    case BLE_ADV_EVT_IDLE:
        // 设置广播指示灯为广播停止（D1指示灯熄灭）
        err_code = bsp_indication_set(BSP_INDICATE_IDLE);
        APP_ERROR_CHECK(err_code);
        break;

    default:
        break;
    }
}
// 广播初始化
static void advertising_init(void)
{
    ret_code_t err_code;
    // 定义广播初始化配置结构体变量
    ble_advertising_init_t init;
    // 配置之前先清零
    memset(&init, 0, sizeof(init));
    // 设备名称类型：全称
    init.advdata.name_type = BLE_ADVDATA_FULL_NAME;
    // 是否包含外观：包含
    init.advdata.include_appearance = false;
    // Flag:一般可发现模式，不支持BR/EDR
    init.advdata.flags = BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE;
    // UUID放到扫描响应里面
    init.srdata.uuids_complete.uuid_cnt = sizeof(m_adv_uuids) / sizeof(m_adv_uuids[0]);
    init.srdata.uuids_complete.p_uuids = m_adv_uuids;

    // 设置广播模式为快速广播
    init.config.ble_adv_fast_enabled = true;
    // 设置广播间隔和广播持续时间
    init.config.ble_adv_fast_interval = APP_ADV_INTERVAL;
    init.config.ble_adv_fast_timeout = APP_ADV_DURATION;
    // 广播事件回调函数
    init.evt_handler = on_adv_evt;
    // 初始化广播
    err_code = ble_advertising_init(&m_advertising, &init);
    APP_ERROR_CHECK(err_code);
    // 设置广播配置标记。APP_BLE_CONN_CFG_TAG是用于跟踪广播配置的标记，这是为未来预留的一个参数，在将来的SoftDevice版本中，
    // 可以使用sd_ble_gap_adv_set_configure()配置新的广播配置
    // 当前SoftDevice版本（S132 V7.2.0版本）支持的最大广播集数量为1，因此APP_BLE_CONN_CFG_TAG只能写1。
    ble_advertising_conn_cfg_tag_set(&m_advertising, APP_BLE_CONN_CFG_TAG);
}

// BLE事件处理函数
static void ble_evt_handler(ble_evt_t const *p_ble_evt, void *p_context)
{
    ret_code_t err_code = NRF_SUCCESS;
    // 判断BLE事件类型，根据事件类型执行相应操作
    switch (p_ble_evt->header.evt_id)
    {
        // 断开连接事件
    case BLE_GAP_EVT_DISCONNECTED:
				err_code = bsp_indication_set(BSP_INDICATE_ADVERTISING_SLOW);
        APP_ERROR_CHECK(err_code);
		
        m_conn_handle = BLE_CONN_HANDLE_INVALID;
        // 打印提示信息
        NRF_LOG_INFO("Disconnected.");
        break;

    // 连接事件
    case BLE_GAP_EVT_CONNECTED:
        NRF_LOG_INFO("Connected.");
        // 设置指示灯状态为连接状态，即指示灯D1常亮
        err_code = bsp_indication_set(BSP_INDICATE_CONNECTED);
        APP_ERROR_CHECK(err_code);
        // 保存连接句柄
        m_conn_handle = p_ble_evt->evt.gap_evt.conn_handle;
        // 将连接句柄分配给排队写入实例，分配后排队写入实例和该连接关联，这样，当有多个连接的时候，通过关联不同的排队写入实例，很方便单独处理各个连接
        err_code = nrf_ble_qwr_conn_handle_assign(&m_qwr, m_conn_handle);
        APP_ERROR_CHECK(err_code);
        break;

    // PHY更新事件
    case BLE_GAP_EVT_PHY_UPDATE_REQUEST:
    {
        NRF_LOG_DEBUG("PHY update request.");
        ble_gap_phys_t const phys =
            {
                .rx_phys = BLE_GAP_PHY_AUTO,
                .tx_phys = BLE_GAP_PHY_AUTO,
            };
        // 响应PHY更新规程
        err_code = sd_ble_gap_phy_update(p_ble_evt->evt.gap_evt.conn_handle, &phys);
        APP_ERROR_CHECK(err_code);
    }
    break;
    // 系统属性访问正在等待中
    case BLE_GATTS_EVT_SYS_ATTR_MISSING:
        // 系统属性没有存储，更新系统属性
        err_code = sd_ble_gatts_sys_attr_set(m_conn_handle, NULL, 0, 0);
        APP_ERROR_CHECK(err_code);
        break;
    // GATT客户端超时事件
    case BLE_GATTC_EVT_TIMEOUT:
        NRF_LOG_DEBUG("GATT Client Timeout.");
        // 断开当前连接
        err_code = sd_ble_gap_disconnect(p_ble_evt->evt.gattc_evt.conn_handle,
                                         BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        APP_ERROR_CHECK(err_code);
        break;

    // GATT服务器超时事件
    case BLE_GATTS_EVT_TIMEOUT:
        NRF_LOG_DEBUG("GATT Server Timeout.");
        // 断开当前连接
        err_code = sd_ble_gap_disconnect(p_ble_evt->evt.gatts_evt.conn_handle,
                                         BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        APP_ERROR_CHECK(err_code);
        break;

    default:
        break;
    }
}

// 初始化BLE协议栈
static void ble_stack_init(void)
{
    ret_code_t err_code;
    // 请求使能SoftDevice，该函数中会根据sdk_config.h文件中低频时钟的设置来配置低频时钟
    err_code = nrf_sdh_enable_request();
    APP_ERROR_CHECK(err_code);

    // 定义保存应用程序RAM起始地址的变量
    uint32_t ram_start = 0;
    // 使用sdk_config.h文件的默认参数配置协议栈，获取应用程序RAM起始地址，保存到变量ram_start
    err_code = nrf_sdh_ble_default_cfg_set(APP_BLE_CONN_CFG_TAG, &ram_start);
    APP_ERROR_CHECK(err_code);

    // 使能BLE协议栈
    err_code = nrf_sdh_ble_enable(&ram_start);
    APP_ERROR_CHECK(err_code);

    // 注册BLE事件回调函数
    NRF_SDH_BLE_OBSERVER(m_ble_observer, APP_BLE_OBSERVER_PRIO, ble_evt_handler, NULL);
}

// 长按1S关机
void system_power_off(void)
{
    // nrf_gpio_cfg_output(16);
    nrf_gpio_pin_clear(16);
}

// 开机
void system_power_on(void)
{
    nrf_gpio_cfg_output(16);
    nrf_gpio_pin_set(16);
}

void bsp_event_handler(bsp_event_t event)
{
    uint32_t err_code;
    switch (event)
    {
    case BSP_EVENT_SLEEP:
        //            sleep_mode_enter();
        bsp_board_leds_on();
        break;

    case BSP_EVENT_DISCONNECT:
        err_code = sd_ble_gap_disconnect(m_conn_handle, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        if (err_code != NRF_ERROR_INVALID_STATE)
        {
            APP_ERROR_CHECK(err_code);
        }
        break;

    case BSP_EVENT_WHITELIST_OFF:
        //            if (m_conn_handle == BLE_CONN_HANDLE_INVALID)
        //            {
        //                err_code = ble_advertising_restart_without_whitelist();
        //                if (err_code != NRF_ERROR_INVALID_STATE)
        //                {
        //                    APP_ERROR_CHECK(err_code);
        //                }
        //            }
        bsp_board_led_invert(2);
        // bsp_board_leds_on();
        break;
    case BSP_EVENT_KEY_1:
        // bsp_board_led_invert(2);
        nrf_gpio_pin_clear(LED_3);
        system_power_off();
        // bsp_board_leds_on();
        break;

    default:
        break;
    }
}

// 初始化电源管理模块
static void power_management_init(void)
{
    ret_code_t err_code;
    // 初始化电源管理
    err_code = nrf_pwr_mgmt_init();
    // 检查函数返回的错误代码
    APP_ERROR_CHECK(err_code);
}

// 初始化指示灯
static void leds_init(void)
{
    ret_code_t err_code;
    // 初始化BSP指示灯
    err_code = bsp_init(BSP_INIT_LEDS | BSP_INIT_BUTTONS, bsp_event_handler);
    APP_ERROR_CHECK(err_code);

    //	     uint32_t err_code = bsp_init(BSP_INIT_LED | BSP_INIT_BUTTONS,BSP_INIT_BUTTONS
    //                                 APP_TIMER_TICKS(100, APP_TIMER_PRESCALER),
    //                                 bsp_event_handler);
    //    APP_ERROR_CHECK(err_code);
}

static void application_timers_start(void)
{
    uint32_t err_code;

    // Start application timers.
    err_code = app_timer_start(m_adc_sampling_timer_id, ADC_SAMPLING_INTERVAL, NULL);
    APP_ERROR_CHECK(err_code);
}

// 初始化APP定时器模块、创建APP定时器
static void timers_init(void)
{
    // 初始化APP定时器模块
    ret_code_t err_code = app_timer_init();
    // 检查返回值
    APP_ERROR_CHECK(err_code);

    // 创建APP定时器：LED定时器，周期定时器，启动后周期运行，用于驱动指示灯闪烁
    err_code = app_timer_create(&m_adc_sampling_timer_id,
                                APP_TIMER_MODE_REPEATED,
                                saadc_sampling_timeout_handler);
    APP_ERROR_CHECK(err_code);
}

static void log_init(void)
{
    // 初始化log程序模块
    ret_code_t err_code = NRF_LOG_INIT(NULL);
    APP_ERROR_CHECK(err_code);
    // 设置log输出终端（根据sdk_config.h中的配置设置输出终端为UART或者RTT）
    NRF_LOG_DEFAULT_BACKENDS_INIT();
}

// 空闲状态处理函数。如果没有挂起的日志操作，则睡眠直到下一个事件发生后唤醒系统
static void idle_state_handle(void)
{
    // 处理挂起的log
    if (NRF_LOG_PROCESS() == false)
    {
        // 运行电源管理，该函数需要放到主循环里面执行
        nrf_pwr_mgmt_run();
    }
}
// 启动广播，该函数所用的模式必须和广播初始化中设置的广播模式一样
static void advertising_start(void)
{
    // 使用广播初始化中设置的广播模式启动广播
    ret_code_t err_code = ble_advertising_start(&m_advertising, BLE_ADV_MODE_FAST);
    // 检查函数返回的错误代码
    APP_ERROR_CHECK(err_code);
}

// 串口事件回调函数，串口初始化时注册，该函数中判断事件类型并进行处理
// 当接收的数据长度达到设定的最大值或者接收到换行符后，则认为一包数据接收完成，之后将接收的数据发送给主机
void uart_event_handle(app_uart_evt_t *p_event)
{
    static uint8_t data_array[BLE_UARTS_MAX_DATA_LEN];
    static uint8_t index = 0;
    uint32_t err_code;
    // 判断事件类型
    switch (p_event->evt_type)
    {
    case APP_UART_DATA_READY: // 串口接收事件
        UNUSED_VARIABLE(app_uart_get(&data_array[index]));
        index++;
        // 接收串口数据，当接收的数据长度达到m_ble_uarts_max_data_len或者接收到换行符后认为一包数据接收完成
        if ((data_array[index - 1] == '\n') ||
            (data_array[index - 1] == '\r') ||
            (index >= m_ble_uarts_max_data_len))
        {
            if (index > 1)
            {
                NRF_LOG_DEBUG("Ready to send data over BLE NUS");
                NRF_LOG_HEXDUMP_DEBUG(data_array, index);
                // 串口接收的数据使用notify发送给BLE主机
                do
                {
                    uint16_t length = (uint16_t)index;
                    err_code = ble_uarts_data_send(&m_uarts, data_array, &length, m_conn_handle);
                    if ((err_code != NRF_ERROR_INVALID_STATE) &&
                        (err_code != NRF_ERROR_RESOURCES) &&
                        (err_code != NRF_ERROR_NOT_FOUND))
                    {
                        APP_ERROR_CHECK(err_code);
                    }
                } while (err_code == NRF_ERROR_RESOURCES);
            }

            index = 0;
        }
        break;
    // 通讯错误事件，进入错误处理
    case APP_UART_COMMUNICATION_ERROR:
				NVIC_SystemReset();
        APP_ERROR_HANDLER(p_event->data.error_communication);
        break;
    // FIFO错误事件，进入错误处理
    case APP_UART_FIFO_ERROR:
				NVIC_SystemReset();
        APP_ERROR_HANDLER(p_event->data.error_code);
        break;

    default:
        break;
    }
}

// 十六进制转字符
uint8_t HexToChar(uint8_t temp)
{
    uint8_t dst;
    if (temp < 10)
    {
        dst = temp + '0';
    }
    else
    {
        dst = temp - 10 + 'A';
    }
    return dst;
}

static void saadc_callback(nrf_drv_saadc_evt_t const *p_event)
{
    if (p_event->type == NRF_DRV_SAADC_EVT_DONE)
    {
				int now_rate = 0, i=0;
        ret_code_t err_code;

        // 设置好缓存，为下一次采样准备
        err_code = nrf_drv_saadc_buffer_convert(p_event->data.done.p_buffer, SAMPLES_IN_BUFFER);
        APP_ERROR_CHECK(err_code);
			
				battery_value = ((float)p_event->data.done.p_buffer[2] * (VDD_VOLTAGE / ADC_RESOLUTION) * 3);

				battery = (uint8_t)(battery_value * 100);

			
				if (battery_value < 1.3)
						battery = 1;
				else if (battery_value > 1.6)
						battery = 100;
				else
						battery = (uint8_t)((battery_value-1.3) * (100/(1.6-1.3)));
				
				AD_value = ((float)p_event->data.done.p_buffer[0]) * (VDD_VOLTAGE / ADC_RESOLUTION) * 3;
        if (Channel1_Digital_Filter_Open_flag) // 如果通道1开启滤波
        {
            Filter_Data = filter(IIR_Filter1_All(AD_value)) + 0.9;
            Send_Data = (uint16_t)(Filter_Data * 10000);
        }
        else // 如果通道1不开启滤波
        {
            Send_Data = (uint16_t)(AD_value * 10000);
        }

				
				
				AD_value1 = ((float)p_event->data.done.p_buffer[1]) * (VDD_VOLTAGE / ADC_RESOLUTION) * 3;
        if (Channel2_Digital_Filter_Open_flag) // 如果通道2开启滤波
        {
            Filter_Data1 = filter1(IIR1_Filter1_All(AD_value1)) + 0.9;
            Send_Data1 = (uint16_t)(Filter_Data1 * 10000);
        }
        else // 如果通道2不开启滤波
        {
            Send_Data1 = (uint16_t)(AD_value1 * 10000);
        }

				
				adc_result[4 + send_cnt*4] = (uint8_t)(Send_Data >> 8);
				adc_result[5 + send_cnt*4] = (uint8_t)(Send_Data);
				
				adc_result[6 + send_cnt*4] = (uint8_t)(Send_Data1 >> 8);
				adc_result[7 + send_cnt*4] = (uint8_t)(Send_Data1);
				
				send_cnt++;
				

				now_rate = get_heart_rate(Filter_Data * 1000.0);
				count_HR++;
				
				if(count_HR == 499)
				{
					avg_rate = 0;
					avg_rate_list[0] = avg_rate_list[1];
					avg_rate_list[1] = avg_rate_list[2];
					avg_rate_list[2] = avg_rate_list[3];
					avg_rate_list[3] = avg_rate_list[4];
					avg_rate_list[4] = now_rate;
					count_HR = 0;
					for(i=0; i<5; i++)
					{
						avg_rate += avg_rate_list[i];
					}
					avg_rate /= 5;
				}
				
				
				
				
				if(send_cnt == 4)
				{
					send_cnt = 0;
//					if(LDF(Send_Data) == 0)
//					{
//						nrf_gpio_pin_set(LED_3);
//					}
//					else
//					{
//						nrf_gpio_pin_clear(LED_3);
//						return;
//					}
					num_test++;
					if(num_test > 0xff)
					{
						num_test = 0;
					}
					adc_result[0] = num_test;
					adc_result[3] = battery;
					adc_result[21] = avg_rate;
					adc_result[length - 1] = Fast_CRC_Cal8Bits(0x00, length - 1, adc_result);
					ble_uarts_data_send(&m_uarts, adc_result, &length, m_conn_handle); // 直接发送16进制的数据，不用转换为字符串
				}
    }
}

// 串口配置
void uart_config(void)
{
    uint32_t err_code;

    // 定义串口通讯参数配置结构体并初始化
    const app_uart_comm_params_t comm_params =
        {
            RX_PIN_NUMBER,                  // 定义uart接收引脚
            TX_PIN_NUMBER,                  // 定义uart发送引脚
            RTS_PIN_NUMBER,                 // 定义uart RTS引脚，流控关闭后虽然定义了RTS和CTS引脚，但是驱动程序会忽略，不会配置这两个引脚，两个引脚仍可作为IO使用
            CTS_PIN_NUMBER,                 // 定义uart CTS引脚
            APP_UART_FLOW_CONTROL_DISABLED, // 关闭uart硬件流控
            false,                          // 禁止奇偶检验
            NRF_UART_BAUDRATE_115200        // uart波特率设置为115200bps
        };
    // 初始化串口，注册串口事件回调函数
    APP_UART_FIFO_INIT(&comm_params,
                       UART_RX_BUF_SIZE,
                       UART_TX_BUF_SIZE,
                       uart_event_handle,
                       APP_IRQ_PRIORITY_LOWEST,
                       err_code);

    APP_ERROR_CHECK(err_code);
}

/***************************

通道0：采样VO1
通道2：采样VO2
通道3：采样供电电压

 ***************************/
static void saadc_config(void)
{
    ret_code_t err_code;

    // 定义SAADC采样通道0初始化配置结构体变量，并使用默认参数初始化
		//通道1
    nrf_saadc_channel_config_t channel_0_config =
        NRF_DRV_SAADC_DEFAULT_CHANNEL_CONFIG_SE(NRF_SAADC_INPUT_AIN0);

    channel_0_config.gain = NRF_SAADC_GAIN1_3;
    channel_0_config.reference = NRF_SAADC_REFERENCE_INTERNAL;
		//通道2
    nrf_saadc_channel_config_t channel_1_config =
        NRF_DRV_SAADC_DEFAULT_CHANNEL_CONFIG_SE(NRF_SAADC_INPUT_AIN2);

    channel_1_config.gain = NRF_SAADC_GAIN1_3;
    channel_1_config.reference = NRF_SAADC_REFERENCE_INTERNAL;
		//电量
    nrf_saadc_channel_config_t channel_2_config =
        NRF_DRV_SAADC_DEFAULT_CHANNEL_CONFIG_SE(NRF_SAADC_INPUT_AIN3);
	
    channel_2_config.gain = NRF_SAADC_GAIN1_3;
    channel_2_config.reference = NRF_SAADC_REFERENCE_INTERNAL;

    // 初始化SAADC，注册事件回调函数。注意，本例使用的是非堵塞模式，非堵塞模式下驱动程序采样完成后
    // 以事件的方式通知应用程序，应用程序在事件回调函数中读取采样数据
    err_code = nrf_drv_saadc_init(NULL, saadc_callback);
    APP_ERROR_CHECK(err_code);
    // 初始化SAADC采样通道0
    err_code = nrf_drv_saadc_channel_init(0, &channel_0_config);
    APP_ERROR_CHECK(err_code);
    // 初始化SAADC采样通道1
    err_code = nrf_drv_saadc_channel_init(1, &channel_1_config);
    APP_ERROR_CHECK(err_code);

    err_code = nrf_drv_saadc_channel_init(2, &channel_2_config);
    APP_ERROR_CHECK(err_code);
    //初始化SAADC采样通道2

    // 使用双缓存
    // 设置好第一个缓存
    err_code = nrf_drv_saadc_buffer_convert(m_buffer_pool[0], SAMPLES_IN_BUFFER);
    APP_ERROR_CHECK(err_code);
    // 设置好第二个缓存，等待应用程序启动采样
    err_code = nrf_drv_saadc_buffer_convert(m_buffer_pool[1], SAMPLES_IN_BUFFER);
    APP_ERROR_CHECK(err_code);
}

// 主函数
int main(void)
{
    //  uint32_t err_code;
    //  bool erase_bonds;
    system_power_on();
    // 初始化log程序模块
    log_init();
    // 初始化串口
    uart_config();
    // 初始化APP定时器
    timers_init();
    // 出使唤按键和指示灯
    leds_init();
    Ks1802_Init();
    // 初始化电源管理
    power_management_init();
    // 初始化协议栈
    ble_stack_init();
    // 配置GAP参数
    gap_params_init();
    // 初始化GATT
    gatt_init();
    // 初始化服务
    services_init();
    // 初始化广播
    advertising_init();
    // 连接参数协商初始化
    conn_params_init();

    // 配置SAADC
    saadc_config();
    // 启动应用定时器
    application_timers_start();

    NRF_LOG_INFO("BLE Template example started.");
    //	//启动广播
    advertising_start();

    nrf_gpio_cfg_output(19);
    nrf_gpio_cfg_output(20);
		nrf_gpio_cfg_output(23);

    nrf_gpio_pin_set(19);
    nrf_gpio_pin_set(20);
		nrf_gpio_pin_set(23);
		nrf_gpio_pin_clear(23);
		
		//nrf_gpio_cfg_input(23, NRF_GPIO_PIN_NOPULL);  //设置LDFIO口为输入模式，用来做脱落检测输入信号
		
    KS1082_Write_Reg(ks1082_REG_ADDR_CH1SET, 0x20);
    KS1082_Write_Reg(ks1082_REG_ADDR_CH2SET, 0x00);
		
		// 添加500ms延时
    nrf_delay_ms(500);
    
    // 延时后再次写入相同的寄存器值
    KS1082_Write_Reg(ks1082_REG_ADDR_CH1SET, 0x20);
    KS1082_Write_Reg(ks1082_REG_ADDR_CH2SET, 0x00);

    // bsp_board_led_on(2);
    nrf_gpio_pin_set(LED_3); // 点亮红灯
    //	nrf_gpio_pin_clear(23);
		
		bsp_indication_set(BSP_INDICATE_ADVERTISING_SLOW);
		
		adc_result[0] = 0xFF;
		adc_result[1] = 0x06;
		adc_result[2] = 0x04;
    // printf("OK\r\n");
    // 主循环
		NRF_LOG_ERROR("test");
    while (true)
    {
        // 处理挂起的LOG和运行电源管理
        idle_state_handle();
    }
}

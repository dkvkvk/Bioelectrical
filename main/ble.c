#include "ble.h"
#include "uart.h"
#include "protocol_crc.h"
#include "host/ble_att.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include <string.h>

static const char *TAG = "BLE";

// Service UUID: 与 nRF52832 上位机一致
// 86530000-43e6-47b7-9cb0-5fc21d4ae340  (BASE, 字节12-13替换为具体16位UUID)
// Service:   0x000A → 40 E3 4A 1D C2 5F B0 9C B7 47 E6 43 0A 00 53 86
// TX (Notify): 0x000B → 40 E3 4A 1D C2 5F B0 9C B7 47 E6 43 0B 00 53 86
// RX (Write):  0x000C → 40 E3 4A 1D C2 5F B0 9C B7 47 E6 43 0C 00 53 86
static const ble_uuid128_t svc_uuid128 = BLE_UUID128_INIT(
    0x40, 0xe3, 0x4a, 0x1d, 0xc2, 0x5f, 0xb0, 0x9c,
    0xb7, 0x47, 0xe6, 0x43, 0x0a, 0x00, 0x53, 0x86
);

// Data (Notify): 0x000B
static const ble_uuid128_t data_chr_uuid128 = BLE_UUID128_INIT(
    0x40, 0xe3, 0x4a, 0x1d, 0xc2, 0x5f, 0xb0, 0x9c,
    0xb7, 0x47, 0xe6, 0x43, 0x0b, 0x00, 0x53, 0x86
);

// Command (Write): 0x000C
static const ble_uuid128_t cmd_chr_uuid128 = BLE_UUID128_INIT(
    0x40, 0xe3, 0x4a, 0x1d, 0xc2, 0x5f, 0xb0, 0x9c,
    0xb7, 0x47, 0xe6, 0x43, 0x0c, 0x00, 0x53, 0x86
);

static uint16_t conn_handle;
static uint16_t data_chr_val_handle;
static volatile bool is_connected;
static volatile bool notify_enabled;
static bool ble_synced;
static esp_timer_handle_t conn_param_timer;
static uint8_t conn_param_attempts;

#define BLE_FRAME_LEN 23
#define BLE_FRAME_MIN_ATT_MTU (BLE_FRAME_LEN + 3)
#define BLE_CONN_ITVL_MIN 6
#define BLE_CONN_ITVL_MAX 12
#define BLE_CONN_LATENCY 0
#define BLE_CONN_SUPERVISION_TIMEOUT 400
#define BLE_CONN_PARAM_FIRST_DELAY_US 5000000LL
#define BLE_CONN_PARAM_RETRY_DELAY_US 30000000LL
#define BLE_CONN_PARAM_MAX_ATTEMPTS 6

extern void ble_on_cmd_received(const uint8_t *cmd, int len);

static void ble_advertise(void);

static void schedule_conn_param_update(int64_t delay_us)
{
    if (conn_param_timer == NULL || !is_connected ||
        conn_param_attempts >= BLE_CONN_PARAM_MAX_ATTEMPTS) {
        return;
    }

    esp_err_t stop_err = esp_timer_stop(conn_param_timer);
    if (stop_err != ESP_OK && stop_err != ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "conn param timer stop failed: %s", esp_err_to_name(stop_err));
    }
    esp_err_t start_err = esp_timer_start_once(conn_param_timer, delay_us);
    if (start_err != ESP_OK) {
        ESP_LOGW(TAG, "conn param timer start failed: %s", esp_err_to_name(start_err));
    }
}

static void conn_param_timer_cb(void *arg)
{
    (void)arg;
    if (!is_connected || conn_param_attempts >= BLE_CONN_PARAM_MAX_ATTEMPTS) {
        return;
    }

    struct ble_gap_upd_params params = {
        .itvl_min = BLE_CONN_ITVL_MIN,
        .itvl_max = BLE_CONN_ITVL_MAX,
        .latency = BLE_CONN_LATENCY,
        .supervision_timeout = BLE_CONN_SUPERVISION_TIMEOUT,
        .min_ce_len = 0,
        .max_ce_len = 0,
    };

    conn_param_attempts++;
    int rc = ble_gap_update_params(conn_handle, &params);
    if (rc != 0) {
        ESP_LOGW(TAG, "connection parameter request failed immediately: rc=%d attempt=%u",
                 rc, (unsigned int)conn_param_attempts);
        schedule_conn_param_update(BLE_CONN_PARAM_RETRY_DELAY_US);
    }
}

// CRC-8 校验（查表法，多项式 0x97，与 nRF52832 一致）
void ble_stop_advertising(void) {
    if (ble_synced && ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
}

void ble_advertise_restart(void) {
    ble_advertise();
}

static bool enter_ble_link(uint16_t handle) {
    if (uart_is_connected()) {
        return false;
    }

    conn_handle = handle;
    is_connected = true;
    notify_enabled = false;
    conn_param_attempts = 0;
    schedule_conn_param_update(BLE_CONN_PARAM_FIRST_DELAY_US);
    return true;
}

static void leave_ble_link(void) {
    is_connected = false;
    notify_enabled = false;
    conn_param_attempts = 0;
    if (conn_param_timer != NULL) {
        esp_timer_stop(conn_param_timer);
    }
    ble_advertise();
}

static int data_chr_access(uint16_t conn_handle, uint16_t attr_handle,
                           struct ble_gatt_access_ctxt *ctxt, void *arg) {
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint16_t om_len = OS_MBUF_PKTLEN(ctxt->om);
        uint8_t buf[32];
        uint16_t copy_len = om_len > sizeof(buf) ? sizeof(buf) : om_len;
        ble_hs_mbuf_to_flat(ctxt->om, buf, copy_len, &copy_len);
        ESP_LOGI(TAG, "DATA CHR WRITE (%d bytes):", copy_len);
        for (int i = 0; i < copy_len; i++) ets_printf("%02X ", buf[i]);
        ets_printf("\n");
    }
    return 0;
}

static int cmd_chr_access(uint16_t conn_handle, uint16_t attr_handle,
                          struct ble_gatt_access_ctxt *ctxt, void *arg) {
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint16_t om_len = OS_MBUF_PKTLEN(ctxt->om);
        uint8_t buf[32];
        uint16_t copy_len = om_len > sizeof(buf) ? sizeof(buf) : om_len;
        ble_hs_mbuf_to_flat(ctxt->om, buf, copy_len, &copy_len);

        ESP_LOGI(TAG, "BLE RX raw (%d bytes):", copy_len);
        for (int i = 0; i < copy_len; i++) {
            ets_printf("%02X ", buf[i]);
        }
        ets_printf("\n");

        if (copy_len == 6) {
            ble_on_cmd_received(buf, 6);
        } else {
            ESP_LOGW(TAG, "CMD: got %d bytes (expect 6)", copy_len);
        }
    }
    return 0;
}

static const struct ble_gatt_svc_def gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &svc_uuid128.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid = &cmd_chr_uuid128.u,
                .access_cb = cmd_chr_access,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP | BLE_GATT_CHR_F_READ,
            },
            {
                .uuid = &data_chr_uuid128.u,
                .access_cb = data_chr_access,
                .flags = BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &data_chr_val_handle,
            },
            { 0 }
        },
    },
    { 0 }
};

static int gap_event_handler(struct ble_gap_event *event, void *arg) {
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        ESP_LOGI(TAG, "EVENT: CONNECT status=%d %s",
                 event->connect.status,
                 event->connect.status == 0 ? "[OK]" : "[FAIL]");
        if (event->connect.status == 0) {
            if (!enter_ble_link(event->connect.conn_handle)) {
                ESP_LOGW(TAG, "BLE connect rejected: UART link is active");
                ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
            }
        } else {
            is_connected = false;
            notify_enabled = false;
            conn_param_attempts = 0;
            if (conn_param_timer != NULL) {
                esp_timer_stop(conn_param_timer);
            }
            ble_advertise();
        }
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "EVENT: DISCONNECT reason=%d", event->disconnect.reason);
        leave_ble_link();
        break;
    case BLE_GAP_EVENT_SUBSCRIBE:
        ESP_LOGI(TAG, "EVENT: SUBSCRIBE cur=%d attr=%d",
                 event->subscribe.cur_notify,
                 event->subscribe.attr_handle);
        if (event->subscribe.attr_handle == data_chr_val_handle) {
            notify_enabled = (event->subscribe.cur_notify != 0);
        }
        break;
    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "EVENT: MTU=%d", event->mtu.value);
        break;
    case BLE_GAP_EVENT_CONN_UPDATE:
        ESP_LOGI(TAG, "EVENT: CONN_UPDATE status=%d",
                 event->conn_update.status);
        if (event->conn_update.status != 0) {
            schedule_conn_param_update(BLE_CONN_PARAM_RETRY_DELAY_US);
        }
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        ble_advertise();
        break;
    default:
        break;
    }
    return 0;
}

static void ble_advertise(void) {
    if (!ble_synced || uart_is_connected() || is_connected || ble_gap_adv_active()) {
        return;
    }

    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.tx_pwr_lvl_is_present = 1;
    fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    fields.uuids128 = &svc_uuid128;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    ble_gap_adv_set_fields(&fields);

    struct ble_hs_adv_fields rsp_fields = {0};
    const char *dev_name = ble_svc_gap_device_name();
    rsp_fields.name = (const uint8_t *)dev_name;
    rsp_fields.name_len = strlen(dev_name);
    rsp_fields.name_is_complete = 1;
    ble_gap_adv_rsp_set_fields(&rsp_fields);

    struct ble_gap_adv_params adv_params = {0};
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    int rc = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                               &adv_params, gap_event_handler, NULL);
    if (rc != 0) {
        ESP_LOGW(TAG, "ble_gap_adv_start failed: rc=%d", rc);
    }
}

static void ble_on_sync(void) {
    ble_synced = true;
    ble_advertise();
}

static void ble_on_reset(int reason) {
    ESP_LOGE(TAG, "reset; reason=%d", reason);
    is_connected = false;
    notify_enabled = false;
    ble_synced = false;
    conn_param_attempts = 0;
    if (conn_param_timer != NULL) {
        esp_timer_stop(conn_param_timer);
    }
}

static void ble_host_task(void *param) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}

bool ble_is_connected(void) {
    return is_connected;
}

// 帧格式：0xFF 0x17 0x2E + 电量(1) + CH1/CH2×4组(16) + 脱落(1) + 心率(1) + CRC8(1)
bool ble_send_frame(uint8_t battery,
                    const uint16_t ch1[4], const uint16_t ch2[4],
                    uint8_t lead_off, uint8_t heart_rate) {
    uint8_t buf[BLE_FRAME_LEN];
    buf[0] = 0xFF;
    buf[1] = 0x17;
    buf[2] = 0x2E;
    buf[3] = battery;
    for (int i = 0; i < 4; i++) {
        buf[4 + i * 4]     = (uint8_t)(ch1[i] >> 8);
        buf[4 + i * 4 + 1] = (uint8_t)ch1[i];
        buf[4 + i * 4 + 2] = (uint8_t)(ch2[i] >> 8);
        buf[4 + i * 4 + 3] = (uint8_t)ch2[i];
    }
    buf[20] = lead_off;
    buf[21] = heart_rate;
    buf[22] = Fast_CRC_Cal8Bits(0x00, 22, buf);

    if (!is_connected || !notify_enabled) {
        return false;
    }

    // A 23-byte notification needs ATT MTU >= 26 (three bytes are ATT overhead).
    // Do not silently truncate the existing protocol frame when the client has
    // not completed MTU exchange yet.
    if (ble_att_mtu(conn_handle) < BLE_FRAME_MIN_ATT_MTU) {
        return false;
    }

    struct os_mbuf *om = ble_hs_mbuf_from_flat(buf, sizeof(buf));
    if (om == NULL) {
        return false;
    }

    // NimBLE consumes the mbuf on both success and failure.
    int rc = ble_gatts_notify_custom(conn_handle, data_chr_val_handle, om);
    if (rc != 0) {
        ESP_LOGW(TAG, "notify failed: rc=%d", rc);
        return false;
    }
    return true;
}

void ble_init(void) {
    const esp_timer_create_args_t conn_param_timer_args = {
        .callback = conn_param_timer_cb,
        .name = "ble_conn_params",
    };
    ESP_ERROR_CHECK(esp_timer_create(&conn_param_timer_args, &conn_param_timer));

    ESP_ERROR_CHECK(nimble_port_init());

    esp_log_level_set("NimBLE", ESP_LOG_NONE);

    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_hs_cfg.reset_cb = ble_on_reset;

    ble_svc_gap_init();
    ble_svc_gatt_init();

    ESP_ERROR_CHECK(ble_gatts_count_cfg(gatt_svcs));
    ESP_ERROR_CHECK(ble_gatts_add_svcs(gatt_svcs));

    ble_svc_gap_device_name_set("BLE_EEG");

    nimble_port_freertos_init(ble_host_task);
    ESP_LOGI(TAG, "BLE initialized");
}

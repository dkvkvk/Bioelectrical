/*
 * BLE transport layer (Zephyr native Bluetooth Host port).
 *
 * This is a port of the ESP-IDF NimBLE implementation to the Zephyr native
 * Bluetooth Host API. The on-air behaviour is identical:
 *
 *   Service  : 8653000a-43e6-47b7-9cb0-5fc21d4ae340
 *   Data     : 8653000b-43e6-47b7-9cb0-5fc21d4ae340  (Notify)
 *   Command  : 8653000c-43e6-47b7-9cb0-5fc21d4ae340  (Write / Write-no-rsp)
 *   Device name: 'BLE_EEG'
 */

#include "ble.h"
#include "uart.h"
#include "protocol_crc.h"

#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(ble, LOG_LEVEL_INF);

/* ------------------------------------------------------------------ */
/* UUIDs. 128-bit vendor UUIDs matching the nRF52832 host protocol.    */
/* ------------------------------------------------------------------ */

/* Service: 8653000a-43e6-47b7-9cb0-5fc21d4ae340 */
#define SVC_UUID  BT_UUID_DECLARE_128(BT_UUID_128_ENCODE(0x8653000a, 0x43e6, 0x47b7, 0x9cb0, 0x5fc21d4ae340))
/* Data (Notify): 8653000b-43e6-47b7-9cb0-5fc21d4ae340 */
#define DATA_UUID BT_UUID_DECLARE_128(BT_UUID_128_ENCODE(0x8653000b, 0x43e6, 0x47b7, 0x9cb0, 0x5fc21d4ae340))
/* Command (Write): 8653000c-43e6-47b7-9cb0-5fc21d4ae340 */
#define CMD_UUID  BT_UUID_DECLARE_128(BT_UUID_128_ENCODE(0x8653000c, 0x43e6, 0x47b7, 0x9cb0, 0x5fc21d4ae340))

#define BLE_FRAME_LEN 23
#define BLE_FRAME_MIN_ATT_MTU (BLE_FRAME_LEN + 3)

/* Connection parameters (units: interval *1.25ms, timeout *10ms). */
#define BLE_CONN_ITVL_MIN 6
#define BLE_CONN_ITVL_MAX 12
#define BLE_CONN_LATENCY 0
#define BLE_CONN_SUPERVISION_TIMEOUT 400

static struct bt_conn *default_conn;
static volatile bool is_connected;
static volatile bool notify_enabled;

extern void ble_on_cmd_received(const uint8_t *cmd, int len);

/* ------------------------------------------------------------------ */
/* GATT callbacks                                                     */
/* ------------------------------------------------------------------ */

static ssize_t cmd_chr_write(struct bt_conn *conn,
			     const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len,
			     uint16_t offset, uint8_t flags)
{
	uint8_t cmd[6];

	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}

	if (len == 6) {
		memcpy(cmd, buf, 6);
		LOG_INF("BLE RX raw (6 bytes):");
		LOG_HEXDUMP_INF(cmd, 6, "BLE RX");
		ble_on_cmd_received(cmd, 6);
	} else {
		LOG_WRN("CMD: got %d bytes (expect 6)", len);
	}

	return len;
}

static ssize_t data_chr_write(struct bt_conn *conn,
			      const struct bt_gatt_attr *attr,
			      const void *buf, uint16_t len,
			      uint16_t offset, uint8_t flags)
{
	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	LOG_INF("DATA CHR WRITE (%d bytes)", len);
	LOG_HEXDUMP_INF(buf, len, "DATA WRITE");
	return len;
}

static void data_chr_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
	notify_enabled = (value == BT_GATT_CCC_NOTIFY);
	LOG_INF("SUBSCRIBE: notify_enabled=%d", notify_enabled);
}

/* GATT service definition. Command characteristic is writable (with and
 * without response, to be robust to the host client), Data characteristic is
 * notifiable with a managed CCC descriptor (one per possible connection). */
BT_GATT_SERVICE_DEFINE(ble_svc,
	BT_GATT_PRIMARY_SERVICE(SVC_UUID),
	BT_GATT_CHARACTERISTIC(CMD_UUID,
			       BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
			       BT_GATT_PERM_WRITE,
			       NULL, cmd_chr_write, NULL),
	BT_GATT_CHARACTERISTIC(DATA_UUID,
			       BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_NONE,
			       NULL, data_chr_write, NULL),
	BT_GATT_CCC(data_chr_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

/* ------------------------------------------------------------------ */
/* Connection callbacks                                               */
/* ------------------------------------------------------------------ */

static void on_connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("CONNECT failed: err=%d", err);
		return;
	}

	if (uart_is_connected()) {
		LOG_WRN("CONNECT rejected: UART link is active");
		bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		return;
	}

	default_conn = bt_conn_ref(conn);
	is_connected = true;
	notify_enabled = false;
	LOG_INF("CONNECT [OK]");

	/* Request preferred connection parameters. */
	struct bt_le_conn_param param = BT_LE_CONN_PARAM_INIT(
		BLE_CONN_ITVL_MIN, BLE_CONN_ITVL_MAX,
		BLE_CONN_LATENCY, BLE_CONN_SUPERVISION_TIMEOUT);
	int rc = bt_conn_le_param_update(conn, &param);
	if (rc) {
		LOG_WRN("conn param update request failed: rc=%d", rc);
	}
}

static void on_disconnected(struct bt_conn *conn, uint8_t reason)
{
	LOG_INF("DISCONNECT reason=%d", reason);
	is_connected = false;
	notify_enabled = false;

	if (default_conn) {
		bt_conn_unref(default_conn);
		default_conn = NULL;
	}

	ble_advertise_restart();
}

static struct bt_conn_cb conn_callbacks = {
	.connected = on_connected,
	.disconnected = on_disconnected,
};

/* 记录协商到的 ATT MTU，用于诊断（>=26 才能发 23 字节通知） */
static volatile uint16_t g_att_mtu_rx;

static void on_att_mtu_updated(struct bt_conn *conn, uint16_t tx, uint16_t rx)
{
	g_att_mtu_rx = rx;
	LOG_INF("MTU updated: tx=%d rx=%d (need >= 26 for notify)", tx, rx);
}

static struct bt_gatt_cb gatt_callbacks = {
	.att_mtu_updated = on_att_mtu_updated,
};

/* ------------------------------------------------------------------ */
/* Advertising                                                        */
/* ------------------------------------------------------------------ */

static const struct bt_data ad_data[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL,
		      BT_UUID_128_ENCODE(0x8653000a, 0x43e6, 0x47b7, 0x9cb0, 0x5fc21d4ae340)),
};

/* 设备名放进"扫描响应"（scan response），与原版 NimBLE 一致：
 * 原版用 ble_gap_adv_rsp_set_fields 把 "BLE_EEG" 放到 rsp，主广播只放 flags+UUID。 */
static const struct bt_data sd_data[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE,
		CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static void ble_advertise(void)
{
	/* Connectable, general-discoverable advertising. The controller stops
	 * advertising automatically when a connection is established; we restart
	 * it after a disconnect (see on_disconnected). */
	int rc = bt_le_adv_start(BT_LE_ADV_CONN_FAST_2,
				 ad_data, ARRAY_SIZE(ad_data),
				 sd_data, ARRAY_SIZE(sd_data));
	if (rc && rc != -EALREADY) {
		LOG_WRN("bt_le_adv_start failed: rc=%d", rc);
	}
}

static void ble_on_ready(int err)
{
	if (err) {
		LOG_ERR("BT init failed: err=%d", err);
		return;
	}
	LOG_INF("BLE initialized (ready), advertising as 'BLE_EEG'");
	ble_advertise();
}

/* ------------------------------------------------------------------ */
/* Public API                                                         */
/* ------------------------------------------------------------------ */

void ble_init(void)
{
	bt_conn_cb_register(&conn_callbacks);
	bt_gatt_cb_register(&gatt_callbacks);

	int rc = bt_enable(ble_on_ready);
	if (rc) {
		LOG_ERR("bt_enable failed: rc=%d", rc);
	}
}

bool ble_is_connected(void)
{
	return is_connected;
}

void ble_stop_advertising(void)
{
	int rc = bt_le_adv_stop();
	if (rc && rc != -EALREADY) {
		LOG_WRN("bt_le_adv_stop failed: rc=%d", rc);
	}
}

void ble_advertise_restart(void)
{
	if (!is_connected && !uart_is_connected()) {
		ble_advertise();
	}
}

bool ble_send_frame(uint8_t battery,
		    const uint16_t ch1[4], const uint16_t ch2[4],
		    uint8_t lead_off, uint8_t heart_rate)
{
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

	/* A 23-byte notification needs ATT MTU >= 26. */
	if (bt_gatt_get_mtu(default_conn) < BLE_FRAME_MIN_ATT_MTU) {
		return false;
	}

	const struct bt_gatt_attr *data_attr =
		bt_gatt_find_by_uuid(NULL, 0, DATA_UUID);

	int rc = bt_gatt_notify(default_conn, data_attr, buf, sizeof(buf));
	if (rc) {
		LOG_WRN("notify failed: rc=%d", rc);
		return false;
	}
	return true;
}

/* 诊断：打印当前 BLE 链路状态，用于排查"上位机收不到数据"。 */
void ble_dump_state(void)
{
	uint16_t mtu = is_connected ? bt_gatt_get_mtu(default_conn) : 0;
	LOG_INF("BLE-STATE connected=%d notify=%d mtu=%d",
		is_connected ? 1 : 0,
		notify_enabled ? 1 : 0,
		mtu);
}
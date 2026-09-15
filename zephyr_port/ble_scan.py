import asyncio
from bleak import BleakScanner


async def main():
    print("Scanning 20 seconds...")
    devices = await BleakScanner.discover(timeout=20.0, return_adv=True)
    print(f"Total found: {len(devices)}")
    for addr, (dev, adv) in devices.items():
        name = dev.name or "(no-name)"
        rssi = adv.rssi
        uuids = [str(u) for u in (adv.service_uuids or [])]
        mfr = adv.manufacturer_data
        print(f"FOUND: name=[{name}] addr={addr} rssi={rssi}dBm uuids={uuids} mfr={mfr}")
    print("Scan done.")


asyncio.run(main())

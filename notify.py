import asyncio
from bleak import BleakClient

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

CALIBRATION_OFFSET = 2.5  # adjust if needed


def parse(data):
    if len(data) != 8:
        return None

    b = int.from_bytes(data[2:4], "little")
    c = int.from_bytes(data[4:6], "little")

    # FIXED mapping
    internal_c = (b / 2) - CALIBRATION_OFFSET
    ambient_c = c / 100

    return {
        "internal_c": internal_c,
        "internal_f": internal_c * 9 / 5 + 32,
        "ambient_c": ambient_c,
        "ambient_f": ambient_c * 9 / 5 + 32,
    }


def handle(sender, data):
    parsed = parse(data)
    if not parsed:
        return

    print(
        f"Internal: {parsed['internal_f']:.1f}°F "
        f"({parsed['internal_c']:.1f}°C) | "
        f"Ambient: {parsed['ambient_f']:.1f}°F "
        f"({parsed['ambient_c']:.1f}°C)"
    )


async def run():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)

        await client.start_notify(NOTIFY_UUID, handle)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await client.stop_notify(NOTIFY_UUID)


asyncio.run(run())
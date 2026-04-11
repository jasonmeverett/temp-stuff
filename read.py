import asyncio

from bleak import BleakClient

from probe_decode import decode_mode_label, format_raw_line, parse

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
READ_VERSION_UUID = "0000ff03-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"


async def run():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)

        ver = await client.read_gatt_char(READ_VERSION_UUID)
        print("Version (ff03, read):", ver.decode("utf-8", errors="replace"))

        print("Subscribing to ff01; waiting for one 8-byte notification…")
        loop = asyncio.get_event_loop()
        first_frame: asyncio.Future[bytes] = loop.create_future()

        def on_notify(_sender, data: bytearray) -> None:
            if first_frame.done():
                return
            b = bytes(data)
            if len(b) == 8:
                first_frame.set_result(b)

        await client.start_notify(NOTIFY_UUID, on_notify)
        try:
            data = await asyncio.wait_for(first_frame, timeout=15.0)
        except asyncio.TimeoutError:
            print("Timed out waiting for ff01 notify.")
            return
        finally:
            await client.stop_notify(NOTIFY_UUID)

        print(format_raw_line(data))
        parsed = parse(data)
        if parsed:
            print(
                f"Internal: {parsed['internal_f']:.1f}°F "
                f"({parsed['internal_c']:.1f}°C)\n"
                f"Ambient:  {parsed['ambient_f']:.1f}°F "
                f"({parsed['ambient_c']:.1f}°C)\n"
                f"({decode_mode_label()})"
            )


asyncio.run(run())

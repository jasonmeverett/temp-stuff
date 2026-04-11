"""Subscribe to the same FF01 notify as notify.py; print the exact notify payload bytes only."""

import asyncio
import os
import sys
from datetime import datetime, timezone

from bleak import BleakClient

from probe_decode import format_raw_line

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"


def handle(sender, data) -> None:
    b = bytes(data)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Exact packet: contiguous hex is lossless; list(b) is each byte value 0–255.
    sys.stdout.write(
        f"{ts} len={len(b)} hex={b.hex()} bytes={list(b)}\n"
    )
    sys.stdout.flush()
    if os.environ.get("NOTIFY_RAW_PROBE", "").strip() in ("1", "true", "yes"):
        sys.stdout.write(f"{ts} probe_decode: {format_raw_line(b)}\n")
        sys.stdout.flush()


async def run() -> None:
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected, flush=True)
        print(
            "Each line: UTC time, length, hex (raw octets, no spaces), "
            "bytes=[...] decimal values. NOTIFY_RAW_PROBE=1 adds probe_decode hint.",
            flush=True,
        )
        await client.start_notify(NOTIFY_UUID, handle)
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...", flush=True)
        finally:
            await client.stop_notify(NOTIFY_UUID)


if __name__ == "__main__":
    asyncio.run(run())

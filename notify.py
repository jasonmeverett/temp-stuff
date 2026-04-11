import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bleak import BleakClient

from probe_decode import decode_mode_label, format_raw_line, parse

ADDRESS = "6E00D83A-7480-3FCF-D7C5-7D89FBDD8974"
# Same family as e.g. ff01/ff02/ff03 custom chars (see ble_ctf_infinity-style layouts).
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

TELEMETRY_WRITE_URL = os.environ.get(
    "TELEMETRY_WRITE_URL",
    "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com/write",
).strip()
SMOKE_ID = os.environ.get("SMOKE_ID", "pbdp").strip() or "smoke-01"


def _post_write(internal: float, ambient: float) -> None:
    if not TELEMETRY_WRITE_URL:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = json.dumps(
        {
            "timestamp": ts,
            "smoke_id": SMOKE_ID,
            "internal": internal,
            "ambient": ambient,
        }
    ).encode("utf-8")
    req = Request(
        TELEMETRY_WRITE_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                print(f"Telemetry write HTTP {resp.status}")
    except HTTPError as e:
        print(f"Telemetry write failed: HTTP {e.code}")
    except URLError as e:
        print(f"Telemetry write failed: {e.reason}")


def handle(sender, data):
    parsed = parse(data)
    if not parsed:
        return

    if not os.environ.get("NOTIFY_QUIET_RAW"):
        print(format_raw_line(bytes(data)))

    print(
        f"Internal: {parsed['internal_f']:.1f}°F "
        f"({parsed['internal_c']:.1f}°C) | "
        f"Ambient: {parsed['ambient_f']:.1f}°F "
        f"({parsed['ambient_c']:.1f}°C)"
    )
    _post_write(parsed["internal_f"], parsed["ambient_f"])


async def run():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)
        print(f"Decode: {decode_mode_label()}")
        print("NOTIFY_PARSE=legacy restores old °C-tenths guess; NOTIFY_QUIET_RAW=1 hides RAW line.")

        await client.start_notify(NOTIFY_UUID, handle)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await client.stop_notify(NOTIFY_UUID)


asyncio.run(run())

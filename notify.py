import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bleak import BleakClient

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

CALIBRATION_OFFSET = 2.5  # adjust if needed

# Set after deploy from CDK output WriteEndpointUrl (full URL ending in /write)
# TELEMETRY_WRITE_URL = os.environ.get("TELEMETRY_WRITE_URL", "").strip()
TELEMETRY_WRITE_URL = "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com/write"
SMOKE_ID = os.environ.get("SMOKE_ID", "smoke-01").strip() or "smoke-01"


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

        await client.start_notify(NOTIFY_UUID, handle)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await client.stop_notify(NOTIFY_UUID)


asyncio.run(run())
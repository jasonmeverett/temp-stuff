import asyncio
import logging
import time
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

SERVICE = "1086fff0-3343-4817-8bb2-b32206336ce8"
COMMAND = "1086fff1-3343-4817-8bb2-b32206336ce8"
NOTIFY = "1086fff2-3343-4817-8bb2-b32206336ce8"
START_STREAM = bytes.fromhex("01 09 8a 7a 13 b7 3e d6 8b 67 c2 a0")
REQUEST_TEMPERATURE = bytes.fromhex("30 00 30")
MAX_READING_AGE = 6

logger = logging.getLogger(__name__)


def decode_probe(encoded: bytes) -> float | None:
    digits = [encoded[0] >> 4, encoded[0] & 15, encoded[1] >> 4, encoded[1] & 15]
    if any(digit > 9 for digit in digits):
        return None
    thousands, hundreds, tens, ones = digits
    return (1000 * thousands + 100 * hundreds + 10 * tens + ones) / 10


def decode_temperature(frame: bytes) -> tuple[float | None, float | None] | None:
    """Read the first two channels of a valid TP920 temperature notification."""
    if len(frame) < 18 or frame[:2] != b"\x30\x0f":
        return None
    if (sum(frame[:17]) & 0xFF) != frame[17]:
        return None
    return decode_probe(frame[5:7]), decode_probe(frame[7:9])


@dataclass(frozen=True)
class Reading:
    received_at_ms: int
    received_at_monotonic: float
    probe1_c: float | None
    probe2_c: float | None
    packet_hex: str


class TP920Reader:
    def __init__(self):
        self.state = "searching"
        self.address = None
        self.latest = None

    @property
    def fresh_reading(self) -> Reading | None:
        if self.latest and time.monotonic() - self.latest.received_at_monotonic <= MAX_READING_AGE:
            return self.latest
        return None

    def matches(self, device, advertisement):
        name = advertisement.local_name or device.name
        return name == "TP920" and (self.address is None or device.address == self.address)

    def on_packet(self, _characteristic, value):
        frame = bytes(value)
        temperatures = decode_temperature(frame)
        if temperatures is not None:
            self.latest = Reading(
                time.time_ns() // 1_000_000,
                time.monotonic(),
                *temperatures,
                frame.hex(" "),
            )

    async def read_connection(self, device):
        disconnected = asyncio.Event()
        client = BleakClient(
            device,
            disconnected_callback=lambda _: disconnected.set(),
            services=[SERVICE],
            timeout=8,
        )

        try:
            async with asyncio.timeout(12):
                await client.connect()
            self.address = device.address
            self.state = "waiting"
            logger.info("Connected to the TP920")
            async with asyncio.timeout(8):
                await client.start_notify(NOTIFY, self.on_packet)
                await client.write_gatt_char(COMMAND, START_STREAM, response=True)

            requested = False
            while not disconnected.is_set():
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=3)
                except TimeoutError:
                    if self.fresh_reading is not None:
                        requested = False
                        continue
                    if requested:
                        raise TimeoutError("The TP920 stopped sending temperature packets")
                    async with asyncio.timeout(5):
                        await client.write_gatt_char(COMMAND, REQUEST_TEMPERATURE, response=True)
                    requested = True
        finally:
            self.latest = None
            if client.is_connected:
                async with asyncio.timeout(5):
                    await client.disconnect()

    async def run(self):
        while True:
            self.state = "searching"
            try:
                device = await BleakScanner.find_device_by_filter(
                    self.matches, timeout=8, service_uuids=[SERVICE]
                )
                if device is not None:
                    self.state = "connecting"
                    await self.read_connection(device)
            except (BleakError, OSError, TimeoutError) as error:
                logger.warning("Bluetooth will retry: %s", error)
            finally:
                self.state = "searching"
                self.latest = None
            await asyncio.sleep(2)

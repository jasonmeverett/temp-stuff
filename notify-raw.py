import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bleak import BleakClient

ADDRESS = "AF449CB0-DAF6-5FA8-5A34-3BF49E6213AE"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

TELEMETRY_WRITE_URL = os.environ.get(
    "TELEMETRY_WRITE_URL",
    "https://jm4k4rx1r2.execute-api.us-east-1.amazonaws.com/write",
).strip()
SMOKE_ID = os.environ.get("SMOKE_ID", "smoke-01").strip() or "smoke-01"


def _tenths_f_offset() -> float:
    return float(os.environ.get("NOTIFY_TENTHS_OFFSET_F", "0"))


def _i16_le(blob: bytes) -> int:
    return int.from_bytes(blob, "little", signed=True)


def _u16_le(blob: bytes) -> int:
    return int.from_bytes(blob, "little", signed=False)


def _word(blob: bytes, *, signed: bool, big_endian: bool) -> int:
    return int.from_bytes(blob, "big" if big_endian else "little", signed=signed)


def _four_words_signed(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 2], "little", signed=True) for i in (0, 2, 4, 6)]


def _four_words_unsigned(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 2], "little", signed=False) for i in (0, 2, 4, 6)]


def _probe_word_indices() -> tuple[int, int]:
    """0..3 → byte offsets 0-1, 2-3, 4-5, 6-7."""
    layout = os.environ.get("NOTIFY_LAYOUT", "").strip()
    mapping = {
        "0-2,6-8": (0, 3),
        "0-2,2-4": (0, 1),
        "2-4,4-6": (1, 2),
        "2-4,6-8": (1, 3),
        "4-6,6-8": (2, 3),
        "4-6,2-4": (2, 1),
        "2-4,0-2": (1, 0),
    }
    if layout in mapping:
        return mapping[layout]
    wi = int(os.environ.get("NOTIFY_WORD_INTERNAL", "1"))
    wa = int(os.environ.get("NOTIFY_WORD_AMBIENT", "3"))
    return wi, wa


def _apply_encoding(raw_i: int, raw_a: int) -> tuple[float, float, float, float]:
    enc = os.environ.get("NOTIFY_ENCODING", "f_tenths").strip().lower()
    off = _tenths_f_offset()
    if enc == "f_hundredths":
        internal_f = raw_i / 100.0
        ambient_f = raw_a / 100.0
        internal_c = (internal_f - 32) * 5 / 9
        ambient_c = (ambient_f - 32) * 5 / 9
    elif enc == "c_tenths":
        internal_c = raw_i / 10.0
        ambient_c = raw_a / 10.0
        internal_f = internal_c * 9 / 5 + 32
        ambient_f = ambient_c * 9 / 5 + 32
    elif enc == "c_hundredths":
        internal_c = raw_i / 100.0
        ambient_c = raw_a / 100.0
        internal_f = internal_c * 9 / 5 + 32
        ambient_f = ambient_c * 9 / 5 + 32
    else:  # f_tenths
        internal_f = raw_i / 10.0 + off
        ambient_f = raw_a / 10.0 + off
        internal_c = (internal_f - 32) * 5 / 9
        ambient_c = (ambient_f - 32) * 5 / 9
    return internal_f, ambient_f, internal_c, ambient_c


def _debug_decode_matrix(data: bytes) -> None:
    w = _four_words_signed(data)
    u = _four_words_unsigned(data)
    print(
        f"NOTIFY_DEBUG2  hex={data.hex()}  i16[w0..w3]={w}  u16={u}  "
        f"÷10°F={[round(x / 10, 2) for x in w]}  ÷100°F={[round(x / 100, 3) for x in w]}"
    )


def parse(data: bytes) -> dict[str, float] | None:
    """
    Picks two of the four little-endian int16s as internal / ambient (see below).

    **Defaults:** `NOTIFY_WORD_INTERNAL=1`, `NOTIFY_WORD_AMBIENT=3` (bytes 2–3 and 6–7).
    Word 2 (bytes 4–5) is often battery/status and may not track temperature.

    Set `NOTIFY_LAYOUT=0-2,6-8` etc. to map pairs without thinking in word indices.

    **Scale:** `NOTIFY_ENCODING=f_tenths` (default) → °F = raw/10 + `NOTIFY_TENTHS_OFFSET_F`.
    **Start with offset 0** and use the printed RAW line to see which words move with temp.
    """
    if len(data) != 8:
        return None

    wi, wa = _probe_word_indices()
    if not (0 <= wi <= 3 and 0 <= wa <= 3):
        return None

    b_internal = data[wi * 2 : wi * 2 + 2]
    b_ambient = data[wa * 2 : wa * 2 + 2]

    enc_preview = os.environ.get("NOTIFY_ENCODING", "f_tenths").strip().lower()
    big_endian = os.environ.get("NOTIFY_ENDIAN", "").lower() in (
        "be",
        "big",
        "big-endian",
    )
    use_u16_hundredths_f = (
        enc_preview == "f_hundredths"
        and os.environ.get("NOTIFY_F_HUNDREDTHS_UNSIGNED")
    )
    raw_internal = _word(
        b_internal,
        signed=not use_u16_hundredths_f,
        big_endian=big_endian,
    )
    raw_ambient = _word(
        b_ambient,
        signed=not use_u16_hundredths_f,
        big_endian=big_endian,
    )

    if os.environ.get("NOTIFY_SWAP"):
        raw_internal, raw_ambient = raw_ambient, raw_internal

    if os.environ.get("NOTIFY_DEBUG") == "2":
        _debug_decode_matrix(data)
    elif os.environ.get("NOTIFY_DEBUG"):
        print(
            f"NOTIFY_DEBUG words=({wi},{wa}) enc={enc_preview} "
            f"raw_i={raw_internal} raw_a={raw_ambient}"
        )

    internal_f, ambient_f, internal_c, ambient_c = _apply_encoding(
        raw_internal, raw_ambient
    )

    return {
        "internal_c": internal_c,
        "internal_f": internal_f,
        "ambient_c": ambient_c,
        "ambient_f": ambient_f,
    }


def _format_raw_line(data: bytes) -> str:
    w = _four_words_signed(data)
    u = _four_words_unsigned(data)
    t = [round(x / 10.0, 2) for x in w]
    h = [round(x / 100.0, 3) for x in w]
    return (
        f"RAW hex={data.hex()} | i16[w0..w3]={w} | u16[w0..w3]={u} | "
        f"÷10°F={t} | ÷100°F={h} (no offset; see NOTIFY_TENTHS_OFFSET_F)"
    )


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
        print(_format_raw_line(data))

    wi, wa = _probe_word_indices()
    print(
        f"Internal: {parsed['internal_f']:.1f}°F "
        f"({parsed['internal_c']:.1f}°C) | "
        f"Ambient: {parsed['ambient_f']:.1f}°F "
        f"({parsed['ambient_c']:.1f}°C) "
        f"[w{wi},w{wa} · {os.environ.get('NOTIFY_ENCODING', 'f_tenths')} · "
        f"offset {_tenths_f_offset()}]"
    )
    _post_write(parsed["internal_f"], parsed["ambient_f"])


async def run():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)
        wi, wa = _probe_word_indices()
        print(
            "Each packet prints RAW (all 4× int16) then Internal/Ambient from "
            f"word indices {wi},{wa}. Change with NOTIFY_WORD_INTERNAL / "
            "NOTIFY_WORD_AMBIENT or NOTIFY_LAYOUT. NOTIFY_QUIET_RAW=1 hides hex line."
        )

        await client.start_notify(NOTIFY_UUID, handle)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await client.stop_notify(NOTIFY_UUID)


asyncio.run(run())

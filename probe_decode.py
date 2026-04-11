"""8-byte FF01 notify → internal / ambient °F (and derived °C).

**Default (`NOTIFY_PARSE=smoker` or unset):** empirically fit from labeled app vs raw hex
(comparisons file). Uses little-endian int16 at byte offsets 2 and 6 (words w1, w3).

**Other modes:** `NOTIFY_PARSE=legacy` (old tenths-°C guess), `byte_sum`, `f_tenths`, etc.

`format_raw_line` prints **hex** and **all four int16 words** plus smoker preview when default.
"""

from __future__ import annotations

import os
from typing import Callable

# Labeled ground truth: (notify hex, internal °F, ambient °F) — app is truth.
COMPARISON_SAMPLES: list[tuple[str, int, int]] = [
    ("100029002c0a2d00", 53, 61),
    ("100037002c0a3700", 79, 79),
    ("10001300c0091300", 12, 12),
    ("100034002c0a3800", 72, 79),
    ("10006400190a8e00", 158, 237),
    # App showed "386" (tenths °F) → 38.6°F ≈ 39°F; w3=224 breaks hi-line extrapolation.
    ("100035006c0ae000", 75, 39),
]


def byte_sum_offset() -> float:
    return float(os.environ.get("NOTIFY_BYTE_SUM_OFFSET", "0"))


def _c_from_f(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _f_from_c(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _i16_le(data: bytes, off: int) -> int:
    return int.from_bytes(data[off : off + 2], "little", signed=True)


def _four_i16_le(data: bytes) -> tuple[int, int, int, int]:
    return (
        _i16_le(data, 0),
        _i16_le(data, 2),
        _i16_le(data, 4),
        _i16_le(data, 6),
    )


def _fit_internal_linear_from_comparisons() -> tuple[float, float]:
    """Least-squares °F vs probe word w1 (fits low + high heat; see COMPARISON_SAMPLES)."""
    xs: list[int] = []
    ys: list[float] = []
    for hx, ti, _ in COMPARISON_SAMPLES:
        blob = bytes.fromhex(hx)
        xs.append(_i16_le(blob, 2))
        ys.append(float(ti))
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    var_x = sum((x - mx) ** 2 for x in xs)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if var_x <= 0:
        return 9.0 / 5.0, -22.0
    m = cov / var_x
    b = my - m * mx
    return m, b


def _refine_internal_intercept_for_rounding(m: float, b_ls: float) -> float:
    """Nudge intercept so round(w1*m+b) minimizes max |error|, then SSE (ties)."""
    xs = [_i16_le(bytes.fromhex(hx), 2) for hx, _, _ in COMPARISON_SAMPLES]
    ys = [ti for hx, ti, _ in COMPARISON_SAMPLES]

    def metrics(b: float) -> tuple[int, float]:
        preds = [round(x * m + b) for x in xs]
        me = max(abs(p - y) for p, y in zip(preds, ys))
        sse = sum((p - y) ** 2 for p, y in zip(preds, ys))
        return me, sse

    best_key = (10**9, 10**9)
    best_b = b_ls
    for i in range(-600, 601):
        b = b_ls + i * 0.005
        key = metrics(b)
        if key < best_key:
            best_key = key
            best_b = b
    return best_b


_ls_m, _ls_b = _fit_internal_linear_from_comparisons()
_INTERNAL_SLOPE = _ls_m
_INTERNAL_INTERCEPT = _refine_internal_intercept_for_rounding(_ls_m, _ls_b)

# Ambient: cold/mid branches, then (56→79)→(142→237); above 142, second segment (142→237)→(224→39°F)
# from labeled sample (386 tenths in app).
_AMB_STITCH_W, _AMB_STITCH_F = 56, 79
_AMB_HI_ANCHOR_W, _AMB_HI_ANCHOR_F = 142, 237
_AMB_HI_SLOPE = (_AMB_HI_ANCHOR_F - _AMB_STITCH_F) / (_AMB_HI_ANCHOR_W - _AMB_STITCH_W)
_AMB_COOL_W, _AMB_COOL_F = 224, 39
_AMB_POST142_SLOPE = (_AMB_COOL_F - _AMB_HI_ANCHOR_F) / (_AMB_COOL_W - _AMB_HI_ANCHOR_W)


def _pack(
    internal_f: float, ambient_f: float
) -> dict[str, float]:
    internal_c = _c_from_f(internal_f)
    ambient_c = _c_from_f(ambient_f)
    return {
        "internal_c": internal_c,
        "internal_f": float(internal_f),
        "ambient_c": ambient_c,
        "ambient_f": float(ambient_f),
    }


def parse1_legacy_c_tenths(data: bytes) -> dict[str, float] | None:
    """Original guess: i16 @ 2–3 & 6–7 are tenths °C → convert to °F."""
    if len(data) != 8:
        return None
    internal_c = _i16_le(data, 2) / 10.0
    ambient_c = _i16_le(data, 6) / 10.0
    return _pack(_f_from_c(internal_c), _f_from_c(ambient_c))


def parse2_byte_sum_f(data: bytes) -> dict[str, float] | None:
    """Legacy single-byte sums: °F = b0+b2+off, b0+b6+off (NOTIFY_BYTE_SUM_OFFSET)."""
    if len(data) != 8:
        return None
    off = byte_sum_offset()
    internal_f = float(data[0]) + float(data[2]) + off
    ambient_f = float(data[0]) + float(data[6]) + off
    return _pack(internal_f, ambient_f)


def parse3_i16_as_tenths_f(data: bytes) -> dict[str, float] | None:
    """Treat words w1 & w3 as tenths °F (÷10), no extra conversion."""
    if len(data) != 8:
        return None
    internal_f = _i16_le(data, 2) / 10.0
    ambient_f = _i16_le(data, 6) / 10.0
    return _pack(internal_f, ambient_f)


def parse4_i16_c_hundredths(data: bytes) -> dict[str, float] | None:
    """i16 @ 2–3 & 6–7 as hundredths °C (÷100) → °F."""
    if len(data) != 8:
        return None
    internal_c = _i16_le(data, 2) / 100.0
    ambient_c = _i16_le(data, 6) / 100.0
    return _pack(_f_from_c(internal_c), _f_from_c(ambient_c))


def _internal_f_smoker_ls(w1: int) -> int:
    """Integer °F from w1 — linear LS on COMPARISON_SAMPLES (typically ±1 °F)."""
    return int(round(w1 * _INTERNAL_SLOPE + _INTERNAL_INTERCEPT))


def _ambient_f_smoker_piecewise(w3: int) -> int:
    """°F from w3 — cold/mid branches; [56,142] hot line; >142 descending line to (224,39)."""
    if w3 <= 20:
        return (9 * w3 - 110) // 5
    if w3 < _AMB_STITCH_W:
        return (9 * w3 - 100) // 5
    if w3 <= _AMB_HI_ANCHOR_W:
        return int(round(_AMB_STITCH_F + (w3 - _AMB_STITCH_W) * _AMB_HI_SLOPE))
    # Past grill-hot anchor w3=142, raw w3 can rise while ambient drops (labeled w3=224→39°F).
    amb = _AMB_HI_ANCHOR_F + (w3 - _AMB_HI_ANCHOR_W) * _AMB_POST142_SLOPE
    return int(round(max(32.0, amb)))


def parse5_smoker_fit(data: bytes) -> dict[str, float] | None:
    """Empirical fit vs app: LS internal on w1 + piecewise/linear ambient on w3."""
    if len(data) != 8:
        return None
    _w0, w1, _w2, w3 = _four_i16_le(data)
    internal_f = _internal_f_smoker_ls(w1)
    ambient_f = _ambient_f_smoker_piecewise(w3)
    return _pack(internal_f, ambient_f)


def parse6_byte_b2_b6_direct_f(data: bytes) -> dict[str, float] | None:
    """Hypothesis: low byte b2 / b6 are whole °F (ignoring high bytes)."""
    if len(data) != 8:
        return None
    return _pack(float(data[2]), float(data[6]))


def parse7_linear_float_least_squares(data: bytes) -> dict[str, float] | None:
    """Same words as smoker; internal F = 1.571*w1 - 11.57, ambient F = 1.8*w3 - 20 (rough LS)."""
    if len(data) != 8:
        return None
    _w0, w1, _w2, w3 = _four_i16_le(data)
    internal_f = 1.571428 * w1 - 11.571428
    ambient_f = 1.8 * w3 - 20.0
    return _pack(internal_f, ambient_f)


_PARSE_FUNCS: dict[str, Callable[[bytes], dict[str, float] | None]] = {
    # User-friendly names
    "legacy": parse1_legacy_c_tenths,
    "c_tenths": parse1_legacy_c_tenths,
    "byte_sum": parse2_byte_sum_f,
    "f_tenths": parse3_i16_as_tenths_f,
    "c_hundredths": parse4_i16_c_hundredths,
    "smoker": parse5_smoker_fit,
    "b2_b6_u8": parse6_byte_b2_b6_direct_f,
    "linear_float": parse7_linear_float_least_squares,
    # Aliases
    "1": parse1_legacy_c_tenths,
    "2": parse2_byte_sum_f,
    "3": parse3_i16_as_tenths_f,
    "4": parse4_i16_c_hundredths,
    "5": parse5_smoker_fit,
    "6": parse6_byte_b2_b6_direct_f,
    "7": parse7_linear_float_least_squares,
    "parse1": parse1_legacy_c_tenths,
    "parse2": parse2_byte_sum_f,
    "parse3": parse3_i16_as_tenths_f,
    "parse4": parse4_i16_c_hundredths,
    "parse5": parse5_smoker_fit,
    "parse6": parse6_byte_b2_b6_direct_f,
    "parse7": parse7_linear_float_least_squares,
}


_DEFAULT_PARSE_MODE = "smoker"


def parse(data: bytes) -> dict[str, float] | None:
    """
    Decode notify payload. Mode from NOTIFY_PARSE (default `smoker`).

    NOTIFY_DECODE=byte_sum still forces byte-sum mode for backward compatibility.
    """
    if len(data) != 8:
        return None

    if os.environ.get("NOTIFY_DECODE", "").strip().lower() in (
        "byte_sum",
        "byte_sum_f",
        "legacy",
    ):
        return parse2_byte_sum_f(data)

    mode = os.environ.get("NOTIFY_PARSE", _DEFAULT_PARSE_MODE).strip().lower()
    fn = _PARSE_FUNCS.get(mode, parse5_smoker_fit)
    return fn(data)


def decode_mode_label() -> str:
    if os.environ.get("NOTIFY_DECODE", "").strip().lower() in (
        "byte_sum",
        "byte_sum_f",
        "legacy",
    ):
        return f"FORCED byte_sum °F: b0+b2+{byte_sum_offset()}, b0+b6+{byte_sum_offset()} (NOTIFY_DECODE)"
    mode = os.environ.get("NOTIFY_PARSE", _DEFAULT_PARSE_MODE).strip().lower()
    labels = {
        "legacy": "parse1 legacy: i16 LE ÷10 → °C @ 2–3 & 6–7",
        "c_tenths": "parse1 legacy: i16 LE ÷10 → °C @ 2–3 & 6–7",
        "byte_sum": "parse2 byte_sum °F",
        "f_tenths": "parse3 i16 ÷10 as °F",
        "c_hundredths": "parse4 i16 ÷100 → °C",
        "smoker": (
            f"parse5 smoker: internal round(w1*{ _INTERNAL_SLOPE:.4f}"
            f"{_INTERNAL_INTERCEPT:+.3f}), ambient piecewise + high line "
            f"({_AMB_STITCH_W}→{_AMB_STITCH_F} .. {_AMB_HI_ANCHOR_W}→{_AMB_HI_ANCHOR_F}°F"
            f" .. {_AMB_COOL_W}→{_AMB_COOL_F}°F)"
        ),
        "b2_b6_u8": "parse6 low bytes b2,b6 as °F",
        "linear_float": "parse7 crude LS floats on w1,w3",
    }
    return labels.get(mode, f"{mode}: custom NOTIFY_PARSE")


def format_raw_line(data: bytes) -> str:
    if len(data) != 8:
        return f"RAW hex={data.hex()} (expected 8 bytes)"
    w0, w1, w2, w3 = _four_i16_le(data)
    off = byte_sum_offset()
    sum_i = data[0] + data[2] + off
    sum_a = data[0] + data[6] + off
    ci, ca = w1 / 10.0, w3 / 10.0
    fi, fa = _f_from_c(ci), _f_from_c(ca)
    smoker = parse5_smoker_fit(data)
    sm_i = smoker["internal_f"] if smoker else float("nan")
    sm_a = smoker["ambient_f"] if smoker else float("nan")
    return (
        f"RAW hex={data.hex()} | i16[w0,w1,w2,w3]=[{w0},{w1},{w2},{w3}] | "
        f"legacy÷10°C → {ci:.1f}°C / {fi:.1f}°F (int), {ca:.1f}°C / {fa:.1f}°F (amb) | "
        f"byte sums b0+b2+off={sum_i}, b0+b6+off={sum_a} (off={off}) | "
        f"smoker_fit → {sm_i:.0f}/{sm_a:.0f}°F"
    )


def _compare_parser(
    name: str, fn: Callable[[bytes], dict[str, float] | None]
) -> tuple[float, float, int]:
    """Returns (max internal abs err, max ambient abs err, count failed)."""
    max_i = 0.0
    max_a = 0.0
    failed = 0
    for hx, ti, ta in COMPARISON_SAMPLES:
        p = fn(bytes.fromhex(hx))
        if not p:
            failed += 1
            continue
        max_i = max(max_i, abs(p["internal_f"] - ti))
        max_a = max(max_a, abs(p["ambient_f"] - ta))
    return max_i, max_a, failed


def compare_all_parsers() -> None:
    print("Parser fit vs COMPARISON_SAMPLES (app °F truth):\n")
    order = [
        ("parse5 smoker (default)", parse5_smoker_fit),
        ("parse1 legacy c_tenths", parse1_legacy_c_tenths),
        ("parse2 byte_sum", parse2_byte_sum_f),
        ("parse3 f_tenths", parse3_i16_as_tenths_f),
        ("parse4 c_hundredths", parse4_i16_c_hundredths),
        ("parse6 b2_b6_u8", parse6_byte_b2_b6_direct_f),
        ("parse7 linear_float", parse7_linear_float_least_squares),
    ]
    for label, fn in order:
        mi, ma, fail = _compare_parser(label, fn)
        print(f"  {label}: max|Δ| int={mi:.2f} amb={ma:.2f}F fails={fail}")
    print("\nPer-sample (smoker):")
    for hx, ti, ta in COMPARISON_SAMPLES:
        p = parse5_smoker_fit(bytes.fromhex(hx))
        assert p is not None
        print(
            f"  {hx} app {ti}/{ta}°F → code {p['internal_f']:.0f}/{p['ambient_f']:.0f}°F "
            f"(Δ {p['internal_f'] - ti:+.0f} / {p['ambient_f'] - ta:+.0f})"
        )


def _self_test() -> None:
    sample = bytes.fromhex("10003200450a3200")
    print(format_raw_line(sample))
    p = parse(sample)
    assert p is not None
    print(f"default parse: internal {p['internal_f']:.1f}°F, ambient {p['ambient_f']:.1f}°F")


if __name__ == "__main__":
    compare_all_parsers()
    print()
    _self_test()

"""MQTT helpers for Zigbee2MQTT IR emitters."""

from __future__ import annotations

import base64
import json
import struct
from typing import Iterable
from typing import Any

from .const import DEFAULT_BASE_TOPIC


def build_topic(
    friendly_name: str,
    base_topic: str = DEFAULT_BASE_TOPIC,
) -> str:
    """Build the Zigbee2MQTT set topic for device commands."""

    return f"{base_topic}/{friendly_name}/set"


def build_payload(code: Any) -> str:
    """Build a Zigbee2MQTT payload for the Tuya/Z2M IR send property."""

    return json.dumps({"ir_code_to_send": command_to_z2m_code(code)})


def build_learning_payload(enabled: bool = True) -> str:
    """Build a Zigbee2MQTT payload that toggles learning mode."""

    return json.dumps({"learn_ir_code": "ON" if enabled else "OFF"})


def command_to_z2m_code(command: Any) -> str:
    """Convert a Home Assistant infrared command or raw value to a Z2M code."""

    if isinstance(command, bytes):
        return command.decode()

    if isinstance(command, str):
        return command

    raw_timings = getattr(command, "get_raw_timings", None)
    if callable(raw_timings):
        return encode_tuya_ir(_flatten_raw_timings(raw_timings()))

    return extract_ir_code(str(command))


def extract_ir_code(value: str) -> str:
    """Normalize a possibly wrapped payload to the raw Tuya IR code string."""

    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return value

    if isinstance(payload, dict) and isinstance(payload.get("ir_code_to_send"), str):
        return payload["ir_code_to_send"]

    return value


def convert_broadlink_to_tuya(command: str) -> str:
    """Convert a Broadlink base64 command to a Tuya raw code."""

    return encode_tuya_ir(list(decode_broadlink_base64(command)))


def decode_broadlink_base64(data: str) -> Iterable[int]:
    """Decode a Broadlink base64 string to raw IR timings."""

    yield from decode_broadlink(base64.b64decode(data))


def decode_broadlink(data: bytes) -> Iterable[int]:
    """Decode the Broadlink binary payload to raw microsecond timings."""

    values = iter(data)
    code = next(values)
    next(values)  # repeat byte

    if code == 0xB2:
        raise ValueError(
            "This SmartIR file contains Broadlink RF payloads. "
            "OtterIR and the TS1201/UFO-R11 only support IR commands."
        )

    if code != 0x26:
        raise ValueError(
            f"Unsupported Broadlink payload type 0x{code:02X}; only IR payloads can be imported"
        )

    length = int.from_bytes(bytes([next(values), next(values)]), byteorder="little")
    if length < 3:
        raise ValueError("Broadlink payload is too short")

    remaining = data[4 : 4 + length]
    index = 0
    while index < len(remaining):
        duration = remaining[index]
        index += 1
        if duration == 0:
            if index + 1 >= len(remaining):
                break
            duration = int.from_bytes(remaining[index : index + 2], byteorder="big")
            index += 2

        micros = int(round(duration * 8192 / 269, 0))
        if micros > 65535:
            break
        yield micros


def encode_tuya_ir(timings: list[int]) -> str:
    """Encode raw IR timings to the Tuya base64 format used by ZS06."""

    payload = b"".join(
        struct.pack("<H", min(max(int(timing), 0), 65535)) for timing in timings
    )
    return base64.b64encode(_encode_fastlz_literal_blocks(payload)).decode("ascii")


def _flatten_raw_timings(raw_timings: Any) -> list[int]:
    """Flatten Home Assistant infrared timings to alternating positive durations."""

    timings: list[int] = []
    for timing in raw_timings:
        if isinstance(timing, int):
            timings.append(abs(timing))
            continue

        if isinstance(timing, (tuple, list)):
            timings.extend(abs(int(value)) for value in timing)
            continue

        high_us = getattr(timing, "high_us", None)
        low_us = getattr(timing, "low_us", None)
        if high_us is not None:
            timings.append(abs(int(high_us)))
        if low_us is not None:
            timings.append(abs(int(low_us)))

    return timings


def _encode_fastlz_literal_blocks(payload: bytes) -> bytes:
    """Encode a FastLZ-compatible stream using only literal blocks."""

    blocks = bytearray()
    for index in range(0, len(payload), 32):
        chunk = payload[index : index + 32]
        blocks.append(len(chunk) - 1)
        blocks.extend(chunk)
    return bytes(blocks)

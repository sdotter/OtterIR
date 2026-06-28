"""Import helpers for structured IR command lists."""

from __future__ import annotations

import csv
from io import StringIO
import re

from homeassistant.exceptions import HomeAssistantError

from .mqtt_helpers import encode_tuya_ir

HEX_CODE_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def parse_command_list_text(text: str) -> list[tuple[str, str]]:
    """Parse a CSV/TSV command list into name/code pairs."""

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise HomeAssistantError("The CSV/TSV source is empty")

    header_index, delimiter = _find_header_row(lines)
    if delimiter is None or header_index is None:
        raise HomeAssistantError(
            "CSV/TSV import expects a header row with at least 'Code' and 'Function' columns"
        )

    reader = csv.DictReader(StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    commands: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for row in reader:
        normalized = {
            str(key).strip().lower(): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        code = normalized.get("code", "").replace("`", "").strip().upper()
        name = _cleanup_name(normalized.get("function", ""))
        if not HEX_CODE_RE.fullmatch(code) or not name:
            continue

        key = (name.lower(), code)
        if key in seen:
            continue
        seen.add(key)
        commands.append((name, code))

    if not commands:
        raise HomeAssistantError(
            "No importable commands were found. Check that the file has valid 8-digit NEC codes."
        )

    return commands


def nec_to_tuya(code: str) -> str:
    """Convert an 8-hex-digit NEC code to Tuya raw base64."""

    code = code.strip().upper()
    if not HEX_CODE_RE.fullmatch(code):
        raise HomeAssistantError(f"Unsupported NEC code '{code}'")

    payload = bytes.fromhex(code)
    timings = [9000, 4500]
    for byte in payload:
        for bit_index in range(8):
            bit = (byte >> bit_index) & 1
            timings.append(560)
            timings.append(1690 if bit else 560)
    timings.append(560)
    return encode_tuya_ir(timings)


def _find_header_row(lines: list[str]) -> tuple[int | None, str | None]:
    """Return the first supported header row and its delimiter."""

    for index, line in enumerate(lines):
        for candidate in ("\t", ",", ";"):
            parts = [part.strip().strip("`").lower() for part in line.split(candidate)]
            if "code" in parts and "function" in parts:
                return index, candidate
    return None, None


def _cleanup_name(value: str) -> str:
    """Normalize a parsed command name."""

    return re.sub(r"\s+", " ", value).strip(" -|:")

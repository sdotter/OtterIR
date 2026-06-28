"""Helpers for importing Flipper IR catalogs and remotes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlparse

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

from .const import ATTR_CODE, ATTR_ENCODING, ATTR_NAME, ENCODING_TUYA_RAW
from .library import slugify, utcnow_iso
from .list_import import nec_to_tuya
from .mqtt_helpers import encode_tuya_ir

GITHUB_API_ROOT = "https://api.github.com"
GITHUB_RAW_ROOT = "https://raw.githubusercontent.com"
REMOTE_SOURCE_RE = re.compile(r"^https?://", re.IGNORECASE)
HEX_BYTE_RE = re.compile(r"^[0-9A-Fa-f]{2}$")


async def async_import_flipper_source(
    hass: HomeAssistant,
    source: str,
    *,
    source_name: str | None = None,
    max_files: int = 200,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Import a Flipper catalog source from a file, directory, or GitHub path."""

    cleaned = str(source).strip()
    if not cleaned:
        raise HomeAssistantError("A Flipper source is required")

    max_files = min(max(int(max_files), 1), 1000)

    github_spec = _parse_github_source(cleaned)
    if github_spec is not None:
        return await _async_import_github_source(
            hass,
            github_spec,
            source_name=source_name,
            max_files=max_files,
        )

    local_path = _resolve_local_path(cleaned)
    if local_path.is_dir():
        return await hass.async_add_executor_job(
            _import_local_directory,
            local_path,
            source_name,
            max_files,
        )

    if local_path.is_file():
        text = await hass.async_add_executor_job(local_path.read_text, "utf-8")
        remote = _build_remote_record(
            text,
            source_key=_stable_source_key("flipper_file", str(local_path)),
            source_name=source_name or _default_source_name_from_path(local_path),
            relative_path=local_path.name,
            origin_url=str(local_path),
            origin_kind="local_file",
        )
        source_record = _build_source_record(
            source_key=remote["source_key"],
            source_name=source_name or _default_source_name_from_path(local_path),
            origin_kind="local_file",
            source=str(local_path),
            remote_count=1,
            truncated=False,
        )
        return source_record, [remote]

    if REMOTE_SOURCE_RE.match(cleaned):
        text = await _async_download_text(hass, cleaned)
        remote = _build_remote_record(
            text,
            source_key=_stable_source_key("flipper_url", cleaned),
            source_name=source_name or _default_source_name_from_url(cleaned),
            relative_path=PurePosixPath(urlparse(cleaned).path).name or "remote.ir",
            origin_url=cleaned,
            origin_kind="remote_file",
        )
        source_record = _build_source_record(
            source_key=remote["source_key"],
            source_name=source_name or _default_source_name_from_url(cleaned),
            origin_kind="remote_file",
            source=cleaned,
            remote_count=1,
            truncated=False,
        )
        return source_record, [remote]

    raise HomeAssistantError(
        "Unsupported Flipper source. Use a GitHub tree/blob URL, a raw .ir URL, or a local /config path."
    )


def iter_supported_catalog_commands(remote_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the supported commands from a stored catalog remote."""

    commands = remote_record.get("commands") or []
    return [
        command
        for command in commands
        if isinstance(command, dict)
        and command.get("supported")
        and isinstance(command.get(ATTR_CODE), str)
    ]


def preview_command_names(remote_record: dict[str, Any], limit: int = 8) -> list[str]:
    """Return a short preview list of command names."""

    names: list[str] = []
    for command in remote_record.get("commands") or []:
        if not isinstance(command, dict):
            continue
        name = str(command.get(ATTR_NAME, "")).strip()
        if not name:
            continue
        names.append(name)
        if len(names) >= limit:
            break
    return names


async def _async_import_github_source(
    hass: HomeAssistant,
    github_spec: dict[str, Any],
    *,
    source_name: str | None,
    max_files: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Import a GitHub-hosted Flipper source."""

    owner = github_spec["owner"]
    repo = github_spec["repo"]
    branch = github_spec["branch"] or await _async_fetch_default_branch(
        hass, owner, repo
    )
    path = github_spec["path"]
    source_key = _stable_source_key(
        "flipper_github",
        f"{owner}/{repo}@{branch}:{path}",
    )
    display_name = source_name or _default_github_source_name(owner, repo, path)

    if github_spec["mode"] == "file" or path.lower().endswith(".ir"):
        text = await _async_download_text(
            hass,
            _github_raw_url(owner, repo, branch, path),
        )
        remote = _build_remote_record(
            text,
            source_key=source_key,
            source_name=display_name,
            relative_path=path or "remote.ir",
            origin_url=github_spec["source"],
            origin_kind="github_file",
        )
        source_record = _build_source_record(
            source_key=source_key,
            source_name=display_name,
            origin_kind="github_file",
            source=github_spec["source"],
            remote_count=1,
            truncated=False,
        )
        return source_record, [remote]

    files = await _async_list_github_ir_files(
        hass,
        owner=owner,
        repo=repo,
        branch=branch,
        prefix=path,
        max_files=max_files,
    )
    if not files:
        raise HomeAssistantError("No Flipper .ir files were found at that GitHub path")

    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(8)

    async def load_file(relative_path: str) -> dict[str, Any]:
        async with semaphore:
            text = await _async_download_text(
                hass,
                _github_raw_url(owner, repo, branch, relative_path),
                session=session,
            )
        return _build_remote_record(
            text,
            source_key=source_key,
            source_name=display_name,
            relative_path=relative_path,
            origin_url=_github_blob_url(owner, repo, branch, relative_path),
            origin_kind="github_tree",
        )

    remotes = await asyncio.gather(*(load_file(path_item) for path_item in files["files"]))
    source_record = _build_source_record(
        source_key=source_key,
        source_name=display_name,
        origin_kind="github_tree",
        source=github_spec["source"],
        remote_count=len(remotes),
        truncated=files["truncated"],
        metadata={
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "path": path,
        },
    )
    return source_record, remotes


async def _async_fetch_default_branch(
    hass: HomeAssistant,
    owner: str,
    repo: str,
) -> str:
    """Return the default branch for a public GitHub repository."""

    payload = await _async_download_json(
        hass,
        f"{GITHUB_API_ROOT}/repos/{owner}/{repo}",
    )
    default_branch = str(payload.get("default_branch", "")).strip()
    if not default_branch:
        raise HomeAssistantError("Unable to determine the GitHub default branch")
    return default_branch


async def _async_list_github_ir_files(
    hass: HomeAssistant,
    *,
    owner: str,
    repo: str,
    branch: str,
    prefix: str,
    max_files: int,
) -> dict[str, Any]:
    """Return .ir files from a GitHub repository tree."""

    branch_payload = await _async_download_json(
        hass,
        f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/branches/{branch}",
    )
    tree_sha = (
        branch_payload.get("commit", {})
        .get("commit", {})
        .get("tree", {})
        .get("sha")
    )
    if not isinstance(tree_sha, str) or not tree_sha:
        raise HomeAssistantError("Unable to resolve the GitHub tree for that branch")

    tree_payload = await _async_download_json(
        hass,
        f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1",
    )
    entries = tree_payload.get("tree", [])
    if not isinstance(entries, list):
        raise HomeAssistantError("Unexpected GitHub tree response")

    normalized_prefix = prefix.strip("/").lower()
    matched_files: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        path = str(entry.get("path", "")).strip()
        if not path.lower().endswith(".ir"):
            continue
        if normalized_prefix and not path.lower().startswith(normalized_prefix + "/"):
            continue
        matched_files.append(path)

    matched_files.sort()
    truncated = len(matched_files) > max_files
    return {
        "files": matched_files[:max_files],
        "truncated": truncated,
    }


async def _async_download_text(
    hass: HomeAssistant,
    url: str,
    *,
    session=None,
) -> str:
    """Download plain text from a remote URL."""

    session = session or async_get_clientsession(hass)
    headers = {"Accept": "application/vnd.github+json"}
    async with session.get(url, headers=headers) as response:
        if response.status >= 400:
            raise HomeAssistantError(
                f"Unable to download Flipper source ({response.status})"
            )
        return await response.text()


async def _async_download_json(hass: HomeAssistant, url: str) -> dict[str, Any]:
    """Download a JSON document."""

    text = await _async_download_text(hass, url)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise HomeAssistantError("The remote response did not contain valid JSON") from err
    if not isinstance(payload, dict):
        raise HomeAssistantError("The remote response was not a JSON object")
    return payload


def _import_local_directory(
    directory: Path,
    source_name: str | None,
    max_files: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Import a local directory of Flipper .ir files."""

    source_key = _stable_source_key("flipper_dir", str(directory))
    display_name = source_name or _default_source_name_from_path(directory)

    file_paths = sorted(path for path in directory.rglob("*.ir") if path.is_file())
    if not file_paths:
        raise HomeAssistantError("No Flipper .ir files were found in that directory")

    truncated = len(file_paths) > max_files
    selected_paths = file_paths[:max_files]
    remotes = [
        _build_remote_record(
            path.read_text(encoding="utf-8"),
            source_key=source_key,
            source_name=display_name,
            relative_path=path.relative_to(directory).as_posix(),
            origin_url=str(path),
            origin_kind="local_directory",
        )
        for path in selected_paths
    ]
    source_record = _build_source_record(
        source_key=source_key,
        source_name=display_name,
        origin_kind="local_directory",
        source=str(directory),
        remote_count=len(remotes),
        truncated=truncated,
    )
    return source_record, remotes


def _resolve_local_path(source: str) -> Path:
    """Resolve a local path and keep it inside /config."""

    if REMOTE_SOURCE_RE.match(source):
        return Path("")

    config_root = Path("/config").resolve()
    path = Path(source)
    if not path.is_absolute():
        path = config_root / path
    resolved = path.resolve()
    if resolved != config_root and config_root not in resolved.parents:
        raise HomeAssistantError("Flipper imports must stay inside /config")
    return resolved


def _build_remote_record(
    text: str,
    *,
    source_key: str,
    source_name: str,
    relative_path: str,
    origin_url: str,
    origin_kind: str,
) -> dict[str, Any]:
    """Build a catalog remote record from Flipper .ir text."""

    commands = _parse_flipper_ir_commands(text)
    if not commands:
        raise HomeAssistantError(f"No commands were found in Flipper file '{relative_path}'")

    relative = PurePosixPath(relative_path)
    category, brand, model = _meta_from_relative_path(relative)
    remote_id = _stable_source_key(source_key, relative.as_posix())
    supported_count = sum(1 for command in commands if command.get("supported"))
    now = utcnow_iso()

    return {
        "remote_id": remote_id,
        "source_key": source_key,
        "source_name": source_name,
        "origin_kind": origin_kind,
        "origin_url": origin_url,
        "relative_path": relative.as_posix(),
        "category": category,
        "brand": brand,
        "model": model,
        "display_name": model.replace("_", " "),
        "manufacturer": brand or None,
        "device_type": _device_type_from_category(category),
        "library_hint": slugify(model),
        "command_count": len(commands),
        "supported_command_count": supported_count,
        "unsupported_command_count": len(commands) - supported_count,
        "preview_commands": [command[ATTR_NAME] for command in commands[:8]],
        "commands": commands,
        "updated_at": now,
    }


def _build_source_record(
    *,
    source_key: str,
    source_name: str,
    origin_kind: str,
    source: str,
    remote_count: int,
    truncated: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a catalog source record."""

    now = utcnow_iso()
    return {
        "source_key": source_key,
        "source_name": source_name,
        "origin_kind": origin_kind,
        "source": source,
        "remote_count": remote_count,
        "truncated": truncated,
        "metadata": metadata or {},
        "updated_at": now,
    }


def _parse_flipper_ir_commands(text: str) -> list[dict[str, Any]]:
    """Parse commands from a Flipper .ir file."""

    commands: list[dict[str, Any]] = []
    current: dict[str, str] = {}

    def finish_current() -> None:
        if current.get("name"):
            commands.append(_normalize_flipper_command(current))
        current.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "#":
            continue
        if line.startswith("Filetype:") or line.startswith("Version:"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key == "name" and current.get("name"):
            finish_current()
        current[normalized_key] = normalized_value

    finish_current()
    return commands


def _normalize_flipper_command(command_data: dict[str, str]) -> dict[str, Any]:
    """Normalize a parsed Flipper command."""

    name = str(command_data.get("name", "Unnamed")).strip() or "Unnamed"
    entry_type = str(command_data.get("type", "")).strip().lower()

    normalized: dict[str, Any] = {
        ATTR_NAME: name,
        "entry_type": entry_type or "unknown",
        "protocol": None,
        ATTR_ENCODING: None,
        ATTR_CODE: None,
        "supported": False,
    }

    if entry_type == "raw":
        data = _parse_raw_timings(command_data.get("data", ""))
        if data:
            normalized[ATTR_CODE] = encode_tuya_ir(data)
            normalized[ATTR_ENCODING] = ENCODING_TUYA_RAW
            normalized["supported"] = True
        normalized["frequency"] = _safe_int(command_data.get("frequency"))
        normalized["duty_cycle"] = command_data.get("duty_cycle")
        return normalized

    if entry_type == "parsed":
        protocol = str(command_data.get("protocol", "")).strip().upper()
        normalized["protocol"] = protocol or None
        code = _convert_parsed_flipper_command(
            protocol,
            command_data.get("address", ""),
            command_data.get("command", ""),
        )
        if code is not None:
            normalized[ATTR_CODE] = code
            normalized[ATTR_ENCODING] = ENCODING_TUYA_RAW
            normalized["supported"] = True
        return normalized

    return normalized


def _convert_parsed_flipper_command(
    protocol: str,
    address_text: str,
    command_text: str,
) -> str | None:
    """Convert a parsed Flipper command to Tuya raw when supported."""

    address_bytes = _parse_hex_bytes(address_text)
    command_bytes = _parse_hex_bytes(command_text)

    if protocol == "NEC":
        if not address_bytes or not command_bytes:
            return None
        full_nec = (
            f"{address_bytes[0]:02X}{address_bytes[0] ^ 0xFF:02X}"
            f"{command_bytes[0]:02X}{command_bytes[0] ^ 0xFF:02X}"
        )
        return nec_to_tuya(full_nec)

    if protocol in {"NECEXT", "ONKYO"}:
        payload = bytes(
            [
                address_bytes[0] if len(address_bytes) > 0 else 0x00,
                address_bytes[1] if len(address_bytes) > 1 else 0x00,
                command_bytes[0] if len(command_bytes) > 0 else 0x00,
                command_bytes[1] if len(command_bytes) > 1 else 0x00,
            ]
        )
        return _encode_nec_payload(payload)

    return None


def _encode_nec_payload(payload: bytes) -> str:
    """Encode a NEC-family payload as Tuya raw."""

    timings = [9000, 4500]
    for byte in payload:
        for bit_index in range(8):
            bit = (byte >> bit_index) & 1
            timings.append(560)
            timings.append(1690 if bit else 560)
    timings.append(560)
    return encode_tuya_ir(timings)


def _parse_hex_bytes(value: str) -> list[int]:
    """Parse a space-separated Flipper byte list."""

    parts = [part for part in value.strip().split() if part]
    if not parts or any(not HEX_BYTE_RE.fullmatch(part) for part in parts):
        return []
    return [int(part, 16) for part in parts]


def _parse_raw_timings(value: str) -> list[int]:
    """Parse a Flipper raw timings field."""

    timings: list[int] = []
    for part in value.split():
        try:
            timings.append(max(0, int(part)))
        except ValueError:
            return []
    return timings


def _meta_from_relative_path(relative_path: PurePosixPath) -> tuple[str, str, str]:
    """Return category, brand, and model from a relative remote path."""

    parts = relative_path.parts
    stem = relative_path.stem or "Unknown"
    category = parts[0] if len(parts) >= 2 else "Unknown"
    brand = parts[1] if len(parts) >= 3 else stem.split("_", 1)[0]
    return category, brand, stem


def _device_type_from_category(category: str) -> str:
    """Infer an OtterIR device type from a Flipper category."""

    normalized = category.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"tvs", "tvs_boxes", "projectors", "monitors"}:
        return "tv"
    if normalized in {"fans", "ceiling_fans"}:
        return "fan"
    if normalized in {"air_conditioners", "acs", "acs_ir"}:
        return "climate"
    if normalized in {"lights", "leds"}:
        return "light"
    return "generic"


def _parse_github_source(source: str) -> dict[str, Any] | None:
    """Parse supported GitHub source URLs."""

    parsed = urlparse(source)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if host == "raw.githubusercontent.com" and len(parts) >= 4:
        return {
            "source": source,
            "owner": parts[0],
            "repo": parts[1],
            "branch": parts[2],
            "path": "/".join(parts[3:]),
            "mode": "file",
        }

    if host != "github.com" or len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    if len(parts) >= 5 and parts[2] in {"blob", "tree"}:
        return {
            "source": source,
            "owner": owner,
            "repo": repo,
            "branch": parts[3],
            "path": "/".join(parts[4:]),
            "mode": "file" if parts[2] == "blob" else "tree",
        }

    return {
        "source": source,
        "owner": owner,
        "repo": repo,
        "branch": None,
        "path": "",
        "mode": "tree",
    }


def _github_raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    """Return a raw GitHub URL for a file."""

    return f"{GITHUB_RAW_ROOT}/{owner}/{repo}/{branch}/{path}"


def _github_blob_url(owner: str, repo: str, branch: str, path: str) -> str:
    """Return a GitHub blob URL for a file."""

    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"


def _default_source_name_from_path(path: Path) -> str:
    """Return a friendly name for a local source."""

    return f"Local Flipper / {path.name}"


def _default_source_name_from_url(url: str) -> str:
    """Return a friendly name for a raw URL source."""

    return f"Remote Flipper / {PurePosixPath(urlparse(url).path).name or 'remote.ir'}"


def _default_github_source_name(owner: str, repo: str, path: str) -> str:
    """Return a friendly name for a GitHub catalog source."""

    prefix = f" / {path}" if path else ""
    return f"{owner}/{repo}{prefix}"


def _stable_source_key(kind: str, value: str) -> str:
    """Return a stable identifier for a source or remote."""

    digest = hashlib.sha1(f"{kind}:{value}".encode("utf-8")).hexdigest()[:10]
    return f"{slugify(kind)}_{digest}"


def _safe_int(value: str | None) -> int | None:
    """Return an integer or None."""

    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None

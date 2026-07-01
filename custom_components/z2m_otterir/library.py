"""Persistent storage helpers for learned and imported IR codes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, TypedDict
from uuid import uuid4

from homeassistant.core import HomeAssistant

from .const import (
    ATTR_CODE,
    ATTR_CODE_HASH,
    ATTR_CODE_ID,
    ATTR_CODE_LENGTH,
    ATTR_DEVICE_TYPE,
    ATTR_ENCODING,
    ATTR_FRIENDLY_NAME,
    ATTR_LEARNED_AT,
    ATTR_LIBRARY,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_RECORD_UID,
    ATTR_SOURCE,
    ATTR_TAGS,
    DEFAULT_LIBRARY,
    DOMAIN,
    ENCODING_TUYA_RAW,
    STORAGE_KEY,
    STORAGE_VERSION,
)

EDITABLE_STORAGE_VERSION = 1
EDITABLE_STORAGE_NAME = "library.json"
TRAILING_COMMA_RE = re.compile(r",(?=\s*[}\]])")


class LearnedCodeRecord(TypedDict):
    """A learned code payload stored per emitter."""

    code: str
    code_hash: str
    code_length: int
    encoding: str
    learned_at: str
    source: str


class SavedCodeRecord(TypedDict):
    """A saved IR command."""

    code: str
    code_hash: str
    code_id: str
    code_length: int
    created_at: str
    device_type: str
    encoding: str
    friendly_name: str | None
    learned_at: str | None
    library: str
    manufacturer: str | None
    model: str | None
    name: str
    record_uid: str
    source: str
    tags: list[str]
    updated_at: str


class CatalogSourceRecord(TypedDict, total=False):
    """A stored external catalog source."""

    metadata: dict[str, Any]
    origin_kind: str
    remote_count: int
    source: str
    source_key: str
    source_name: str
    truncated: bool
    updated_at: str


class CatalogRemoteRecord(TypedDict, total=False):
    """A stored remote inside an imported catalog."""

    brand: str
    category: str
    command_count: int
    commands: list[dict[str, Any]]
    device_type: str
    display_name: str
    library_hint: str
    manufacturer: str | None
    model: str
    origin_kind: str
    origin_url: str
    preview_commands: list[str]
    relative_path: str
    remote_id: str
    source_key: str
    source_name: str
    supported_command_count: int
    unsupported_command_count: int
    updated_at: str


class LibraryStoreData(TypedDict):
    """Storage schema for the integration."""

    catalog_remotes: dict[str, CatalogRemoteRecord]
    catalog_sources: dict[str, CatalogSourceRecord]
    csv_sources: dict[str, str]
    codes: dict[str, SavedCodeRecord]
    entity_id_bases: dict[str, str]
    import_libraries: dict[str, str]
    last_learned: dict[str, LearnedCodeRecord]
    pending_names: dict[str, str]
    smartir_sources: dict[str, str]


def _default_data() -> LibraryStoreData:
    """Return a fresh empty storage payload."""

    return {
        "catalog_remotes": {},
        "catalog_sources": {},
        "csv_sources": {},
        "codes": {},
        "entity_id_bases": {},
        "import_libraries": {},
        "last_learned": {},
        "pending_names": {},
        "smartir_sources": {},
    }


def utcnow_iso() -> str:
    """Return the current UTC timestamp in ISO format."""

    return datetime.now(timezone.utc).isoformat()


def code_hash(code: str) -> str:
    """Return a short stable hash for a code."""

    return hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]


def slugify(value: str) -> str:
    """Convert a string into a stable identifier fragment."""

    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "code"


def parse_tags(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Parse comma-separated tags to a stable tag list."""

    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = [str(item) for item in value]

    seen: set[str] = set()
    parsed: list[str] = []
    for item in items:
        tag = item.strip()
        if not tag or tag in seen:
            continue
        parsed.append(tag)
        seen.add(tag)
    return parsed


def build_learned_record(
    code: str,
    *,
    learned_at: str | None = None,
    source: str = "learned",
    encoding: str = ENCODING_TUYA_RAW,
) -> LearnedCodeRecord:
    """Build a learned code record."""

    return {
        ATTR_CODE: code,
        ATTR_CODE_HASH: code_hash(code),
        ATTR_CODE_LENGTH: len(code),
        ATTR_ENCODING: encoding,
        ATTR_LEARNED_AT: learned_at or utcnow_iso(),
        ATTR_SOURCE: source,
    }


def build_saved_record(
    *,
    code_id: str,
    name: str,
    code: str,
    source: str,
    encoding: str = ENCODING_TUYA_RAW,
    library: str = DEFAULT_LIBRARY,
    friendly_name: str | None = None,
    device_type: str = "generic",
    manufacturer: str | None = None,
    model: str | None = None,
    tags: list[str] | None = None,
    learned_at: str | None = None,
    created_at: str | None = None,
    record_uid: str | None = None,
) -> SavedCodeRecord:
    """Build a persistent saved-code record."""

    now = utcnow_iso()
    return {
        ATTR_CODE: code,
        ATTR_CODE_HASH: code_hash(code),
        ATTR_CODE_ID: code_id,
        ATTR_CODE_LENGTH: len(code),
        "created_at": created_at or now,
        ATTR_DEVICE_TYPE: device_type,
        ATTR_ENCODING: encoding,
        ATTR_FRIENDLY_NAME: friendly_name,
        ATTR_LEARNED_AT: learned_at,
        ATTR_LIBRARY: library,
        ATTR_MANUFACTURER: manufacturer,
        ATTR_MODEL: model,
        ATTR_NAME: name,
        ATTR_RECORD_UID: record_uid or new_record_uid(),
        ATTR_SOURCE: source,
        ATTR_TAGS: tags or [],
        "updated_at": now,
    }


def new_record_uid() -> str:
    """Return a stable opaque id for one stored command record."""

    return uuid4().hex


class IRLibraryStore:
    """Persist learned and imported IR codes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the storage helper."""

        self.hass = hass
        self._entry_id = entry_id
        self._editable_path = Path(hass.config.path(DOMAIN, EDITABLE_STORAGE_NAME))
        self._legacy_path = Path(hass.config.path(".storage", f"{STORAGE_KEY}_{entry_id}"))
        self._legacy_glob = f"{STORAGE_KEY}_{entry_id}.corrupt.*"
        self._data: LibraryStoreData = _default_data()

    async def async_load(self) -> None:
        """Load storage data from disk."""

        # Re-save after loading so legacy or repaired payloads are migrated into
        # the editable grouped JSON format in one predictable place.
        self._data = await self.hass.async_add_executor_job(self._load_best_available_data)
        await self.async_save()

    @property
    def data(self) -> LibraryStoreData:
        """Return the full storage payload."""

        return self._data

    @property
    def codes(self) -> dict[str, SavedCodeRecord]:
        """Return all saved codes."""

        return self._data["codes"]

    @property
    def last_learned(self) -> dict[str, LearnedCodeRecord]:
        """Return the last learned code per emitter."""

        return self._data["last_learned"]

    @property
    def catalog_sources(self) -> dict[str, CatalogSourceRecord]:
        """Return known catalog sources."""

        return self._data["catalog_sources"]

    @property
    def catalog_remotes(self) -> dict[str, CatalogRemoteRecord]:
        """Return known catalog remotes."""

        return self._data["catalog_remotes"]

    async def async_set_last_learned(
        self,
        friendly_name: str,
        record: LearnedCodeRecord,
    ) -> None:
        """Persist the last learned code for an emitter."""

        self._data["last_learned"][friendly_name] = record
        await self.async_save()

    def get_last_learned(self, friendly_name: str) -> LearnedCodeRecord | None:
        """Return the most recent learned code for an emitter."""

        return self._data["last_learned"].get(friendly_name)

    def get_code(self, code_id: str) -> SavedCodeRecord | None:
        """Return a saved code by id."""

        return self._data["codes"].get(code_id)

    def get_code_by_record_uid(self, record_uid: str) -> SavedCodeRecord | None:
        """Return a saved code by its stable record uid."""

        for record in self._data["codes"].values():
            if record.get(ATTR_RECORD_UID) == record_uid:
                return record
        return None

    def get_catalog_source(self, source_key: str) -> CatalogSourceRecord | None:
        """Return a catalog source by source key."""

        return self._data["catalog_sources"].get(source_key)

    def get_catalog_remote(self, remote_id: str) -> CatalogRemoteRecord | None:
        """Return a catalog remote by remote id."""

        return self._data["catalog_remotes"].get(remote_id)

    def count_codes(self, friendly_name: str | None = None) -> int:
        """Return the number of saved codes, optionally filtered by emitter."""

        return len(self.list_codes(friendly_name))

    def list_codes(self, friendly_name: str | None = None) -> list[SavedCodeRecord]:
        """Return saved codes, optionally filtered by emitter."""

        records = list(self._data["codes"].values())
        if friendly_name is not None:
            records = [
                record
                for record in records
                if record.get(ATTR_FRIENDLY_NAME) in {None, friendly_name}
            ]
        return sorted(
            records,
            key=lambda item: (
                item[ATTR_LIBRARY],
                item.get(ATTR_FRIENDLY_NAME) or "",
                item[ATTR_NAME],
            ),
        )

    def list_catalog_sources(self) -> list[CatalogSourceRecord]:
        """Return catalog sources sorted for display."""

        return sorted(
            self._data["catalog_sources"].values(),
            key=lambda item: (
                item.get("source_name", ""),
                item.get("source_key", ""),
            ),
        )

    def list_catalog_remotes(
        self,
        source_key: str | None = None,
    ) -> list[CatalogRemoteRecord]:
        """Return catalog remotes sorted for display."""

        records = list(self._data["catalog_remotes"].values())
        if source_key is not None:
            records = [
                record for record in records if record.get("source_key") == source_key
            ]

        return sorted(
            records,
            key=lambda item: (
                item.get("source_name", ""),
                item.get("category", ""),
                item.get("brand", ""),
                item.get("display_name", ""),
                item.get("relative_path", ""),
            ),
        )

    def get_pending_name(self, friendly_name: str) -> str:
        """Return the pending name for an emitter."""

        return self._data["pending_names"].get(friendly_name, "")

    async def async_set_pending_name(self, friendly_name: str, value: str) -> None:
        """Persist the pending name for an emitter."""

        cleaned = value.strip()
        if cleaned:
            self._data["pending_names"][friendly_name] = cleaned
        else:
            self._data["pending_names"].pop(friendly_name, None)
        await self.async_save()

    def get_csv_source(self, friendly_name: str) -> str:
        """Return the configured CSV/TSV source for an emitter."""

        return self._data["csv_sources"].get(friendly_name, "")

    async def async_set_csv_source(self, friendly_name: str, value: str) -> None:
        """Persist the CSV/TSV source for an emitter."""

        cleaned = value.strip()
        if cleaned:
            self._data["csv_sources"][friendly_name] = cleaned
        else:
            self._data["csv_sources"].pop(friendly_name, None)
        await self.async_save()

    def get_import_library(self, friendly_name: str) -> str:
        """Return the configured import library for an emitter."""

        return self._data["import_libraries"].get(friendly_name, "")

    def get_entity_id_base(self, friendly_name: str) -> str:
        """Return the configured entity-id base for an emitter."""

        return self._data["entity_id_bases"].get(friendly_name, "")

    async def async_set_entity_id_base(self, friendly_name: str, value: str) -> None:
        """Persist the entity-id base for an emitter."""

        cleaned = value.strip()
        if cleaned:
            self._data["entity_id_bases"][friendly_name] = cleaned
        else:
            self._data["entity_id_bases"].pop(friendly_name, None)
        await self.async_save()

    async def async_set_import_library(self, friendly_name: str, value: str) -> None:
        """Persist the import library for an emitter."""

        cleaned = value.strip()
        if cleaned:
            self._data["import_libraries"][friendly_name] = cleaned
        else:
            self._data["import_libraries"].pop(friendly_name, None)
        await self.async_save()

    def get_smartir_source(self, friendly_name: str) -> str:
        """Return the configured SmartIR source for an emitter."""

        return self._data["smartir_sources"].get(friendly_name, "")

    async def async_set_smartir_source(self, friendly_name: str, value: str) -> None:
        """Persist the SmartIR source for an emitter."""

        cleaned = value.strip()
        if cleaned:
            self._data["smartir_sources"][friendly_name] = cleaned
        else:
            self._data["smartir_sources"].pop(friendly_name, None)
        await self.async_save()

    def next_code_id(self, name: str, library: str = DEFAULT_LIBRARY) -> str:
        """Generate a unique code id for a new record."""

        base = f"{slugify(library)}_{slugify(name)}"
        if base not in self._data["codes"]:
            return base

        suffix = 2
        while f"{base}_{suffix}" in self._data["codes"]:
            suffix += 1
        return f"{base}_{suffix}"

    def next_code_id_for_update(
        self,
        name: str,
        library: str = DEFAULT_LIBRARY,
        *,
        exclude_code_id: str | None = None,
    ) -> str:
        """Generate a unique code id while allowing one existing record to keep its id."""

        base = f"{slugify(library)}_{slugify(name)}"
        if base == exclude_code_id or base not in self._data["codes"]:
            return base

        suffix = 2
        while True:
            candidate = f"{base}_{suffix}"
            if candidate == exclude_code_id or candidate not in self._data["codes"]:
                return candidate
            suffix += 1

    async def async_upsert_code(self, record: SavedCodeRecord) -> None:
        """Insert or update a saved code."""

        self._data["codes"][record[ATTR_CODE_ID]] = record
        await self.async_save()

    async def async_update_code_metadata(
        self,
        current_code_id: str,
        *,
        name: str,
        code_id: str = "",
    ) -> SavedCodeRecord:
        """Rename a saved code and optionally change its internal command id."""

        existing = self._data["codes"].get(current_code_id)
        if existing is None:
            raise KeyError(current_code_id)

        cleaned_name = str(name).strip() or existing[ATTR_NAME]
        desired_code_id = str(code_id).strip() or current_code_id

        if desired_code_id != current_code_id and desired_code_id in self._data["codes"]:
            raise ValueError(f"Code id '{desired_code_id}' already exists")

        updated = deepcopy(existing)
        updated[ATTR_NAME] = cleaned_name
        updated[ATTR_CODE_ID] = desired_code_id
        updated["updated_at"] = utcnow_iso()

        if desired_code_id != current_code_id:
            del self._data["codes"][current_code_id]
        self._data["codes"][desired_code_id] = updated
        await self.async_save()
        return updated

    async def async_delete_code(self, code_id: str) -> bool:
        """Delete a saved code if it exists."""

        if code_id not in self._data["codes"]:
            return False

        del self._data["codes"][code_id]
        await self.async_save()
        return True

    async def async_delete_library(
        self,
        library: str,
        *,
        friendly_name: str | None = None,
    ) -> int:
        """Delete all saved codes from a specific library/scope."""

        deleted_ids = [
            code_id
            for code_id, record in self._data["codes"].items()
            if record.get(ATTR_LIBRARY) == library
            and record.get(ATTR_FRIENDLY_NAME) == friendly_name
        ]
        if not deleted_ids:
            return 0

        for code_id in deleted_ids:
            del self._data["codes"][code_id]

        await self.async_save()
        return len(deleted_ids)

    async def async_rename_library(
        self,
        library: str,
        new_library: str,
        *,
        friendly_name: str | None = None,
    ) -> int:
        """Rename all saved codes from one library/scope to another library name."""

        cleaned_new_library = str(new_library).strip()
        if not cleaned_new_library:
            raise ValueError("Library name cannot be empty")

        updated_count = 0
        for record in self._data["codes"].values():
            if record.get(ATTR_LIBRARY) != library:
                continue
            if record.get(ATTR_FRIENDLY_NAME) != friendly_name:
                continue

            record[ATTR_LIBRARY] = cleaned_new_library
            record["updated_at"] = utcnow_iso()
            updated_count += 1

        if updated_count == 0:
            return 0

        await self.async_save()
        return updated_count

    async def async_replace_catalog_source(
        self,
        source_record: CatalogSourceRecord,
        remote_records: list[CatalogRemoteRecord],
    ) -> None:
        """Replace a catalog source and all of its remotes."""

        source_key = str(source_record.get("source_key", "")).strip()
        if not source_key:
            raise ValueError("Catalog source is missing source_key")

        self._data["catalog_sources"][source_key] = deepcopy(source_record)
        self._data["catalog_remotes"] = {
            remote_id: remote
            for remote_id, remote in self._data["catalog_remotes"].items()
            if remote.get("source_key") != source_key
        }
        for remote_record in remote_records:
            remote_id = str(remote_record.get("remote_id", "")).strip()
            if not remote_id:
                continue
            self._data["catalog_remotes"][remote_id] = deepcopy(remote_record)
        await self.async_save()

    async def async_delete_catalog_source(self, source_key: str) -> bool:
        """Delete a catalog source and all remotes under it."""

        if source_key not in self._data["catalog_sources"]:
            return False

        del self._data["catalog_sources"][source_key]
        self._data["catalog_remotes"] = {
            remote_id: remote
            for remote_id, remote in self._data["catalog_remotes"].items()
            if remote.get("source_key") != source_key
        }
        await self.async_save()
        return True

    async def async_save(self) -> None:
        """Write storage data to disk."""

        payload = deepcopy(self._data)
        await self.hass.async_add_executor_job(self._write_editable_payload, payload)

    def _load_best_available_data(self) -> LibraryStoreData:
        """Load the best available payload from editable or legacy storage."""

        if self._editable_path.is_file():
            payload = self._read_json_file(self._editable_path)
            return _deduplicate_data(_normalize_loaded_payload(payload))

        # If the editable file does not exist yet, prefer the most complete
        # legacy payload, including auto-repaired corrupt backups when possible.
        candidates: list[tuple[int, LibraryStoreData]] = []

        if self._legacy_path.is_file():
            try:
                payload = self._read_json_file(self._legacy_path)
                candidates.append(
                    (_score_data(payload), _deduplicate_data(_normalize_loaded_payload(payload)))
                )
            except Exception:
                pass

        for corrupt_path in sorted(
            self._legacy_path.parent.glob(self._legacy_glob),
            reverse=True,
        ):
            try:
                payload = self._read_json_file(corrupt_path)
                normalized = _deduplicate_data(_normalize_loaded_payload(payload))
                candidates.append((_score_data(payload) + 1000, normalized))
            except Exception:
                continue

        if not candidates:
            return _default_data()

        return _deduplicate_data(max(candidates, key=lambda item: item[0])[1])

    def _write_editable_payload(self, payload: LibraryStoreData) -> None:
        """Write the editable JSON payload to disk."""

        self._editable_path.parent.mkdir(parents=True, exist_ok=True)
        export = _serialize_editable_payload(payload)
        temp_path = self._editable_path.with_suffix(".tmp")
        # Write atomically so Home Assistant never sees a half-written library file.
        temp_path.write_text(
            json.dumps(export, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self._editable_path)

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        """Read and parse JSON from disk with light syntax repair."""

        text = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            repaired = TRAILING_COMMA_RE.sub("", text)
            payload = json.loads(repaired)

        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object in '{path}'")
        return payload


def _normalize_loaded_payload(payload: dict[str, Any]) -> LibraryStoreData:
    """Normalize editable or legacy payloads to the in-memory structure."""

    if isinstance(payload.get("data"), dict):
        payload = payload["data"]

    if (
        "devices" in payload
        or "shared_codes" in payload
        or "device_codes" in payload
        or "catalogs" in payload
    ):
        return _normalize_editable_payload(payload)

    return _normalize_legacy_payload(payload)


def _normalize_legacy_payload(payload: dict[str, Any]) -> LibraryStoreData:
    """Normalize the legacy flat payload."""

    normalized = _default_data()
    normalized["codes"].update(_normalize_legacy_codes(payload.get("codes", {})))
    normalized["csv_sources"].update(_clean_string_map(payload.get("csv_sources", {})))
    normalized["csv_sources"].update(_clean_string_map(payload.get("import_urls", {})))
    normalized["catalog_sources"].update(
        _normalize_catalog_source_map(payload.get("catalog_sources", {}))
    )
    normalized["catalog_remotes"].update(
        _normalize_catalog_remote_map(payload.get("catalog_remotes", {}))
    )
    normalized["entity_id_bases"].update(
        _clean_string_map(payload.get("entity_id_bases", {}))
    )
    normalized["import_libraries"].update(
        _clean_string_map(payload.get("import_libraries", {}))
    )
    normalized["pending_names"].update(_clean_string_map(payload.get("pending_names", {})))
    normalized["smartir_sources"].update(
        _clean_string_map(payload.get("smartir_sources", {}))
    )

    last_learned = payload.get("last_learned", {})
    if isinstance(last_learned, dict):
        for friendly_name, record in last_learned.items():
            if not isinstance(record, dict):
                continue
            normalized["last_learned"][str(friendly_name)] = _normalize_learned_record(record)

    return normalized


def _normalize_editable_payload(payload: dict[str, Any]) -> LibraryStoreData:
    """Normalize the editable grouped payload."""

    normalized = _default_data()

    devices = payload.get("devices", {})
    if isinstance(devices, dict):
        for friendly_name, device_data in devices.items():
            if not isinstance(device_data, dict):
                continue
            device_name = str(friendly_name)
            pending_name = str(device_data.get("pending_name", "")).strip()
            csv_source = str(device_data.get("csv_source", "")).strip()
            entity_id_base = str(device_data.get("entity_id_base", "")).strip()
            import_library = str(device_data.get("import_library", "")).strip()
            smartir_source = str(device_data.get("smartir_source", "")).strip()

            if pending_name:
                normalized["pending_names"][device_name] = pending_name
            if csv_source:
                normalized["csv_sources"][device_name] = csv_source
            if entity_id_base:
                normalized["entity_id_bases"][device_name] = entity_id_base
            if import_library:
                normalized["import_libraries"][device_name] = import_library
            if smartir_source:
                normalized["smartir_sources"][device_name] = smartir_source

            learned = device_data.get("last_learned")
            if isinstance(learned, dict) and learned.get(ATTR_CODE):
                normalized["last_learned"][device_name] = _normalize_learned_record(learned)

    shared_codes = payload.get("shared_codes", {})
    if isinstance(shared_codes, dict):
        for library_name, records in shared_codes.items():
            for record in _iter_group_records(records):
                normalized_record = _normalize_saved_record(
                    record,
                    library=str(library_name),
                    friendly_name=None,
                )
                normalized["codes"][normalized_record[ATTR_CODE_ID]] = normalized_record

    device_codes = payload.get("device_codes", {})
    if isinstance(device_codes, dict):
        for friendly_name, libraries in device_codes.items():
            if not isinstance(libraries, dict):
                continue
            for library_name, records in libraries.items():
                for record in _iter_group_records(records):
                    normalized_record = _normalize_saved_record(
                        record,
                        library=str(library_name),
                        friendly_name=str(friendly_name),
                    )
                    normalized["codes"][normalized_record[ATTR_CODE_ID]] = normalized_record

    catalogs = payload.get("catalogs", {})
    if isinstance(catalogs, dict):
        normalized["catalog_sources"].update(
            _normalize_catalog_source_map(catalogs.get("sources", {}))
        )
        normalized["catalog_remotes"].update(
            _normalize_catalog_remote_map(catalogs.get("remotes", {}))
        )

    return normalized


def _normalize_legacy_codes(codes: Any) -> dict[str, SavedCodeRecord]:
    """Normalize flat code maps from the legacy structure."""

    normalized: dict[str, SavedCodeRecord] = {}
    if not isinstance(codes, dict):
        return normalized

    for code_id, record in codes.items():
        if not isinstance(record, dict):
            continue
        normalized_record = _normalize_saved_record(
            record,
            code_id=str(code_id),
            library=record.get(ATTR_LIBRARY),
            friendly_name=record.get(ATTR_FRIENDLY_NAME),
        )
        normalized[normalized_record[ATTR_CODE_ID]] = normalized_record
    return normalized


def _normalize_saved_record(
    record: dict[str, Any],
    *,
    library: str | None = None,
    friendly_name: str | None = None,
    code_id: str | None = None,
) -> SavedCodeRecord:
    """Normalize a saved record to the canonical structure."""

    code = str(record.get(ATTR_CODE, "")).strip()
    name = str(record.get(ATTR_NAME, code_id or "Unnamed")).strip() or "Unnamed"
    record_library = str(library or record.get(ATTR_LIBRARY) or DEFAULT_LIBRARY).strip()
    record_code_id = str(
        code_id or record.get(ATTR_CODE_ID) or f"{slugify(record_library)}_{slugify(name)}"
    ).strip()
    created_at = str(record.get("created_at") or utcnow_iso())
    updated_at = str(record.get("updated_at") or created_at)
    learned_at = record.get(ATTR_LEARNED_AT)
    record_uid = str(record.get(ATTR_RECORD_UID) or "").strip() or new_record_uid()

    return {
        ATTR_CODE: code,
        ATTR_CODE_HASH: code_hash(code),
        ATTR_CODE_ID: record_code_id,
        ATTR_CODE_LENGTH: len(code),
        "created_at": created_at,
        ATTR_DEVICE_TYPE: str(record.get(ATTR_DEVICE_TYPE) or "generic"),
        ATTR_ENCODING: str(record.get(ATTR_ENCODING) or ENCODING_TUYA_RAW),
        ATTR_FRIENDLY_NAME: friendly_name,
        ATTR_LEARNED_AT: str(learned_at) if learned_at is not None else None,
        ATTR_LIBRARY: record_library,
        ATTR_MANUFACTURER: _optional_str(record.get(ATTR_MANUFACTURER)),
        ATTR_MODEL: _optional_str(record.get(ATTR_MODEL)),
        ATTR_NAME: name,
        ATTR_RECORD_UID: record_uid,
        ATTR_SOURCE: str(record.get(ATTR_SOURCE) or "imported"),
        ATTR_TAGS: parse_tags(record.get(ATTR_TAGS)),
        "updated_at": updated_at,
    }


def _normalize_learned_record(record: dict[str, Any]) -> LearnedCodeRecord:
    """Normalize a learned record."""

    code = str(record.get(ATTR_CODE, "")).strip()
    return {
        ATTR_CODE: code,
        ATTR_CODE_HASH: code_hash(code),
        ATTR_CODE_LENGTH: len(code),
        ATTR_ENCODING: str(record.get(ATTR_ENCODING) or ENCODING_TUYA_RAW),
        ATTR_LEARNED_AT: str(record.get(ATTR_LEARNED_AT) or utcnow_iso()),
        ATTR_SOURCE: str(record.get(ATTR_SOURCE) or "learned"),
    }


def _serialize_editable_payload(data: LibraryStoreData) -> dict[str, Any]:
    """Convert the in-memory payload to an ordered editable JSON structure."""

    payload: dict[str, Any] = {
        "version": EDITABLE_STORAGE_VERSION,
        "catalogs": {
            "sources": {},
            "remotes": {},
        },
        "devices": {},
        "shared_codes": {},
        "device_codes": {},
    }

    device_names = sorted(
        set(data["pending_names"])
        | set(data["csv_sources"])
        | set(data["entity_id_bases"])
        | set(data["import_libraries"])
        | set(data["smartir_sources"])
        | set(data["last_learned"])
        | {
            record[ATTR_FRIENDLY_NAME]
            for record in data["codes"].values()
            if record.get(ATTR_FRIENDLY_NAME)
        }
    )

    for friendly_name in device_names:
        if friendly_name is None:
            continue
        device_entry: dict[str, Any] = {}
        if pending_name := data["pending_names"].get(friendly_name):
            device_entry["pending_name"] = pending_name
        if csv_source := data["csv_sources"].get(friendly_name):
            device_entry["csv_source"] = csv_source
        if entity_id_base := data["entity_id_bases"].get(friendly_name):
            device_entry["entity_id_base"] = entity_id_base
        if import_library := data["import_libraries"].get(friendly_name):
            device_entry["import_library"] = import_library
        if smartir_source := data["smartir_sources"].get(friendly_name):
            device_entry["smartir_source"] = smartir_source
        if learned := data["last_learned"].get(friendly_name):
            device_entry["last_learned"] = _export_learned_record(learned)
        payload["devices"][friendly_name] = device_entry

    shared_codes: dict[str, list[dict[str, Any]]] = {}
    device_codes: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for record in sorted(
        data["codes"].values(),
        key=lambda item: (
            item[ATTR_FRIENDLY_NAME] or "",
            item[ATTR_LIBRARY],
            item[ATTR_NAME],
        ),
    ):
        exported = _export_saved_record(record)
        library = record[ATTR_LIBRARY]
        friendly_name = record.get(ATTR_FRIENDLY_NAME)
        if friendly_name is None:
            shared_codes.setdefault(library, []).append(exported)
        else:
            device_codes.setdefault(friendly_name, {}).setdefault(library, []).append(exported)

    payload["shared_codes"] = dict(sorted(shared_codes.items()))
    payload["device_codes"] = {
        friendly_name: dict(sorted(libraries.items()))
        for friendly_name, libraries in sorted(device_codes.items())
    }
    payload["catalogs"]["sources"] = {
        source_key: _export_catalog_source_record(record)
        for source_key, record in sorted(data["catalog_sources"].items())
    }

    grouped_remotes: dict[str, list[dict[str, Any]]] = {}
    for record in sorted(
        data["catalog_remotes"].values(),
        key=lambda item: (
            item.get("source_name", ""),
            item.get("category", ""),
            item.get("brand", ""),
            item.get("display_name", ""),
            item.get("relative_path", ""),
        ),
    ):
        grouped_remotes.setdefault(record.get("source_key", "unknown"), []).append(
            _export_catalog_remote_record(record)
        )

    payload["catalogs"]["remotes"] = dict(sorted(grouped_remotes.items()))
    return payload


def _deduplicate_data(data: LibraryStoreData) -> LibraryStoreData:
    """Remove exact duplicate saved codes from a payload."""

    deduped = _default_data()
    deduped["catalog_sources"].update(data["catalog_sources"])
    deduped["catalog_remotes"].update(data["catalog_remotes"])
    deduped["csv_sources"].update(data["csv_sources"])
    deduped["entity_id_bases"].update(data["entity_id_bases"])
    deduped["import_libraries"].update(data["import_libraries"])
    deduped["last_learned"].update(data["last_learned"])
    deduped["pending_names"].update(data["pending_names"])
    deduped["smartir_sources"].update(data["smartir_sources"])

    chosen: dict[tuple[str | None, str, str, str], SavedCodeRecord] = {}
    for record in data["codes"].values():
        key = (
            record.get(ATTR_FRIENDLY_NAME),
            record[ATTR_LIBRARY],
            record[ATTR_NAME],
            record[ATTR_CODE_HASH],
        )
        current = chosen.get(key)
        if current is None or _prefer_record(record, current):
            chosen[key] = record

    for record in chosen.values():
        deduped["codes"][record[ATTR_CODE_ID]] = record

    return deduped


def _export_saved_record(record: SavedCodeRecord) -> dict[str, Any]:
    """Export a saved code for the editable JSON file."""

    return {
        ATTR_CODE_ID: record[ATTR_CODE_ID],
        ATTR_NAME: record[ATTR_NAME],
        ATTR_CODE: record[ATTR_CODE],
        ATTR_DEVICE_TYPE: record[ATTR_DEVICE_TYPE],
        ATTR_ENCODING: record[ATTR_ENCODING],
        ATTR_MANUFACTURER: record.get(ATTR_MANUFACTURER),
        ATTR_MODEL: record.get(ATTR_MODEL),
        ATTR_RECORD_UID: record[ATTR_RECORD_UID],
        ATTR_SOURCE: record[ATTR_SOURCE],
        ATTR_TAGS: list(record.get(ATTR_TAGS, [])),
        ATTR_LEARNED_AT: record.get(ATTR_LEARNED_AT),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _export_learned_record(record: LearnedCodeRecord) -> dict[str, Any]:
    """Export a learned record for the editable JSON file."""

    return {
        ATTR_CODE: record[ATTR_CODE],
        ATTR_ENCODING: record[ATTR_ENCODING],
        ATTR_LEARNED_AT: record[ATTR_LEARNED_AT],
        ATTR_SOURCE: record[ATTR_SOURCE],
    }


def _export_catalog_source_record(record: CatalogSourceRecord) -> dict[str, Any]:
    """Export a catalog source for the editable JSON file."""

    return {
        "source_key": record.get("source_key"),
        "source_name": record.get("source_name"),
        "origin_kind": record.get("origin_kind"),
        "source": record.get("source"),
        "remote_count": record.get("remote_count", 0),
        "truncated": bool(record.get("truncated", False)),
        "metadata": deepcopy(record.get("metadata", {})),
        "updated_at": record.get("updated_at"),
    }


def _export_catalog_remote_record(record: CatalogRemoteRecord) -> dict[str, Any]:
    """Export a catalog remote for the editable JSON file."""

    return {
        "remote_id": record.get("remote_id"),
        "source_key": record.get("source_key"),
        "source_name": record.get("source_name"),
        "origin_kind": record.get("origin_kind"),
        "origin_url": record.get("origin_url"),
        "relative_path": record.get("relative_path"),
        "category": record.get("category"),
        "brand": record.get("brand"),
        "model": record.get("model"),
        "display_name": record.get("display_name"),
        "manufacturer": record.get("manufacturer"),
        "device_type": record.get("device_type"),
        "library_hint": record.get("library_hint"),
        "command_count": record.get("command_count", 0),
        "supported_command_count": record.get("supported_command_count", 0),
        "unsupported_command_count": record.get("unsupported_command_count", 0),
        "preview_commands": list(record.get("preview_commands", [])),
        "commands": deepcopy(record.get("commands", [])),
        "updated_at": record.get("updated_at"),
    }


def _iter_group_records(records: Any) -> list[dict[str, Any]]:
    """Return grouped records as a list of dictionaries."""

    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    if isinstance(records, dict):
        return [record for record in records.values() if isinstance(record, dict)]
    return []


def _clean_string_map(value: Any) -> dict[str, str]:
    """Normalize a mapping of strings to non-empty strings."""

    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        text = str(item).strip()
        if text:
            cleaned[str(key)] = text
    return cleaned


def _normalize_catalog_source_map(value: Any) -> dict[str, CatalogSourceRecord]:
    """Normalize stored catalog sources."""

    if not isinstance(value, dict):
        return {}

    normalized: dict[str, CatalogSourceRecord] = {}
    for source_key, record in value.items():
        if not isinstance(record, dict):
            continue
        normalized_record = _normalize_catalog_source_record(record, source_key)
        normalized[normalized_record["source_key"]] = normalized_record
    return normalized


def _normalize_catalog_remote_map(value: Any) -> dict[str, CatalogRemoteRecord]:
    """Normalize stored catalog remotes."""

    normalized: dict[str, CatalogRemoteRecord] = {}
    if not isinstance(value, dict):
        return normalized

    for key, record in value.items():
        if isinstance(record, dict):
            normalized_record = _normalize_catalog_remote_record(record, remote_id=key)
            normalized[normalized_record["remote_id"]] = normalized_record
            continue

        if not isinstance(record, list):
            continue

        source_key = str(key)
        for item in record:
            if not isinstance(item, dict):
                continue
            normalized_record = _normalize_catalog_remote_record(
                item,
                source_key=source_key,
            )
            normalized[normalized_record["remote_id"]] = normalized_record

    return normalized


def _normalize_catalog_source_record(
    record: dict[str, Any],
    source_key: str | None = None,
) -> CatalogSourceRecord:
    """Normalize one catalog source."""

    normalized_source_key = (
        str(source_key or record.get("source_key") or "").strip() or "catalog_source"
    )
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "source_key": normalized_source_key,
        "source_name": str(record.get("source_name") or normalized_source_key).strip()
        or normalized_source_key,
        "origin_kind": str(record.get("origin_kind") or "unknown").strip() or "unknown",
        "source": str(record.get("source") or "").strip(),
        "remote_count": _safe_int(record.get("remote_count")) or 0,
        "truncated": bool(record.get("truncated", False)),
        "metadata": deepcopy(metadata),
        "updated_at": str(record.get("updated_at") or utcnow_iso()),
    }


def _normalize_catalog_remote_record(
    record: dict[str, Any],
    *,
    source_key: str | None = None,
    remote_id: str | None = None,
) -> CatalogRemoteRecord:
    """Normalize one catalog remote."""

    normalized_source_key = (
        str(source_key or record.get("source_key") or "").strip() or "catalog_source"
    )
    normalized_remote_id = (
        str(remote_id or record.get("remote_id") or "").strip()
        or f"{normalized_source_key}_remote"
    )
    commands = record.get("commands", [])
    if not isinstance(commands, list):
        commands = []

    preview_commands = record.get("preview_commands", [])
    if not isinstance(preview_commands, list):
        preview_commands = []

    command_count = _safe_int(record.get("command_count")) or len(commands)
    supported_count = _safe_int(record.get("supported_command_count")) or sum(
        1
        for command in commands
        if isinstance(command, dict) and command.get("supported")
    )
    unsupported_count = _safe_int(record.get("unsupported_command_count"))
    if unsupported_count is None:
        unsupported_count = max(0, command_count - supported_count)
    if not preview_commands:
        preview_commands = [
            str(command.get(ATTR_NAME)).strip()
            for command in commands
            if isinstance(command, dict) and str(command.get(ATTR_NAME, "")).strip()
        ][:8]

    return {
        "remote_id": normalized_remote_id,
        "source_key": normalized_source_key,
        "source_name": str(record.get("source_name") or normalized_source_key).strip()
        or normalized_source_key,
        "origin_kind": str(record.get("origin_kind") or "unknown").strip() or "unknown",
        "origin_url": str(record.get("origin_url") or "").strip(),
        "relative_path": str(record.get("relative_path") or normalized_remote_id).strip()
        or normalized_remote_id,
        "category": str(record.get("category") or "").strip(),
        "brand": str(record.get("brand") or "").strip(),
        "model": str(record.get("model") or "").strip(),
        "display_name": str(
            record.get("display_name") or record.get("model") or normalized_remote_id
        ).strip()
        or normalized_remote_id,
        "manufacturer": _optional_str(record.get("manufacturer")),
        "device_type": str(record.get("device_type") or "generic").strip() or "generic",
        "library_hint": str(record.get("library_hint") or "default").strip() or "default",
        "command_count": command_count,
        "supported_command_count": supported_count,
        "unsupported_command_count": unsupported_count,
        "preview_commands": [str(item).strip() for item in preview_commands if str(item).strip()],
        "commands": deepcopy([item for item in commands if isinstance(item, dict)]),
        "updated_at": str(record.get("updated_at") or utcnow_iso()),
    }


def _optional_str(value: Any) -> str | None:
    """Return a cleaned optional string."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prefer_record(candidate: SavedCodeRecord, current: SavedCodeRecord) -> bool:
    """Return true when the candidate is a better duplicate to keep."""

    candidate_rank = (_suffix_penalty(candidate[ATTR_CODE_ID]), candidate["created_at"])
    current_rank = (_suffix_penalty(current[ATTR_CODE_ID]), current["created_at"])
    return candidate_rank < current_rank


def _suffix_penalty(code_id: str) -> int:
    """Return a penalty for numeric suffixes so canonical ids win."""

    match = re.search(r"_(\d+)$", code_id)
    return int(match.group(1)) if match else 0


def _score_data(payload: dict[str, Any]) -> int:
    """Score a payload so richer data wins during migration."""

    normalized = _normalize_loaded_payload(payload)
    return (
        len(normalized["codes"]) * 100
        + len(normalized["catalog_remotes"]) * 10
        + len(normalized["catalog_sources"]) * 10
        + len(normalized["last_learned"]) * 10
        + len(normalized["pending_names"])
        + len(normalized["csv_sources"])
        + len(normalized["entity_id_bases"])
        + len(normalized["smartir_sources"])
        + len(normalized["import_libraries"])
    )


def _safe_int(value: Any) -> int | None:
    """Return an integer when possible."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return None

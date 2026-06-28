"""Constants for the OtterIR integration."""

from __future__ import annotations

DOMAIN = "z2m_otter_ir"

DEFAULT_BASE_TOPIC = "zigbee2mqtt"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_LIBRARY = "default"

PLATFORMS = ["infrared", "button", "sensor", "event"]

ENCODING_TUYA_RAW = "tuya_raw_base64"
ENCODING_BROADLINK_BASE64 = "broadlink_base64"

CONF_BASE_TOPIC = "base_topic"
CONF_DISCOVERY_PREFIX = "discovery_prefix"
CONF_ENABLE_AUTO = "enable_auto"
CONF_MANUAL_FRIENDLY_NAMES = "manual_friendly_names"

ATTR_CODE = "code"
ATTR_CODE_HASH = "code_hash"
ATTR_CODE_ID = "code_id"
ATTR_CODE_IDS = "code_ids"
ATTR_CODE_LENGTH = "code_length"
ATTR_CATALOG_NAME = "catalog_name"
ATTR_COMMANDS_IMPORTED = "commands_imported"
ATTR_CSV_SOURCE = "csv_source"
ATTR_DEVICE_TYPE = "device_type"
ATTR_ENTITY_ID_BASE = "entity_id_base"
ATTR_ENCODING = "encoding"
ATTR_FILE_PATH = "file_path"
ATTR_FRIENDLY_NAME = "friendly_name"
ATTR_IMPORT_LIBRARY = "import_library"
ATTR_IMPORT_SOURCE = "import_source"
ATTR_LEARNED_AT = "learned_at"
ATTR_LIBRARY = "library"
ATTR_MANUFACTURER = "manufacturer"
ATTR_MODEL = "model"
ATTR_NAME = "name"
ATTR_OVERWRITE = "overwrite"
ATTR_MAX_FILES = "max_files"
ATTR_PENDING_NAME = "pending_name"
ATTR_REPEAT = "repeat"
ATTR_REMOTE_ID = "remote_id"
ATTR_RECORD_UID = "record_uid"
ATTR_SAVED_COUNT = "saved_count"
ATTR_SAVED_NAMES = "saved_names"
ATTR_SHARED = "shared"
ATTR_SMARTIR_SOURCE = "smartir_source"
ATTR_SOURCE = "source"
ATTR_SOURCE_KEY = "source_key"
ATTR_TAGS = "tags"
ATTR_URL = "url"

EVENT_LEARNED = "learned"

SERVICE_DELETE_CODE = "delete_code"
SERVICE_DELETE_CATALOG_SOURCE = "delete_catalog_source"
SERVICE_SET_ENTITY_ID_BASE = "set_entity_id_base"
SERVICE_IMPORT_CATALOG_REMOTE = "import_catalog_remote"
SERVICE_IMPORT_CSV_COMMANDS = "import_csv_commands"
SERVICE_IMPORT_FLIPPER_SOURCE = "import_flipper_source"
SERVICE_IMPORT_BROADLINK_CODE = "import_broadlink_code"
SERVICE_IMPORT_SMARTIR_JSON = "import_smartir_json"
SERVICE_SAVE_LEARNED_CODE = "save_learned_code"
SERVICE_SEND_CODE = "send_code"
SERVICE_SEND_SAVED_CODE = "send_saved_code"
SERVICE_START_LEARNING = "start_learning"

SIGNAL_NEW_IR_DEVICE = "z2m_otter_ir_new_ir_device_{}"
SIGNAL_IR_CODE_LEARNED = "z2m_otter_ir_ir_code_learned_{}"
SIGNAL_LIBRARY_UPDATED = "z2m_otter_ir_library_updated_{}"
SIGNAL_CATALOG_UPDATED = "z2m_otter_ir_catalog_updated_{}"
SIGNAL_IMPORT_FIELDS_UPDATED = "z2m_otter_ir_import_fields_updated_{}"
SIGNAL_PENDING_NAME_UPDATED = "z2m_otter_ir_pending_name_updated_{}"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_library"

IR_MODELS = {
    "ZS06",
    "TS1201",
    "TS120F",
    "TUYA_IR_BLASTER",
}

IR_KEYS = {
    "ir_code_to_send",
    "learn_ir_code",
    "learned_ir_code",
}

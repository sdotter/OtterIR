const PANEL_CSS_URL = "/z2m_otter_ir_static/otter-ir-panel.css?v=1.3.27";

class OtterIRPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._route = null;
    this._panel = null;
    this._loaded = false;
    this._loading = false;
    this._selectedDevice = "";
    this._search = "";
    this._catalogSearch = "";
    this._scope = "all";
    this._codeDialogOpen = false;
    this._editingCodeId = "";
    this._expandedGroups = {};
    this._toasts = [];
    this._toastSeq = 0;
    this._toastTimers = new Map();
    this._deferredRender = false;
    this._learnStatus = {};
    this._saveStatus = {};
    this._state = {
      devices: [],
      codes: [],
      catalog_sources: [],
      catalog_remotes: [],
    };
    this._form = {
      pending_name: "",
      import_library: "",
      csv_source: "",
      entity_id_base: "",
      smartir_source: "",
      save_shared: true,
      import_shared: true,
      catalog_source: "",
      catalog_name: "",
      catalog_max_files: "200",
    };
    this._codeForm = {
      name: "",
      entity_id: "",
      custom_entity_id: false,
      target_device: "",
    };
  }

  connectedCallback() {
    this.render();
    this.shadowRoot.addEventListener("click", (event) => this._handleClick(event));
    this.shadowRoot.addEventListener("input", (event) => this._handleInput(event));
    this.shadowRoot.addEventListener("change", (event) => this._handleChange(event));
    this.shadowRoot.addEventListener("toggle", (event) => this._handleToggle(event), true);
    this.shadowRoot.addEventListener("focusout", () => {
      window.setTimeout(() => this._flushDeferredRender(), 0);
    });
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded && !this._loading) {
      this._load();
      return;
    }
    if (this._isEditingTextField()) {
      this._deferredRender = true;
      this._syncActionButtonStates();
      return;
    }
    this.render();
  }

  set route(value) {
    this._route = value;
    this.render();
  }

  get route() {
    return this._route;
  }

  set panel(value) {
    this._panel = value;
  }

  get panel() {
    return this._panel;
  }

  set narrow(value) {
    const nextValue = Boolean(value);
    if (this._narrow === nextValue) {
      return;
    }
    this._narrow = nextValue;
    this.render();
  }

  get narrow() {
    return this._narrow;
  }

  async _load() {
    if (!this._hass || this._loading) {
      return;
    }

    this._loading = true;
    this.render();

    try {
      this._state = await this._hass.callWS({ type: "z2m_otter_ir/get_state" });
      if (!this._selectedDevice && this._state.devices.length) {
        this._selectedDevice = this._state.devices[0].friendly_name;
      }
      if (
        this._selectedDevice &&
        !this._state.devices.some(
          (device) => device.friendly_name === this._selectedDevice
        )
      ) {
        this._selectedDevice = this._state.devices[0]?.friendly_name || "";
      }
      this._syncLearnStatuses();
      this._syncFormFromDevice();
      this._loaded = true;
    } catch (err) {
      this._showToast(err?.message || String(err), "error");
    } finally {
      this._loading = false;
      this.render();
    }
  }

  _selectedDeviceData() {
    return this._state.devices.find(
      (device) => device.friendly_name === this._selectedDevice
    );
  }

  _syncFormFromDevice() {
    const device = this._selectedDeviceData();
    if (!device) {
      return;
    }
    this._form.pending_name = device.pending_name || "";
    this._form.import_library = device.import_library || "";
    this._form.csv_source = device.csv_source || "";
    this._form.smartir_source = device.smartir_source || "";
  }

  _effectiveLibrary() {
    return String(this._form.import_library || "").trim() || "default";
  }

  _renderLibraryField(label = "Library", copy = "") {
    return `
      <div class="field-stack">
        <label class="field">
          <span class="field-label">${this._escape(label)}</span>
          <input
            class="text-input"
            data-field="import_library"
            type="text"
            placeholder="default"
          />
        </label>
        ${
          copy
            ? `<div class="secondary">${copy}</div>`
            : ""
        }
      </div>
    `;
  }

  _activeEditableField() {
    const active = this.shadowRoot?.activeElement;
    if (!active?.dataset?.field) {
      return null;
    }
    if (!active.classList?.contains("text-input")) {
      return null;
    }
    return active;
  }

  _isEditingTextField() {
    return Boolean(this._activeEditableField());
  }

  _flushDeferredRender() {
    if (!this._deferredRender || this._isEditingTextField()) {
      return;
    }
    this._deferredRender = false;
    this.render();
  }

  _showToast(message, type = "success", duration = null) {
    if (!message) {
      return;
    }

    const id = ++this._toastSeq;
    const toast = {
      id,
      message: String(message),
      type,
    };
    this._toasts = [...this._toasts.filter((item) => item.id !== id), toast].slice(-4);
    this._syncToastLayer();

    const timeout = duration ?? (type === "error" ? 6500 : 3200);
    const timer = window.setTimeout(() => this._dismissToast(id), timeout);
    this._toastTimers.set(id, timer);
  }

  _dismissToast(id) {
    const timer = this._toastTimers.get(id);
    if (timer) {
      window.clearTimeout(timer);
      this._toastTimers.delete(id);
    }
    const nextToasts = this._toasts.filter((item) => item.id !== id);
    if (nextToasts.length === this._toasts.length) {
      return;
    }
    this._toasts = nextToasts;
    this._syncToastLayer();
  }

  _renderToasts() {
    if (!this._toasts.length) {
      return "";
    }

    return `
      <div class="toast-stack" aria-live="polite" aria-atomic="true">
        ${this._toasts
          .map(
            (toast) => `
              <div class="toast toast--${this._escape(toast.type)}" role="status">
                <div class="toast__icon" aria-hidden="true">
                  <ha-icon icon="${this._escape(this._toastIcon(toast.type))}"></ha-icon>
                </div>
                <div class="toast__body">
                  <span class="toast__message">${this._escape(toast.message)}</span>
                </div>
                <button
                  class="toast__close"
                  data-action="dismiss-toast"
                  data-toast-id="${String(toast.id)}"
                  aria-label="Dismiss notification"
                >
                  <ha-icon icon="mdi:close"></ha-icon>
                </button>
              </div>
            `
          )
          .join("")}
      </div>
    `;
  }

  _toastIcon(type) {
    switch (type) {
      case "error":
        return "mdi:alert-circle";
      case "success":
        return "mdi:check-circle";
      default:
        return "mdi:information";
    }
  }

  _syncToastLayer() {
    const host = this.shadowRoot?.querySelector("[data-toast-layer]");
    if (!host) {
      return;
    }
    host.innerHTML = this._renderToasts();
  }

  _ensureShell() {
    let appRoot = this.shadowRoot?.querySelector("[data-app-root]");
    if (appRoot) {
      return appRoot;
    }

    // Keep a stable shell in place so text inputs and toasts survive normal
    // panel refreshes without remounting the whole shadow DOM.
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${PANEL_CSS_URL}" />
      <div data-app-root></div>
      <div data-toast-layer></div>
    `;

    return this.shadowRoot.querySelector("[data-app-root]");
  }

  _slugify(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "code";
  }

  _entityIdExamples() {
    const device = this._selectedDeviceData();
    const base = this._slugify(device?.entity_id_base || device?.friendly_name || "");
    const current = device?.entity_ids || {};
    return {
      infrared: current.infrared || `infrared.${base}`,
      button: current.button || `button.${base}_learn_ir_code`,
      sensor: current.sensor || `sensor.${base}_last_learned_code`,
      event: current.event || `event.${base}_learned_signal`,
    };
  }

  _currentCodeRecord() {
    return (this._state.codes || []).find((record) => record.code_id === this._editingCodeId);
  }

  _codeTargetDevice(record) {
    if (!record) {
      return "";
    }
    if (record.friendly_name) {
      return record.friendly_name;
    }
    if (this._selectedDevice && record.default_entity_ids?.[this._selectedDevice]) {
      return this._selectedDevice;
    }
    return (
      Object.keys(record.default_entity_ids || {})[0] ||
      Object.keys(record.entity_ids || {})[0] ||
      ""
    );
  }

  _entityIdForRecord(record, targetDevice = this._codeTargetDevice(record)) {
    if (!record || !targetDevice) {
      return "";
    }
    return record.entity_ids?.[targetDevice] || record.default_entity_ids?.[targetDevice] || "";
  }

  _defaultEntityIdForRecord(record, targetDevice = this._codeTargetDevice(record)) {
    if (!record || !targetDevice) {
      return "";
    }
    return record.default_entity_ids?.[targetDevice] || "";
  }

  _hasCustomEntityId(record, targetDevice = this._codeTargetDevice(record)) {
    const current = this._entityIdForRecord(record, targetDevice);
    const fallback = this._defaultEntityIdForRecord(record, targetDevice);
    return Boolean(current) && Boolean(fallback) && current !== fallback;
  }

  _visibleCodes() {
    const query = this._search.trim().toLowerCase();

    return (this._state.codes || []).filter((record) => {
      if (this._scope === "shared" && !record.shared) {
        return false;
      }
      if (this._scope === "device" && record.friendly_name !== this._selectedDevice) {
        return false;
      }

      if (!query) {
        return true;
      }

      return [record.name, record.library, record.friendly_name || "", record.source || ""]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }

  _groupedCodes() {
    const groups = new Map();
    const ordered = [...this._visibleCodes()].sort((left, right) =>
      `${left.shared ? "0" : "1"}|${left.library}|${left.name}`.localeCompare(
        `${right.shared ? "0" : "1"}|${right.library}|${right.name}`
      )
    );

    for (const record of ordered) {
      const scope = record.shared ? "Shared library" : record.friendly_name || "Device";
      const key = `${scope}::${record.library}`;
      if (!groups.has(key)) {
        groups.set(key, {
          scope,
          title: record.library,
          records: [],
        });
      }
      groups.get(key).records.push(record);
    }

    return [...groups.values()];
  }

  _catalogQuery() {
    return this._catalogSearch.trim().toLowerCase();
  }

  _catalogText(remote) {
    return [
      remote.display_name,
      remote.brand,
      remote.category,
      remote.model,
      remote.source_name,
      remote.relative_path,
      ...(remote.preview_commands || []),
    ]
      .join(" ")
      .toLowerCase();
  }

  _sourceText(source) {
    return [source.source_name, source.source, source.origin_kind].join(" ").toLowerCase();
  }

  _catalogRemotesForSource(sourceKey) {
    const query = this._catalogQuery();
    return (this._state.catalog_remotes || []).filter((remote) => {
      if (remote.source_key !== sourceKey) {
        return false;
      }
      if (!query) {
        return true;
      }
      return this._catalogText(remote).includes(query);
    });
  }

  _visibleCatalogSources() {
    const query = this._catalogQuery();
    return (this._state.catalog_sources || []).filter((source) => {
      const matchingRemotes = this._catalogRemotesForSource(source.source_key);
      if (!query) {
        return matchingRemotes.length > 0 || Boolean(source.source_key);
      }
      return matchingRemotes.length > 0 || this._sourceText(source).includes(query);
    });
  }

  _groupKey(group) {
    return `${group.scope}::${group.title}`;
  }

  _catalogSourceGroupKey(source) {
    return `catalog-source::${source.source_key}`;
  }

  _catalogRemoteGroupKey(remote) {
    return `catalog-remote::${remote.remote_id}`;
  }

  _isGroupExpanded(key, defaultOpen = true) {
    if (!(key in this._expandedGroups)) {
      return defaultOpen;
    }
    return this._expandedGroups[key];
  }

  _summary() {
    const codes = this._state.codes || [];
    const remotes = this._state.catalog_remotes || [];
    const shared = codes.filter((record) => record.shared).length;
    const local = codes.length - shared;
    const supportedCatalogCommands = remotes.reduce(
      (sum, remote) => sum + (remote.supported_command_count || 0),
      0
    );
    return {
      devices: this._state.devices.length,
      shared,
      local,
      total: codes.length,
      catalogSources: (this._state.catalog_sources || []).length,
      catalogRemotes: remotes.length,
      supportedCatalogCommands,
    };
  }

  _syncLearnStatuses() {
    const activeDevices = new Set((this._state.devices || []).map((device) => device.friendly_name));
    for (const friendlyName of Object.keys(this._learnStatus)) {
      if (!activeDevices.has(friendlyName)) {
        delete this._learnStatus[friendlyName];
      }
    }

    for (const device of this._state.devices || []) {
      const status = this._learnStatus[device.friendly_name];
      if (!status) {
        continue;
      }

      const learnedAt = device.last_learned?.learned_at || "";
      if (status.state === "listening" && learnedAt && learnedAt !== (status.lastLearnedAt || "")) {
        this._learnStatus[device.friendly_name] = {
          state: "learned",
          text: "Code learned",
          lastLearnedAt: learnedAt,
        };
        continue;
      }

      this._learnStatus[device.friendly_name] = {
        ...status,
        lastLearnedAt: learnedAt || status.lastLearnedAt || "",
      };
    }
  }

  _learnStatusForDevice(device) {
    if (!device?.friendly_name) {
      return { state: "idle", text: "Idle" };
    }

    return (
      this._learnStatus[device.friendly_name] || {
        state: "idle",
        text: "Idle",
        lastLearnedAt: device.last_learned?.learned_at || "",
      }
    );
  }

  _saveStatusForDevice(device) {
    if (!device?.friendly_name) {
      return { state: "idle", text: "Idle" };
    }

    return (
      this._saveStatus[device.friendly_name] || {
        state: "idle",
        text: "Idle",
      }
    );
  }

  async _handleClick(event) {
    const button = this._actionTargetFromEvent(event);
    if (
      !button ||
      button.disabled ||
      button.hasAttribute?.("disabled") ||
      button.getAttribute?.("aria-disabled") === "true"
    ) {
      return;
    }

    const action = button.dataset.action;
    const codeId = button.dataset.codeId;
    const device = button.dataset.device;
    const scope = button.dataset.scope;
    const remoteId = button.dataset.remoteId;
    const sourceKey = button.dataset.sourceKey;
    const targetDevice = button.dataset.targetDevice;
    const toastId = button.dataset.toastId;

    try {
      if (action === "refresh") {
        await this._load();
        return;
      }

      if (action === "select-device") {
        this._selectedDevice = device || "";
        this._syncFormFromDevice();
        this.render();
        return;
      }

      if (action === "set-scope") {
        this._scope = scope || "all";
        this.render();
        return;
      }

      if (action === "dismiss-toast" && toastId) {
        this._dismissToast(Number(toastId));
        return;
      }

      if (action === "learn") {
        const currentLearnedAt =
          this._selectedDeviceData()?.last_learned?.learned_at || "";
        await this._callService("start_learning", {
          friendly_name: this._selectedDevice,
        });
        this._learnStatus[this._selectedDevice] = {
          state: "listening",
          text: "Listening...",
          lastLearnedAt: currentLearnedAt,
        };
        this.render();
        this._showToast("Learning mode started.", "info");
        await this._load();
        return;
      }

      if (action === "open-code-dialog" && codeId) {
        const record = this._state.codes.find((item) => item.code_id === codeId);
        if (!record) {
          throw new Error("Unknown command");
        }
        const targetDevice = this._codeTargetDevice(record);
        this._editingCodeId = codeId;
        this._codeDialogOpen = true;
        this._codeForm.name = record.name || "";
        this._codeForm.target_device = targetDevice;
        this._codeForm.entity_id = this._entityIdForRecord(record, targetDevice);
        this._codeForm.custom_entity_id = this._hasCustomEntityId(record, targetDevice);
        this.render();
        return;
      }

      if (action === "close-code-dialog") {
        this._codeDialogOpen = false;
        this._editingCodeId = "";
        this.render();
        return;
      }

      if (action === "save-code-dialog") {
        await this._hass.callWS({
          type: "z2m_otter_ir/update_code",
          current_code_id: this._editingCodeId,
          name: this._codeForm.name,
        });
        await this._hass.callWS({
          type: "z2m_otter_ir/update_code_entity_id",
          code_id: this._editingCodeId,
          friendly_name: this._codeForm.target_device,
          custom_entity_id: this._codeForm.custom_entity_id,
          entity_id: this._codeForm.custom_entity_id ? this._codeForm.entity_id : "",
        });
        this._codeDialogOpen = false;
        this._editingCodeId = "";
        this._showToast("Command updated.");
        await this._load();
        return;
      }

      if (action === "save-learned") {
        this._saveStatus[this._selectedDevice] = {
          state: "saving",
          text: "Saving...",
        };
        this.render();
        await this._persistDeviceSettings([
          "pending_name",
          "import_library",
          "csv_source",
          "smartir_source",
        ]);
        await this._callService("save_learned_code", {
          friendly_name: this._selectedDevice,
          name: this._form.pending_name,
          library: this._form.import_library || "default",
          shared: this._form.save_shared,
        });
        this._saveStatus[this._selectedDevice] = {
          state: "saved",
          text: "Saved",
        };
        this._showToast("Learned code saved.");
        this._form.pending_name = "";
        await this._persistDeviceSettings(["pending_name"]);
        await this._load();
        return;
      }

      if (action === "import-csv") {
        await this._persistDeviceSettings(["import_library", "csv_source"]);
        await this._callService("import_csv_commands", {
          friendly_name: this._selectedDevice,
          import_source: this._form.csv_source,
          library: this._form.import_library || undefined,
          shared: this._form.import_shared,
          overwrite: false,
        });
        this._showToast("CSV or TSV import completed.");
        await this._load();
        return;
      }

      if (action === "import-smartir") {
        await this._persistDeviceSettings(["import_library", "smartir_source"]);
        await this._callService("import_smartir_json", {
          friendly_name: this._selectedDevice,
          import_source: this._form.smartir_source,
          library: this._form.import_library || undefined,
          shared: this._form.import_shared,
          overwrite: false,
        });
        this._showToast("SmartIR import completed.");
        await this._load();
        return;
      }

      if (action === "import-flipper-source") {
        await this._callService("import_flipper_source", {
          import_source: this._form.catalog_source,
          catalog_name: this._form.catalog_name || undefined,
          max_files: Number(this._form.catalog_max_files || 200),
        });
        this._showToast("Catalog source imported.");
        await this._load();
        return;
      }

      if (action === "delete-catalog-source" && sourceKey) {
        if (!window.confirm("Remove this catalog source and all imported remotes?")) {
          return;
        }
        await this._callService("delete_catalog_source", { source_key: sourceKey });
        this._showToast("Catalog source removed.");
        await this._load();
        return;
      }

      if (action === "import-catalog-shared" && remoteId) {
        const remote = this._state.catalog_remotes.find((item) => item.remote_id === remoteId);
        await this._callService("import_catalog_remote", {
          remote_id: remoteId,
          library: this._form.import_library || remote?.library_hint || undefined,
          shared: true,
          overwrite: false,
        });
        this._showToast("Catalog remote imported to the shared library.");
        await this._load();
        return;
      }

      if (action === "import-catalog-device" && remoteId) {
        const remote = this._state.catalog_remotes.find((item) => item.remote_id === remoteId);
        await this._callService("import_catalog_remote", {
          remote_id: remoteId,
          friendly_name: this._selectedDevice,
          library: this._form.import_library || remote?.library_hint || undefined,
          shared: false,
          overwrite: false,
        });
        this._showToast("Catalog remote imported to the current device.");
        await this._load();
        return;
      }

      if (action === "send-code" && codeId) {
        await this._callService("send_saved_code", {
          code_id: codeId,
          friendly_name: targetDevice || this._selectedDevice,
        });
        this._showToast("Code sent.", "info");
        return;
      }

      if (action === "delete-code" && codeId) {
        if (!window.confirm("Delete this saved code?")) {
          return;
        }
        await this._callService("delete_code", { code_id: codeId });
        this._showToast("Code removed.");
        await this._load();
      }
    } catch (err) {
      if (action === "learn" && this._selectedDevice) {
        this._learnStatus[this._selectedDevice] = {
          state: "error",
          text: "Start failed",
          lastLearnedAt: this._selectedDeviceData()?.last_learned?.learned_at || "",
        };
        this.render();
      }
      if (action === "save-learned" && this._selectedDevice) {
        this._saveStatus[this._selectedDevice] = {
          state: "error",
          text: "Save failed",
        };
        this.render();
      }
      this._showToast(err?.message || String(err), "error");
    }
  }

  _actionTargetFromEvent(event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    const insideDialogContent = path.some(
      (item) =>
        item &&
        typeof item === "object" &&
        item.classList?.contains?.("dialog-content")
    );
    for (const item of path) {
      if (
        insideDialogContent &&
        item &&
        typeof item === "object" &&
        item.classList?.contains?.("dialog-backdrop")
      ) {
        continue;
      }
      if (item && typeof item === "object" && item.dataset?.action) {
        return item;
      }
    }
    const target = event.target;
    if (target?.dataset?.action) {
      return target;
    }
    return null;
  }

  _fieldTargetFromEvent(event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    for (const item of path) {
      if (item && typeof item === "object" && item.dataset?.field) {
        return item;
      }
    }
    const target = event.target;
    if (target?.dataset?.field) {
      return target;
    }
    return null;
  }

  _handleInput(event) {
    const target = this._fieldTargetFromEvent(event);
    const field = target?.dataset?.field;
    if (!field) {
      return;
    }

    if (field === "search") {
      this._search = target.value || "";
      this.render();
      return;
    }

    if (field === "catalog_search") {
      this._catalogSearch = target.value || "";
      this.render();
      return;
    }

    if (field === "custom_entity_id") {
      this._codeForm.custom_entity_id = Boolean(target.checked);
      if (!this._codeForm.custom_entity_id) {
        const record = this._currentCodeRecord();
        this._codeForm.entity_id = this._defaultEntityIdForRecord(
          record,
          this._codeForm.target_device
        );
      }
      this.render();
      return;
    }

    const value = target.type === "checkbox" ? target.checked : target.value;
    if (field === "code_name") {
      this._codeForm.name = value ?? "";
      this._syncActionButtonStates();
      return;
    }
    if (field === "entity_id_input") {
      this._codeForm.entity_id = value ?? "";
      this._syncActionButtonStates();
      return;
    }
    this._form[field] = value ?? "";
    this._syncActionButtonStates();
  }

  async _handleChange(event) {
    const target = this._fieldTargetFromEvent(event);
    const field = target?.dataset?.field;
    if (!field) {
      return;
    }

    const value =
      target.type === "checkbox" || target.tagName?.toLowerCase() === "ha-checkbox"
        ? Boolean(target.checked)
        : target.value;

    if (field === "custom_entity_id") {
      this._codeForm.custom_entity_id = Boolean(value);
      if (!this._codeForm.custom_entity_id) {
        const record = this._currentCodeRecord();
        this._codeForm.entity_id = this._defaultEntityIdForRecord(
          record,
          this._codeForm.target_device
        );
      }
      this.render();
      return;
    }

    if (field === "save_shared" || field === "import_shared") {
      this._form[field] = Boolean(value);
      this.render();
      return;
    }

    if (
      ["pending_name", "import_library", "csv_source", "smartir_source"].includes(field)
    ) {
      this._form[field] = value ?? "";
      try {
        await this._persistDeviceSettings([field]);
      } catch (err) {
        this._showToast(err?.message || String(err), "error");
      }
    }
  }

  _handleToggle(event) {
    const details = event.target;
    if (!(details instanceof HTMLElement) || !details.matches("details[data-group-key]")) {
      return;
    }
    this._expandedGroups[details.dataset.groupKey] = details.open;
  }

  async _persistDeviceSettings(fields) {
    if (!this._selectedDevice || !this._hass) {
      return;
    }

    const payload = {
      type: "z2m_otter_ir/set_device_settings",
      friendly_name: this._selectedDevice,
    };
    for (const field of fields) {
      payload[field] = this._form[field] || "";
    }
    this._state = await this._hass.callWS(payload);
  }

  async _callService(service, data) {
    await this._hass.callService("z2m_otter_ir", service, data);
  }

  _renderCodeDialog() {
    const record = this._currentCodeRecord();
    if (!this._codeDialogOpen || !record) {
      return "";
    }

    const targetDevice = this._codeForm.target_device || this._codeTargetDevice(record);
    const defaultEntityId = this._defaultEntityIdForRecord(record, targetDevice);
    const currentEntityId = this._codeForm.entity_id || defaultEntityId;

    return `
      <div class="dialog-backdrop" data-action="close-code-dialog">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="Edit command">
          <div class="dialog-content">
            <h2 class="dialog-title">Edit command</h2>
            <div class="dialog-copy">
              Update the command name and the real Home Assistant button entity ID.
            </div>
            <div class="detail-grid">
              <div class="detail-chip"><span>Library</span><strong>${this._escape(
                record.library
              )}</strong></div>
              <div class="detail-chip"><span>Target device</span><strong>${this._escape(
                targetDevice || "Unavailable"
              )}</strong></div>
            </div>
            <label class="field">
              <span class="field-label">Command name</span>
              <input
                class="text-input"
                data-field="code_name"
                type="text"
                value="${this._escape(this._codeForm.name)}"
              />
            </label>
            <div class="secondary">
              Internal command ID: <code>${this._escape(record.code_id)}</code>
            </div>
            <ha-formfield class="toggle-field" label="Custom Home Assistant entity ID">
              <ha-checkbox
                class="toggle-input"
                data-field="custom_entity_id"
                ${this._codeForm.custom_entity_id ? "checked" : ""}
              ></ha-checkbox>
            </ha-formfield>
            <label class="field">
              <span class="field-label">Button entity ID</span>
              <input
                class="text-input"
                data-field="entity_id_input"
                type="text"
                value="${this._escape(currentEntityId)}"
                ${this._codeForm.custom_entity_id ? "" : "disabled"}
              />
            </label>
            <div class="secondary">
              ${
                this._codeForm.custom_entity_id
                  ? "When enabled, OtterIR updates the actual Home Assistant entity_id for this saved-command button."
                  : `When disabled, OtterIR uses the default entity ID: ${this._escape(
                      defaultEntityId || "button entity not available"
                    )}`
              }
            </div>
            <div class="dialog-actions">
              <button class="theme-button" data-action="close-code-dialog">Cancel</button>
              <button
                class="theme-button primary-action"
                data-action="save-code-dialog"
                ${!this._codeForm.name.trim() || !targetDevice || (this._codeForm.custom_entity_id && !this._codeForm.entity_id.trim()) ? "disabled" : ""}
              >
                Save command
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _formatLearned(learned) {
    if (!learned) {
      return "No learned code yet";
    }
    const when = learned.learned_at
      ? new Date(learned.learned_at).toLocaleString()
      : "unknown";
    return `${learned.code_hash || learned.code?.slice(0, 12) || "learned"} - ${when}`;
  }

  _escape(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  _captureFocusState() {
    const active = this.shadowRoot?.activeElement;
    if (!active?.dataset?.field) {
      return null;
    }

    const matches = Array.from(
      this.shadowRoot.querySelectorAll(`[data-field="${active.dataset.field}"]`)
    );

    return {
      field: active.dataset.field,
      index: Math.max(0, matches.indexOf(active)),
      selectionStart:
        typeof active.selectionStart === "number" ? active.selectionStart : null,
      selectionEnd: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
    };
  }

  _restoreFocusState(focusState) {
    if (!focusState?.field) {
      return;
    }

    const matches = Array.from(
      this.shadowRoot.querySelectorAll(`[data-field="${focusState.field}"]`)
    );
    const element = matches[focusState.index || 0] || matches[0];
    if (!element || element.disabled) {
      return;
    }

    if (typeof element.focus === "function") {
      element.focus({ preventScroll: true });
    }

    if (
      typeof focusState.selectionStart === "number" &&
      typeof focusState.selectionEnd === "number" &&
      typeof element.setSelectionRange === "function"
    ) {
      try {
        element.setSelectionRange(
          focusState.selectionStart,
          focusState.selectionEnd
        );
      } catch (_err) {
        // Ignore selection restore failures for non-text-like inputs.
      }
    }
  }

  _syncActionButtonStates() {
    const saveLearnedButton = this.shadowRoot.querySelector(
      '[data-action="save-learned"]'
    );
    if (saveLearnedButton) {
      saveLearnedButton.disabled =
        !this._selectedDevice || !String(this._form.pending_name || "").trim();
    }

    const importCsvButton = this.shadowRoot.querySelector(
      '[data-action="import-csv"]'
    );
    if (importCsvButton) {
      importCsvButton.disabled =
        !this._selectedDevice || !String(this._form.csv_source || "").trim();
    }

    const importSmartIrButton = this.shadowRoot.querySelector(
      '[data-action="import-smartir"]'
    );
    if (importSmartIrButton) {
      importSmartIrButton.disabled =
        !this._selectedDevice || !String(this._form.smartir_source || "").trim();
    }

    const importCatalogButton = this.shadowRoot.querySelector(
      '[data-action="import-flipper-source"]'
    );
    if (importCatalogButton) {
      importCatalogButton.disabled = !String(this._form.catalog_source || "").trim();
    }

    const saveCodeButton = this.shadowRoot.querySelector(
      '[data-action="save-code-dialog"]'
    );
    if (saveCodeButton) {
      const targetDevice = this._codeForm.target_device;
      saveCodeButton.disabled =
        !String(this._codeForm.name || "").trim() ||
        !targetDevice ||
        (this._codeForm.custom_entity_id &&
          !String(this._codeForm.entity_id || "").trim());
    }
  }

  _syncComponentValues() {
    const syncTextField = (field, value) => {
      this.shadowRoot
        .querySelectorAll(`.text-input[data-field="${field}"]`)
        .forEach((element) => {
          element.value = value || "";
        });
    };

    const syncSwitch = (field, value) => {
      this.shadowRoot
        .querySelectorAll(`.toggle-input[data-field="${field}"]`)
        .forEach((element) => {
          element.checked = Boolean(value);
        });
    };

    syncTextField("search", this._search);
    syncTextField("catalog_search", this._catalogSearch);
    syncTextField("code_name", this._codeForm.name);
    syncTextField("entity_id_input", this._codeForm.entity_id);
    syncTextField("pending_name", this._form.pending_name);
    syncTextField("import_library", this._form.import_library);
    syncTextField("csv_source", this._form.csv_source);
    syncTextField("smartir_source", this._form.smartir_source);
    syncTextField("catalog_source", this._form.catalog_source);
    syncTextField("catalog_name", this._form.catalog_name);
    syncTextField("catalog_max_files", this._form.catalog_max_files);
    syncSwitch("custom_entity_id", this._codeForm.custom_entity_id);
    syncSwitch("save_shared", this._form.save_shared);
    syncSwitch("import_shared", this._form.import_shared);
    this._syncActionButtonStates();
  }

  _renderDeviceButtons() {
    return this._state.devices
      .map(
        (item) => `
          <button
            class="list-button ${item.friendly_name === this._selectedDevice ? "active" : ""}"
            data-action="select-device"
            data-device="${this._escape(item.friendly_name)}"
          >
            <div class="list-button__text">
              <span class="primary">${this._escape(item.friendly_name)}</span>
              <span class="secondary">${this._escape(item.model || "Unknown model")}</span>
            </div>
            <span class="badge">${item.saved_count}</span>
          </button>
        `
      )
      .join("");
  }

  _renderCodeGroups(hasDevice) {
    const groups = this._groupedCodes();
    if (!groups.length) {
      return `<div class="empty-state">No saved commands yet. Save a learned signal or import a remote.</div>`;
    }

    return groups
      .map((group) => {
        const groupKey = this._groupKey(group);
        return `
          <details class="group-card" data-group-key="${this._escape(groupKey)}" ${
            this._isGroupExpanded(groupKey, true) ? "open" : ""
          }>
            <summary class="group-card__summary">
              <div class="group-card__header">
                <div>
                  <div class="meta-label">${this._escape(group.scope)}</div>
                  <h3>${this._escape(group.title)}</h3>
                </div>
                <div class="group-card__summary-meta">
                  <span class="badge">${group.records.length}</span>
                  <ha-icon class="summary-chevron" icon="mdi:chevron-down"></ha-icon>
                </div>
              </div>
            </summary>
            <div class="rows">
              ${group.records
                .map((record) => {
                  const targetDevice = this._codeTargetDevice(record);
                  const entityId = this._entityIdForRecord(record, targetDevice);
                  const entitySubtitle = targetDevice
                    ? `${targetDevice}: ${entityId || "button entity pending"}`
                    : "No target device available";
                  return `
                    <div class="row">
                      <div class="row__text">
                        <span class="primary">${this._escape(record.name)}</span>
                        <span class="secondary">${this._escape(entitySubtitle)}</span>
                      </div>
                      <div class="row__actions">
                        <button class="theme-button" data-action="open-code-dialog" data-code-id="${this._escape(record.code_id)}">Edit</button>
                        <button class="theme-button" data-action="send-code" data-code-id="${this._escape(record.code_id)}" data-target-device="${this._escape(targetDevice)}" ${
                          !targetDevice ? "disabled" : ""
                        }>Send</button>
                        <button class="theme-button danger" data-action="delete-code" data-code-id="${this._escape(record.code_id)}">Delete</button>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </details>
        `;
      })
      .join("");
  }

  _renderCatalogSources(hasDevice) {
    const sources = this._visibleCatalogSources();
    if (!sources.length) {
      return `<div class="empty-state">No catalog sources imported yet. Add a GitHub folder, repo, local directory, or a single .ir file.</div>`;
    }

    return sources
      .map((source) => {
        const sourceKey = this._catalogSourceGroupKey(source);
        const remotes = this._catalogRemotesForSource(source.source_key);
        return `
          <details class="group-card" data-group-key="${this._escape(sourceKey)}" ${
            this._isGroupExpanded(sourceKey, true) ? "open" : ""
          }>
            <summary class="group-card__summary">
              <div class="group-card__header">
                <div>
                  <div class="meta-label">${this._escape(source.origin_kind || "catalog")}</div>
                  <h3>${this._escape(source.source_name || source.source_key)}</h3>
                  <div class="secondary source-line">${this._escape(source.source || "")}</div>
                </div>
                <div class="group-card__summary-meta">
                  ${source.truncated ? `<span class="pill warn">limited</span>` : ""}
                  <span class="badge">${remotes.length}</span>
                  <ha-icon class="summary-chevron" icon="mdi:chevron-down"></ha-icon>
                </div>
              </div>
            </summary>
            <div class="catalog-group-body">
              <div class="row row--meta">
                <div class="row__text">
                  <span class="primary">Imported remotes</span>
                  <span class="secondary">${source.remote_count || remotes.length} total${
                    source.truncated ? " - import was limited by max files" : ""
                  }</span>
                </div>
                <div class="row__actions">
                  <button class="theme-button danger" data-action="delete-catalog-source" data-source-key="${this._escape(
                    source.source_key
                  )}">Remove source</button>
                </div>
              </div>
              <div class="remote-stack">
                ${remotes
                  .map((remote) => {
                    const remoteKey = this._catalogRemoteGroupKey(remote);
                    const preview = (remote.preview_commands || [])
                      .map((name) => `<span class="pill">${this._escape(name)}</span>`)
                      .join("");
                    const subtitleParts = [
                      remote.category || "unknown",
                      remote.brand || "unknown",
                      `${remote.supported_command_count || 0}/${remote.command_count || 0} supported`,
                    ];
                    return `
                      <details class="nested-group" data-group-key="${this._escape(remoteKey)}" ${
                        this._isGroupExpanded(remoteKey, false) ? "open" : ""
                      }>
                        <summary class="nested-group__summary">
                          <div class="row__text">
                            <span class="primary">${this._escape(
                              remote.display_name || remote.model || remote.relative_path
                            )}</span>
                            <span class="secondary">${this._escape(subtitleParts.join(" - "))}</span>
                          </div>
                          <div class="group-card__summary-meta">
                            <span class="badge">${remote.supported_command_count || 0}</span>
                            <ha-icon class="summary-chevron" icon="mdi:chevron-down"></ha-icon>
                          </div>
                        </summary>
                        <div class="nested-group__body">
                          <div class="detail-grid">
                            <div class="detail-chip"><span>Library hint</span><strong>${this._escape(
                              remote.library_hint || "default"
                            )}</strong></div>
                            <div class="detail-chip"><span>Path</span><strong>${this._escape(
                              remote.relative_path || "-"
                            )}</strong></div>
                          </div>
                          ${
                            preview
                              ? `<div class="pill-row">${preview}</div>`
                              : `<div class="secondary">No preview commands available.</div>`
                          }
                          <div class="row__actions">
                            <button class="theme-button" data-action="import-catalog-shared" data-remote-id="${this._escape(
                              remote.remote_id
                            )}">Import to shared</button>
                            <button class="theme-button primary-action" data-action="import-catalog-device" data-remote-id="${this._escape(
                              remote.remote_id
                            )}" ${!hasDevice ? "disabled" : ""}>Import to current device</button>
                          </div>
                        </div>
                      </details>
                    `;
                  })
                  .join("")}
              </div>
            </div>
          </details>
        `;
      })
      .join("");
  }

  render() {
    const focusState = this._captureFocusState();
    const device = this._selectedDeviceData();
    const learnStatus = this._learnStatusForDevice(device);
    const saveStatus = this._saveStatusForDevice(device);
    const summary = this._summary();
    const hasDevice = Boolean(device);
    const deviceButtons = this._renderDeviceButtons();
    const codeGroups = this._renderCodeGroups(hasDevice);
    const catalogGroups = this._renderCatalogSources(hasDevice);

    // Only the app root is rerendered; the toast host above it remains mounted
    // so notifications can animate independently from the main page content.
    const appRoot = this._ensureShell();
    appRoot.innerHTML = `
      <div class="app-header">
        <div class="app-header__brand">
          <div class="app-header__icon">
            <ha-icon icon="mdi:remote"></ha-icon>
          </div>
          <div class="app-header__title-wrap">
            <h1 class="app-header__title">OtterIR</h1>
          </div>
        </div>
        <div class="app-header__stats">
          <span class="app-header__chip">${summary.total} commands</span>
          <span class="app-header__chip">${summary.devices} devices</span>
        </div>
      </div>
      <div class="page ${this._loading ? "loading" : ""}">
            <div class="page-header">
              <div>
                <p class="page-subtitle">Keep your own commands clean, while browsing larger IR databases as separate catalogs that you can selectively import into shared or device-specific libraries.</p>
              </div>
              <div class="header-tools">
                <input
                  class="text-input"
                  data-field="search"
                  type="text"
                  placeholder="Search saved commands"
                />
                <button class="theme-button" data-action="refresh">Refresh</button>
              </div>
            </div>

          <div class="summary-grid">
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.devices}</span>
              <span class="summary-label">IR devices</span>
            </div>
          </ha-card>
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.total}</span>
              <span class="summary-label">Saved commands</span>
            </div>
          </ha-card>
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.shared}</span>
              <span class="summary-label">Shared commands</span>
            </div>
          </ha-card>
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.local}</span>
              <span class="summary-label">Device commands</span>
            </div>
          </ha-card>
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.catalogSources}</span>
              <span class="summary-label">Catalog sources</span>
            </div>
          </ha-card>
          <ha-card class="summary-card">
            <div class="card-content">
              <span class="summary-value">${summary.catalogRemotes}</span>
              <span class="summary-label">Catalog remotes</span>
            </div>
          </ha-card>
          </div>

          <div class="layout">
            <div class="stack">
              <ha-card header="Devices">
                <div class="card-content">
                  <p class="section-copy">Choose the IR blaster you want to learn from or send with.</p>
                  <div class="rows">
                    ${deviceButtons || `<div class="empty-state">No IR devices found.</div>`}
                  </div>
                </div>
              </ha-card>

              <ha-card header="Current Device">
                <div class="card-content">
                  ${
                    device
                      ? `
                      <p class="section-copy">${this._escape(device.friendly_name)}</p>
                      <div class="details-grid">
                        <div class="detail">
                          <dt>Model</dt>
                          <dd>${this._escape(device.model || "Unknown")}</dd>
                        </div>
                        <div class="detail">
                          <dt>Manufacturer</dt>
                          <dd>${this._escape(device.manufacturer || "Unknown")}</dd>
                        </div>
                        <div class="detail">
                          <dt>Last learned</dt>
                          <dd>${this._escape(this._formatLearned(device.last_learned))}</dd>
                        </div>
                      <div class="detail">
                        <dt>Saved commands</dt>
                        <dd>${device.saved_count}</dd>
                      </div>
                      </div>
                      <div class="secondary">Saved commands become real Home Assistant button entities. Use the library list below to rename each command and adjust its HA entity ID.</div>
                      <div class="form-actions">
                        <button class="theme-button primary-action" data-action="learn">Learn IR code</button>
                        <span class="learn-status learn-status--${this._escape(learnStatus.state)}">
                          <span class="learn-status__dot" aria-hidden="true"></span>
                          ${this._escape(learnStatus.text)}
                        </span>
                      </div>
                    `
                      : `<div class="empty-state">Select a device to continue.</div>`
                  }
                </div>
              </ha-card>

              <ha-card header="Learn and Save">
                <div class="card-content">
                  <p class="section-copy">Save the last learned signal into a shared library or a device-only library.</p>
                  <div class="field-grid">
                    <label class="field">
                      <span class="field-label">Command name</span>
                      <input
                      class="text-input"
                      data-field="pending_name"
                      type="text"
                      placeholder="e.g. TV Power"
                    />
                    </label>
                    ${this._renderLibraryField(
                      "Library",
                      "This same library name is also used by CSV, SmartIR JSON, and catalog imports below."
                    )}
                    <ha-formfield class="toggle-field" label="Save to shared library">
                      <ha-checkbox class="toggle-input" data-field="save_shared"></ha-checkbox>
                    </ha-formfield>
                  </div>
                  <div class="form-actions">
                    <button class="theme-button primary-action" data-action="save-learned" ${
                      !hasDevice || !this._form.pending_name.trim() ? "disabled" : ""
                    }>Save learned code</button>
                    <span class="learn-status learn-status--${this._escape(saveStatus.state)}">
                      <span class="learn-status__dot" aria-hidden="true"></span>
                      ${this._escape(saveStatus.text)}
                    </span>
                  </div>
                </div>
              </ha-card>

              <ha-card header="Quick Imports">
                <div class="card-content">
                  <p class="section-copy">Import a CSV/TSV list or a SmartIR JSON file straight into the selected library.</p>
                  <div class="field-grid">
                    <div class="import-field-stack">
                      ${this._renderLibraryField(
                        "Target library",
                        `Imported commands from CSV/TSV and SmartIR JSON go into <strong>${this._escape(
                          this._effectiveLibrary()
                        )}</strong>.`
                      )}
                      <label class="field">
                        <span class="field-label">CSV or TSV source</span>
                        <input
                        class="text-input"
                        data-field="csv_source"
                        type="text"
                        placeholder="/config/my_ir_codes.csv or https://..."
                      />
                      </label>
                      <label class="field">
                        <span class="field-label">SmartIR JSON source</span>
                        <input
                        class="text-input"
                        data-field="smartir_source"
                        type="text"
                        placeholder="/config/1388.json, raw.githubusercontent.com/...json, or github.com/.../blob/...json"
                      />
                      </label>
                    </div>
                    <ha-formfield class="toggle-field" label="Import as shared library">
                      <ha-checkbox class="toggle-input" data-field="import_shared"></ha-checkbox>
                    </ha-formfield>
                  </div>
                  <div class="secondary">Use a local <code>.json</code> file, a GitHub <code>blob</code> URL, or a direct <code>raw.githubusercontent.com</code> SmartIR JSON URL.</div>
                  <div class="form-actions">
                    <button class="theme-button" data-action="import-csv" ${
                      !hasDevice || !this._form.csv_source.trim() ? "disabled" : ""
                    }>Import CSV or TSV</button>
                    <button class="theme-button" data-action="import-smartir" ${
                      !hasDevice || !this._form.smartir_source.trim() ? "disabled" : ""
                    }>Import SmartIR JSON</button>
                  </div>
                </div>
              </ha-card>
            </div>

            <div class="main-stack">
              <ha-card header="Catalogs">
                <div class="card-content">
                  <p class="section-copy">Import a large IR database source first. After that, the remotes appear below and you can selectively copy them into your shared or device library.</p>
                  <div class="field-grid">
                    <div class="import-field-stack">
                      ${this._renderLibraryField(
                        "Target library",
                        `When you import a remote from the catalog list below, OtterIR saves the commands into <strong>${this._escape(
                          this._effectiveLibrary()
                        )}</strong>.`
                      )}
                      <label class="field">
                        <span class="field-label">Catalog source</span>
                        <input
                        class="text-input"
                        data-field="catalog_source"
                        type="text"
                        placeholder="Examples: TVs/LG, https://github.com/Lucaslhm/Flipper-IRDB/tree/main/TVs/LG, /config/ir/LG.ir"
                      />
                      </label>
                    </div>
                    <div class="field-grid field-grid--two">
                      <label class="field">
                        <span class="field-label">Optional catalog name</span>
                        <input
                        class="text-input"
                        data-field="catalog_name"
                        type="text"
                        placeholder="e.g. LG TVs"
                      />
                      </label>
                      <label class="field">
                        <span class="field-label">Max files</span>
                        <input
                        class="text-input"
                        data-field="catalog_max_files"
                        type="number"
                        placeholder="200"
                      />
                      </label>
                    </div>
                  </div>
                  <div class="form-actions">
                    <button class="theme-button primary-action" data-action="import-flipper-source" ${
                      !this._form.catalog_source.trim() ? "disabled" : ""
                    }>Import catalog source</button>
                  </div>
                  <label class="field">
                    <span class="field-label">Search catalog remotes</span>
                    <input
                    class="text-input"
                    data-field="catalog_search"
                    type="text"
                    placeholder="Search imported catalog remotes"
                  />
                  </label>
                  <div class="secondary">How to import: paste a GitHub folder/repo URL, a single raw <code>.ir</code> file URL, or a local file/folder under <code>/config</code>, then click <strong>Import catalog source</strong>.</div>
                  ${catalogGroups}
                </div>
              </ha-card>

              <ha-card header="Library">
                <div class="card-content">
                  <p class="section-copy">Browse, filter, send, and delete saved commands.</p>
                  <div class="filter-bar">
                    <button class="theme-button ${this._scope === "all" ? "active" : ""}" data-action="set-scope" data-scope="all">All</button>
                    <button class="theme-button ${this._scope === "shared" ? "active" : ""}" data-action="set-scope" data-scope="shared">Shared</button>
                    <button class="theme-button ${this._scope === "device" ? "active" : ""}" data-action="set-scope" data-scope="device" ${
                      !hasDevice ? "disabled" : ""
                    }>Current device</button>
                  </div>
                  ${codeGroups}
                </div>
              </ha-card>
            </div>
          </div>
        ${this._renderCodeDialog()}
      </div>
    `;

    this._syncComponentValues();
    this._syncToastLayer();
    this._restoreFocusState(focusState);
  }
}

customElements.define("otter-ir-panel", OtterIRPanel);

"""VST/AU parameter editor panel for the optional desktop shell."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QWidget,
)

from audiocli.gui.theme import repolish
from audiocli.vst_params import normalize_param_entries, snapshot_to_param_entries

VST_CAPABILITY_ID = "builtin.external_plugin.vst"
VST_PARAMETER_PAGE_SIZE = 24


class VstEditorPanel:
    """Render and host VST/AU-specific controls inside the main parameter form."""

    def __init__(
        self,
        *,
        service: Any,
        parent: QWidget,
        test_safe: bool = False,
        host_controller_factory: Callable[[], Any] | None = None,
        is_refreshing: Callable[[], bool],
        refresh_chain_list: Callable[[], None],
        refresh_parameter_panel: Callable[[], None],
    ) -> None:
        self.service = service
        self._parent = parent
        self.test_safe = test_safe
        self._host_controller_factory = host_controller_factory
        self._is_refreshing = is_refreshing
        self._refresh_chain_list = refresh_chain_list
        self._refresh_parameter_panel = refresh_parameter_panel

        self._host_controller: Any | None = None
        self._host_node_id: str | None = None
        self._parameter_snapshots: dict[str, list[dict[str, Any]]] = {}
        self._parameter_pages: dict[str, int] = {}
        self._status_by_node: dict[str, tuple[str, str]] = {}
        self._host_status_label: QLabel | None = None
        self._open_editor_button: QPushButton | None = None
        self._discovered_plugins: list[dict[str, Any]] | None = None

    def render(self, form: QFormLayout, node: Any, capability: Any) -> dict[str, QWidget]:
        """Append VST controls to ``form`` and return parameter widgets by name."""

        parameter_widgets: dict[str, QWidget] = {}
        plugin_path_parameter = next(
            (parameter for parameter in capability.parameters if parameter.name == "plugin_path"),
            None,
        )

        def update_plugin_path(new_value: Any) -> None:
            if self._is_refreshing():
                return
            self.service.update_selected_param("plugin_path", new_value)
            self._refresh_chain_list()

        if plugin_path_parameter is not None:
            form.addRow(
                "Detected",
                self._build_plugin_picker(str(node.params.get("plugin_path") or "")),
            )
            path_widget = self._path_parameter_widget(
                "plugin_path",
                node.params.get("plugin_path", plugin_path_parameter.default),
                update_plugin_path,
            )
            form.addRow(
                plugin_path_parameter.display_name
                + (" *" if plugin_path_parameter.required else ""),
                path_widget,
            )
            parameter_widgets["plugin_path"] = path_widget

        host_row = QWidget()
        host_layout = QHBoxLayout(host_row)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(8)

        open_button = QPushButton("Open Editor")
        open_button.setObjectName("open_vst_editor_button")
        open_button.setIcon(self._standard_icon("SP_MediaPlay"))
        open_button.setProperty("role", "accent")
        open_button.setEnabled(self._host_node_id != node.id)
        open_button.clicked.connect(self._open_selected_editor)
        host_layout.addWidget(open_button)
        self._open_editor_button = open_button

        status_label = QLabel()
        status_label.setObjectName("vst_host_status")
        status_label.setWordWrap(True)
        message, state = self._status_by_node.get(
            node.id,
            ("Ready when a plugin path is set.", "idle"),
        )
        status_label.setText(message)
        status_label.setProperty("state", state)
        host_layout.addWidget(status_label, 1)
        self._host_status_label = status_label
        form.addRow("Editor", host_row)

        snapshot = self._parameter_snapshots.get(node.id, [])
        if not snapshot:
            hint = QLabel("No mirrored parameters yet.")
            hint.setObjectName("vst_parameter_empty_hint")
            hint.setProperty("role", "emptyState")
            hint.setWordWrap(True)
            form.addRow(hint)
            return parameter_widgets

        page_count = max(
            1, (len(snapshot) + VST_PARAMETER_PAGE_SIZE - 1) // VST_PARAMETER_PAGE_SIZE
        )
        page = min(max(0, self._parameter_pages.get(node.id, 0)), page_count - 1)
        self._parameter_pages[node.id] = page
        start = page * VST_PARAMETER_PAGE_SIZE
        end = min(start + VST_PARAMETER_PAGE_SIZE, len(snapshot))
        form.addRow(
            "Parameters",
            self._build_parameter_pager(node.id, page, page_count, start, end, len(snapshot)),
        )
        form.addRow(self._build_parameter_scroll(snapshot[start:end]))
        return parameter_widgets

    def stop_host(self) -> None:
        """Stop the helper process if an editor host has been created."""

        if self._host_controller is not None:
            self._host_controller.stop()

    def _build_plugin_picker(self, current_path: str) -> QWidget:
        container = QWidget()
        container.setObjectName("vst_detected_plugin_picker")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        combo = QComboBox()
        combo.setObjectName("vst_detected_plugin_combo")
        combo.addItem("Select detected plugin", "")
        discovered = self._plugin_scan_results()
        for plugin in discovered:
            label = _plugin_picker_label(plugin)
            combo.addItem(label, str(plugin.get("path") or ""))

        current_index = combo.findData(current_path)
        if current_index >= 0:
            combo.setCurrentIndex(current_index)
        combo.setEnabled(bool(discovered))
        combo.currentIndexChanged.connect(lambda _index, c=combo: self._select_plugin(c))
        layout.addWidget(combo, 1)

        refresh_button = QPushButton()
        refresh_button.setObjectName("refresh_vst_plugins_button")
        self._configure_icon_button(
            refresh_button,
            "SP_BrowserReload",
            "Refresh detected plugins",
            fallback=QStyle.StandardPixmap.SP_BrowserReload,
        )
        refresh_button.clicked.connect(self._refresh_plugins)
        layout.addWidget(refresh_button)
        return container

    def _plugin_scan_results(self) -> list[dict[str, Any]]:
        if self._discovered_plugins is not None:
            return self._discovered_plugins
        try:
            from audiocli.plugin_discovery import discover_default_plugins  # noqa: PLC0415

            discovered = discover_default_plugins()
        except Exception as exc:
            self._discovered_plugins = []
            self._set_status(
                self.service.selected_node_id,
                f"Plugin scan failed: {exc}",
                "warning",
            )
            return self._discovered_plugins
        self._discovered_plugins = [plugin.to_view_model() for plugin in discovered]
        return self._discovered_plugins

    def _select_plugin(self, combo: QComboBox) -> None:
        if self._is_refreshing():
            return
        plugin_path = str(combo.currentData() or "")
        if not plugin_path:
            return
        self.service.update_selected_param("plugin_path", plugin_path)
        self._refresh_chain_list()
        self._refresh_parameter_panel()

    def _refresh_plugins(self) -> None:
        self._discovered_plugins = None
        self._set_status(self.service.selected_node_id, "Plugin list refreshed.", "idle")
        self._refresh_parameter_panel()

    def _build_parameter_pager(
        self,
        node_id: str,
        page: int,
        page_count: int,
        start: int,
        end: int,
        total: int,
    ) -> QWidget:
        pager = QWidget()
        pager.setObjectName("vst_parameter_pager")
        layout = QHBoxLayout(pager)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        previous_button = QPushButton()
        previous_button.setObjectName("vst_params_prev_page_button")
        self._configure_icon_button(
            previous_button,
            "SP_ArrowBack",
            "Previous parameter page",
            fallback=QStyle.StandardPixmap.SP_ArrowLeft,
        )
        previous_button.setEnabled(page > 0)
        previous_button.clicked.connect(lambda: self._set_parameter_page(node_id, page - 1))
        layout.addWidget(previous_button)

        next_button = QPushButton()
        next_button.setObjectName("vst_params_next_page_button")
        self._configure_icon_button(
            next_button,
            "SP_ArrowForward",
            "Next parameter page",
            fallback=QStyle.StandardPixmap.SP_ArrowRight,
        )
        next_button.setEnabled(page < page_count - 1)
        next_button.clicked.connect(lambda: self._set_parameter_page(node_id, page + 1))
        layout.addWidget(next_button)

        label = QLabel(f"{start + 1}-{end} of {total}")
        label.setObjectName("vst_parameter_page_label")
        label.setProperty("role", "fieldLabel")
        layout.addWidget(label)
        layout.addStretch(1)
        return pager

    def _build_parameter_scroll(self, snapshot: list[dict[str, Any]]) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("vst_parameter_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(180)
        scroll.setMaximumHeight(420)

        container = QWidget()
        container.setObjectName("vst_parameter_scroll_contents")
        layout = QFormLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(8)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for entry in snapshot:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            label = str(entry.get("display_name") or key)
            widget = self._create_mirror_widget(entry)
            layout.addRow(label, widget)

        scroll.setWidget(container)
        return scroll

    def _set_parameter_page(self, node_id: str, page: int) -> None:
        self._parameter_pages[node_id] = max(0, page)
        if self.service.selected_node_id == node_id:
            self._refresh_parameter_panel()

    def _create_mirror_widget(self, entry: dict[str, Any]) -> QWidget:
        key = str(entry.get("key") or "parameter")
        value = entry.get("value", entry.get("raw_value"))
        type_name = str(entry.get("type") or "").lower()
        choices = list(entry.get("choices") or [])

        if choices:
            combo = QComboBox()
            combo.setObjectName(f"vst_param_widget_{key}")
            for choice in choices:
                combo.addItem(str(choice), choice)
            current = combo.findText(str(value))
            if current < 0 and value is not None:
                combo.addItem(str(value), value)
                current = combo.count() - 1
            if current >= 0:
                combo.setCurrentIndex(current)
            combo.setEnabled(False)
            return combo

        if isinstance(value, bool) or type_name in {"bool", "boolean"}:
            checkbox = QCheckBox()
            checkbox.setObjectName(f"vst_param_widget_{key}")
            checkbox.setChecked(bool(value))
            checkbox.setEnabled(False)
            return checkbox

        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            or type_name in {"int", "integer"}
        ):
            spin = QSpinBox()
            spin.setObjectName(f"vst_param_widget_{key}")
            spin.setRange(-1_000_000_000, 1_000_000_000)
            if value is not None:
                spin.setValue(int(value))
            spin.setEnabled(False)
            return spin

        if isinstance(value, float) or type_name in {"float", "double", "number"}:
            spin = QDoubleSpinBox()
            spin.setObjectName(f"vst_param_widget_{key}")
            spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
            spin.setDecimals(6)
            if value is not None:
                spin.setValue(float(value))
            spin.setEnabled(False)
            return spin

        line = QLineEdit()
        line.setObjectName(f"vst_param_widget_{key}")
        line.setText("" if value is None else str(value))
        line.setEnabled(False)
        return line

    def _open_selected_editor(self) -> None:
        node = self.service.selected_node()
        capability = self.service.selected_capability()
        if node is None or capability is None or capability.id != VST_CAPABILITY_ID:
            self._set_status(None, "Select a VST / AU Plugin node first.", "warning")
            return

        plugin_path = str(node.params.get("plugin_path") or "").strip()
        if not plugin_path:
            self._set_status(node.id, "Choose a plugin path before opening the editor.", "warning")
            return
        expanded_path = Path(plugin_path).expanduser()
        if not expanded_path.exists():
            self._set_status(node.id, f"Plugin path not found: {expanded_path}", "warning")
            return

        controller = self._ensure_host_controller()
        self._host_node_id = node.id
        self._set_status(node.id, "Opening editor...", "running")
        if self._open_editor_button is not None:
            self._open_editor_button.setEnabled(False)
        controller.open_editor(
            plugin_path=str(expanded_path),
            params=normalize_param_entries(node.params.get("params") or []),
        )

    def _ensure_host_controller(self) -> Any:
        if self._host_controller is not None:
            return self._host_controller
        if self._host_controller_factory is not None:
            controller = self._host_controller_factory()
        else:
            from audiocli.gui.vst_host_client import VstHostController  # noqa: PLC0415

            controller = VstHostController(self._parent)
        controller.loaded.connect(self._on_host_loaded)
        controller.parameters.connect(self._on_host_parameters)
        controller.closed.connect(self._on_host_closed)
        controller.error.connect(self._on_host_error)
        controller.status.connect(self._on_host_status)
        if hasattr(controller, "exited"):
            controller.exited.connect(self._on_host_exited)
        self._host_controller = controller
        return controller

    def _on_host_loaded(self, payload: dict[str, Any]) -> None:
        display_name = str(payload.get("display_name") or "Plugin")
        self._set_status(self._host_node_id, f"{display_name} editor loaded.", "running")

    def _on_host_parameters(self, parameters: list[Any]) -> None:
        node_id = self._host_node_id
        if node_id is None:
            return
        snapshot = [dict(entry) for entry in parameters if isinstance(entry, dict)]
        self._parameter_snapshots[node_id] = snapshot
        page_count = max(
            1, (len(snapshot) + VST_PARAMETER_PAGE_SIZE - 1) // VST_PARAMETER_PAGE_SIZE
        )
        self._parameter_pages[node_id] = min(self._parameter_pages.get(node_id, 0), page_count - 1)
        entries = snapshot_to_param_entries(snapshot)
        try:
            node = self.service.chain.get_node(node_id)
        except (IndexError, KeyError, ValueError):
            return
        params = dict(node.params)
        params["params"] = entries
        self.service.chain.update_node_params(node_id, params)
        self._refresh_chain_list()
        if self.service.selected_node_id == node_id:
            self._refresh_parameter_panel()

    def _on_host_closed(self, _payload: dict[str, Any]) -> None:
        node_id = self._host_node_id
        self._set_status(node_id, "Editor closed. Parameters are mirrored.", "idle")
        self._host_node_id = None
        if self._open_editor_button is not None:
            self._open_editor_button.setEnabled(True)
        if node_id is not None and self.service.selected_node_id == node_id:
            self._refresh_parameter_panel()

    def _on_host_error(self, message: str) -> None:
        self._set_status(self._host_node_id, message, "failed")

    def _on_host_status(self, message: str) -> None:
        if self._host_node_id is None:
            return
        self._set_status(self._host_node_id, message, "running")

    def _on_host_exited(self, _payload: dict[str, Any]) -> None:
        self._host_node_id = None

    def _set_status(self, node_id: str | None, message: str, state: str) -> None:
        if node_id is not None:
            self._status_by_node[node_id] = (message, state)
        label = self._host_status_label
        if label is not None and (node_id is None or self.service.selected_node_id == node_id):
            label.setText(message)
            label.setProperty("state", state)
            repolish(label)

    def _path_parameter_widget(
        self,
        name: str,
        value: Any,
        updater: Callable[[Any], None],
    ) -> QWidget:
        container = QWidget()
        container.setObjectName(f"param_widget_{name}")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        line = QLineEdit()
        line.setObjectName(f"param_widget_{name}_line")
        line.setText("" if value is None else str(value))
        line.editingFinished.connect(lambda w=line: updater(w.text()))
        layout.addWidget(line, 1)
        browse = QPushButton()
        self._configure_icon_button(
            browse,
            "SP_DirOpenIcon",
            f"Browse {name}",
            role="icon",
            fallback=QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        browse.clicked.connect(lambda: self._browse_parameter_path(line, updater))
        layout.addWidget(browse)
        return container

    def _browse_parameter_path(self, line: QLineEdit, updater: Callable[[Any], None]) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(self._parent, "Select file")
        if path:
            line.setText(path)
            updater(path)

    def _standard_icon(
        self,
        name: str,
        fallback: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_FileIcon,
    ) -> QIcon:
        standard_pixmap = getattr(QStyle.StandardPixmap, name, fallback)
        return self._parent.style().standardIcon(standard_pixmap)

    def _configure_icon_button(
        self,
        button: QPushButton,
        icon_name: str,
        label: str,
        *,
        role: str = "icon",
        fallback: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_FileIcon,
        size: QSize | None = None,
    ) -> QPushButton:
        button.setText("")
        button.setIcon(self._standard_icon(icon_name, fallback))
        button.setIconSize(QSize(17, 17))
        button.setToolTip(_compact_tooltip(label, limit=64))
        button.setAccessibleName(label)
        button.setFixedSize(size or QSize(36, 32))
        button.setProperty("role", role)
        return button


def _plugin_picker_label(plugin: dict[str, Any]) -> str:
    name = str(plugin.get("name") or Path(str(plugin.get("path") or "")).stem or "Plugin")
    plugin_format = str(plugin.get("format") or "plugin")
    scope = str(plugin.get("scope") or "")
    suffix = f"{plugin_format}"
    if scope:
        suffix = f"{suffix} / {scope}"
    return f"{name}  ({suffix})"


def _compact_tooltip(text: object, *, limit: int = 120) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."

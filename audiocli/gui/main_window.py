"""PySide6 main-window implementation for the optional desktop shell."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from audiocli.capabilities import CapabilityNode
from audiocli.errors import AudioCLIError
from audiocli.gui.qt_compat import is_checked_state
from audiocli.gui.service import InMemoryWorkspaceService

USER_ROLE = int(Qt.ItemDataRole.UserRole)


class MainWindow(QMainWindow):
    """Single unified AudioCLI workspace shell.

    The window intentionally uses one central splitter workspace and no
    operation-specific tabs.  All chain editing flows through
    :class:`InMemoryWorkspaceService`.
    """

    def __init__(
        self,
        service: InMemoryWorkspaceService | None = None,
        *,
        test_safe: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or InMemoryWorkspaceService()
        self.test_safe = test_safe
        self._refreshing = False
        self._parameter_widgets: dict[str, QWidget] = {}
        self._run_thread: QThread | None = None
        self._run_worker: Any | None = None
        self._global_actions: dict[str, QAction] = {}
        self._saved_chain_menu: QMenu | None = None
        self._load_saved_chain_button: QToolButton | None = None

        self.setWindowTitle("AudioCLI Workspace")
        self.resize(1280, 760)
        self._build_action_bar()
        self._build_workspace()
        self.refresh_workspace()

    def _build_action_bar(self) -> None:
        toolbar = QToolBar("AudioCLI", self)
        toolbar.setObjectName("main_action_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        file_menu = self.menuBar().addMenu("&File")
        library_menu = self.menuBar().addMenu("&Library")

        load_saved = self._make_action(
            "load_saved_chain_action",
            "Load Saved",
            self._show_saved_chain_menu,
            shortcut=QKeySequence.StandardKey.Open,
        )
        save_native = self._make_action(
            "save_native_chain_action",
            "Save Native",
            self._export_native_chain_file,
            shortcut=QKeySequence.StandardKey.Save,
        )
        import_native = self._make_action(
            "import_native_chain_action",
            "Import Native",
            self._import_native_chain_file,
        )
        export_acli = self._make_action(
            "export_acli_chain_action",
            "Export .acli",
            self._export_acli_chain_file,
        )
        import_acli = self._make_action(
            "import_acli_chain_action",
            "Import .acli",
            self._import_acli_chain_file,
        )
        refresh_saved = self._make_action(
            "refresh_saved_chains_action",
            "Refresh Saved",
            self._refresh_saved_chain_library,
            shortcut=QKeySequence.StandardKey.Refresh,
        )

        self._saved_chain_menu = QMenu("Load Saved Chains", self)
        self._saved_chain_menu.setObjectName("load_saved_chain_menu")
        self._saved_chain_menu.aboutToShow.connect(self._populate_saved_chain_menu)
        self._load_saved_chain_button = QToolButton(self)
        self._load_saved_chain_button.setObjectName("load_saved_chain_menu_button")
        self._load_saved_chain_button.setDefaultAction(load_saved)
        self._load_saved_chain_button.setMenu(self._saved_chain_menu)
        self._load_saved_chain_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._load_saved_chain_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        load_widget_action = toolbar.addWidget(self._load_saved_chain_button)
        load_widget_action.setObjectName("load_saved_chain_menu_widget_action")
        for action in (save_native, import_native, import_acli, export_acli):
            toolbar.addAction(action)
        separator = toolbar.addSeparator()
        separator.setObjectName("separator")
        toolbar.addAction(refresh_saved)

        file_menu.addAction(load_saved)
        file_menu.addAction(save_native)
        file_menu.addSeparator()
        file_menu.addAction(import_native)
        file_menu.addAction(import_acli)
        file_menu.addSeparator()
        file_menu.addAction(export_acli)

        library_menu.addAction(refresh_saved)
        library_menu.addAction(load_saved)

    def _make_action(
        self,
        object_name: str,
        text: str,
        callback: Callable[[], None],
        *,
        shortcut: QKeySequence.StandardKey | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.setObjectName(object_name)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        self._global_actions[object_name] = action
        return action

    def _build_workspace(self) -> None:
        workspace = QSplitter(Qt.Orientation.Horizontal, self)
        workspace.setObjectName("main_workspace_splitter")
        self.setCentralWidget(workspace)

        workspace.addWidget(self._build_capability_browser())
        workspace.addWidget(self._build_chain_editor())
        workspace.addWidget(self._build_detail_panel())
        workspace.setSizes([320, 360, 560])

    def _build_capability_browser(self) -> QWidget:
        group = QGroupBox("Capability Browser")
        layout = QVBoxLayout(group)

        self.capability_filter = QLineEdit()
        self.capability_filter.setObjectName("capability_filter")
        self.capability_filter.setPlaceholderText("Filter capabilities…")
        self.capability_filter.textChanged.connect(self._populate_capability_browser)
        layout.addWidget(self.capability_filter)

        self.capability_browser = QTreeWidget()
        self.capability_browser.setObjectName("capability_browser")
        self.capability_browser.setHeaderLabels(["Capability"])
        self.capability_browser.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.capability_browser.itemDoubleClicked.connect(self._add_browser_selection)
        layout.addWidget(self.capability_browser, 1)

        add_button = QPushButton("Add selected to chain")
        add_button.setObjectName("add_capability_button")
        add_button.clicked.connect(self._add_browser_selection)
        layout.addWidget(add_button)

        return group

    def _build_chain_editor(self) -> QWidget:
        group = QGroupBox("Ordered Chain Editor")
        layout = QVBoxLayout(group)

        self.chain_list = QListWidget()
        self.chain_list.setObjectName("chain_editor")
        self.chain_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.chain_list.currentItemChanged.connect(self._select_chain_item)
        layout.addWidget(self.chain_list, 1)

        button_row = QHBoxLayout()
        self.move_up_button = QPushButton("Up")
        self.move_up_button.setObjectName("move_node_up_button")
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        button_row.addWidget(self.move_up_button)

        self.move_down_button = QPushButton("Down")
        self.move_down_button.setObjectName("move_node_down_button")
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        button_row.addWidget(self.move_down_button)

        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("remove_node_button")
        self.remove_button.clicked.connect(self._remove_selected)
        button_row.addWidget(self.remove_button)
        layout.addLayout(button_row)

        self.chain_status = QLabel()
        self.chain_status.setObjectName("chain_status")
        self.chain_status.setWordWrap(True)
        layout.addWidget(self.chain_status)
        return group

    def _build_detail_panel(self) -> QWidget:
        detail_splitter = QSplitter(Qt.Orientation.Vertical)
        detail_splitter.setObjectName("detail_panel_splitter")

        self.parameter_group = QGroupBox("Parameter Panel")
        self.parameter_group.setObjectName("parameter_panel")
        self.parameter_form = QFormLayout(self.parameter_group)
        detail_splitter.addWidget(self.parameter_group)

        detail_splitter.addWidget(self._build_target_output_controls())
        detail_splitter.addWidget(self._build_results_and_logs())
        detail_splitter.setSizes([340, 150, 260])
        return detail_splitter

    def _build_target_output_controls(self) -> QWidget:
        group = QGroupBox("Target / Output / Job Controls")
        layout = QVBoxLayout(group)

        target_row = QHBoxLayout()
        self.target_input = QLineEdit()
        self.target_input.setObjectName("target_input")
        self.target_input.setPlaceholderText("Input files/directories separated by ;")
        self.target_input.editingFinished.connect(self._update_targets_from_text)
        target_row.addWidget(QLabel("Targets"))
        target_row.addWidget(self.target_input, 1)
        browse_targets = QPushButton("Browse…")
        browse_targets.clicked.connect(self._browse_targets)
        target_row.addWidget(browse_targets)
        layout.addLayout(target_row)

        output_row = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setObjectName("output_input")
        self.output_input.setPlaceholderText("Output file or directory")
        self.output_input.editingFinished.connect(
            lambda: self.service.set_output_path(self.output_input.text().strip())
        )
        output_row.addWidget(QLabel("Output"))
        output_row.addWidget(self.output_input, 1)
        browse_output = QPushButton("Browse…")
        browse_output.clicked.connect(self._browse_output)
        output_row.addWidget(browse_output)
        layout.addLayout(output_row)

        mode_row = QHBoxLayout()
        self.output_mode = QComboBox()
        self.output_mode.setObjectName("output_mode")
        self.output_mode.addItems(["final_only", "keep_intermediates", "destructive"])
        self.output_mode.currentTextChanged.connect(self.service.set_output_mode)
        mode_row.addWidget(QLabel("Mode"))
        mode_row.addWidget(self.output_mode)

        self.worker_count = QSpinBox()
        self.worker_count.setObjectName("worker_count")
        self.worker_count.setRange(0, 256)
        self.worker_count.setSpecialValueText("auto")
        self.worker_count.valueChanged.connect(self.service.set_worker_count)
        mode_row.addWidget(QLabel("Workers"))
        mode_row.addWidget(self.worker_count)

        self.recursive_scan = QCheckBox("Recursive")
        self.recursive_scan.setObjectName("recursive_scan")
        self.recursive_scan.stateChanged.connect(
            lambda state: self.service.set_recursive(is_checked_state(state))
        )
        mode_row.addWidget(self.recursive_scan)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        job_row = QHBoxLayout()
        self.run_button = QPushButton("Run chain")
        self.run_button.setObjectName("run_job_button")
        self.run_button.clicked.connect(self._run_chain)
        job_row.addWidget(self.run_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancel_job_button")
        self.cancel_button.clicked.connect(self._cancel_chain)
        job_row.addWidget(self.cancel_button)
        job_row.addStretch(1)
        layout.addLayout(job_row)

        self.job_status = QLabel("Idle")
        self.job_status.setObjectName("job_status")
        self.job_status.setWordWrap(True)
        layout.addWidget(self.job_status)

        self.job_progress = QProgressBar()
        self.job_progress.setObjectName("job_progress")
        self.job_progress.setRange(0, 100)
        layout.addWidget(self.job_progress)
        return group

    def _build_results_and_logs(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("results_log_splitter")

        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        self.results_panel = QPlainTextEdit()
        self.results_panel.setObjectName("results_panel")
        self.results_panel.setReadOnly(True)
        results_layout.addWidget(self.results_panel)
        splitter.addWidget(results_group)

        log_group = QGroupBox("Logs")
        log_layout = QVBoxLayout(log_group)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setObjectName("log_panel")
        self.log_panel.setReadOnly(True)
        log_layout.addWidget(self.log_panel)
        splitter.addWidget(log_group)
        splitter.setSizes([280, 280])
        return splitter

    def refresh_workspace(self) -> None:
        self._refreshing = True
        try:
            self._populate_capability_browser()
            self._refresh_saved_chain_library()
            self._refresh_chain_list()
            self._refresh_parameter_panel()
            self._refresh_job_panels()
        finally:
            self._refreshing = False

    def _populate_capability_browser(self, *_args: object) -> None:
        if not hasattr(self, "capability_browser"):
            return
        needle = (
            self.capability_filter.text().strip().lower()
            if hasattr(self, "capability_filter")
            else ""
        )
        self.capability_browser.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for capability in self.service.capabilities():
            haystack = f"{capability.display_name} {capability.id} {capability.type}".lower()
            if needle and needle not in haystack:
                continue
            group_name = capability.type.replace("_", " ").title() or "Capabilities"
            group_item = groups.get(group_name)
            if group_item is None:
                group_item = QTreeWidgetItem([group_name])
                group_item.setFirstColumnSpanned(True)
                groups[group_name] = group_item
                self.capability_browser.addTopLevelItem(group_item)
            item = QTreeWidgetItem([capability.display_name])
            item.setData(0, USER_ROLE, capability.id)
            item.setToolTip(0, capability.description)
            group_item.addChild(item)
        self.capability_browser.expandAll()

    def _refresh_saved_chain_library(self) -> None:
        self._populate_saved_chain_menu()

    def _populate_saved_chain_menu(self) -> None:
        if self._saved_chain_menu is None:
            return
        self._saved_chain_menu.clear()
        entries = self.service.list_saved_chains()
        if not entries:
            empty_action = self._saved_chain_menu.addAction("No saved chains")
            empty_action.setObjectName("no_saved_chains_action")
            empty_action.setEnabled(False)
            return

        for index, entry in enumerate(entries):
            label = entry.name if entry.valid else f"{entry.name} — invalid"
            action = QAction(label, self._saved_chain_menu)
            action.setObjectName(f"load_saved_chain_entry_action_{index}")
            action.setData(entry.path)
            action.setToolTip(entry.description or entry.notes or entry.error or entry.path)
            action.setEnabled(entry.valid)
            action.triggered.connect(
                lambda _checked=False, path=entry.path: self._load_saved_chain_path(path)
            )
            self._saved_chain_menu.addAction(action)

    def _show_saved_chain_menu(self, *_args: object) -> None:
        self._populate_saved_chain_menu()
        if self._saved_chain_menu is None:
            return
        if self._load_saved_chain_button is not None:
            button_pos = self._load_saved_chain_button.mapToGlobal(
                self._load_saved_chain_button.rect().bottomLeft()
            )
            self._saved_chain_menu.popup(button_pos)
            return
        self._saved_chain_menu.popup(self.mapToGlobal(self.rect().topLeft()))

    def _load_saved_chain_path(self, path: str) -> None:
        if not path:
            return
        try:
            self.service.load_saved_chain(path)
        except Exception as exc:
            if not self.test_safe:
                QMessageBox.warning(self, "Saved chain", str(exc))
            self.service.job.logs.append(f"Saved chain load failed: {exc}")
        self.refresh_workspace()

    def _import_native_chain_file(self) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import native AudioCLI chain",
            "",
            "AudioCLI chains (*.aclichain *.audiocli-chain.json);;All files (*)",
        )
        if not path:
            return
        try:
            result = self.service.import_native_chain(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import native chain", str(exc))
            self.service.job.logs.append(f"Native chain import failed: {exc}")
        else:
            QMessageBox.information(self, "Import native chain", result.explanation)
        self.refresh_workspace()

    def _export_native_chain_file(self) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export native AudioCLI chain",
            "chain.aclichain",
            "AudioCLI chains (*.aclichain *.audiocli-chain.json);;All files (*)",
        )
        if not path:
            return
        try:
            result = self.service.export_current_chain_native(path)
        except Exception as exc:
            QMessageBox.warning(self, "Export native chain", str(exc))
            self.service.job.logs.append(f"Native chain export failed: {exc}")
        else:
            QMessageBox.information(self, "Export native chain", result.explanation)
        self.refresh_workspace()

    def _import_acli_chain_file(self) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import .acli script",
            "",
            "AudioCLI scripts (*.acli);;All files (*)",
        )
        if not path:
            return
        try:
            result = self.service.import_acli_script_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import .acli", str(exc))
            self.service.job.logs.append(f".acli import failed: {exc}")
        else:
            QMessageBox.information(self, "Import .acli", result.explanation)
        self.refresh_workspace()

    def _export_acli_chain_file(self) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export .acli script",
            "chain.acli",
            "AudioCLI scripts (*.acli);;All files (*)",
        )
        if not path:
            return
        try:
            result = self.service.export_current_chain_acli(path)
        except Exception as exc:
            QMessageBox.warning(self, "Export .acli", str(exc))
            self.service.job.logs.append(f".acli export failed: {exc}")
        else:
            QMessageBox.information(self, "Export .acli", result.explanation)
        self.refresh_workspace()

    def _refresh_chain_list(self) -> None:
        selected_id = self.service.selected_node_id
        self.chain_list.blockSignals(True)
        self.chain_list.clear()
        chain_view = self.service.chain.to_view_model()
        for node_view in chain_view["nodes"]:
            marker = "✓" if node_view["validation_state"].get("valid") else "!"
            item = QListWidgetItem(
                f"{node_view['position'] + 1}. {node_view['display_name']}   {marker}"
            )
            item.setData(USER_ROLE, node_view["id"])
            self.chain_list.addItem(item)
            if node_view["id"] == selected_id:
                self.chain_list.setCurrentItem(item)
        self.chain_list.blockSignals(False)

        validation = chain_view["validation_state"]
        if validation["valid"]:
            self.chain_status.setText("Chain is valid.")
        else:
            messages = [error["message"] for error in validation["errors"][:3]]
            self.chain_status.setText("Chain needs attention: " + " | ".join(messages))

    def _refresh_parameter_panel(self) -> None:
        self._clear_form(self.parameter_form)
        self._parameter_widgets = {}

        node = self.service.selected_node()
        capability = self.service.selected_capability()
        if node is None or capability is None:
            self.parameter_form.addRow(QLabel("Select a chain node to edit its parameters."))
            return

        title = QLabel(f"{capability.display_name}\n{capability.description}")
        title.setWordWrap(True)
        title.setObjectName("selected_capability_summary")
        self.parameter_form.addRow(title)

        if not capability.parameters:
            self.parameter_form.addRow(QLabel("This capability has no configurable parameters."))
            return

        for parameter in capability.parameters:
            widget = self._create_parameter_widget(
                capability, parameter.to_view_model(), node.params
            )
            label = parameter.display_name + (" *" if parameter.required else "")
            self.parameter_form.addRow(label, widget)
            self._parameter_widgets[parameter.name] = widget

    def _refresh_job_panels(self) -> None:
        job = self.service.job
        self.target_input.setText("; ".join(job.targets))
        self.output_input.setText(job.output_path)
        index = self.output_mode.findText(job.output_mode)
        if index >= 0:
            self.output_mode.setCurrentIndex(index)
        self.worker_count.setValue(job.worker_count)
        self.recursive_scan.setChecked(job.recursive)
        self.run_button.setEnabled(not job.running and self._run_thread is None)
        self.cancel_button.setEnabled(job.running or self._run_worker is not None)
        self.job_progress.setValue(int(job.progress * 100))
        current_bits = []
        if job.current_file:
            current_bits.append(f"file: {job.current_file}")
        if job.current_node:
            current_bits.append(f"node: {job.current_node}")
        current_text = " | ".join(current_bits)
        progress_text = f"{job.done}/{job.total}" if job.total else "not started"
        cancel_text = " (cancellation requested)" if job.cancel_requested else ""
        self.job_status.setText(
            f"Status: {job.status}{cancel_text}\nProgress: {progress_text}"
            + (f"\nCurrent: {current_text}" if current_text else "")
        )
        result_view = {
            "status": job.status,
            "progress": {"done": job.done, "total": job.total, "fraction": job.progress},
            "current_node": job.current_node,
            "current_file": job.current_file,
            "summary": job.summary,
            "results": job.results,
            "errors": job.errors,
        }
        self.results_panel.setPlainText(json.dumps(result_view, indent=2, sort_keys=True))
        self.log_panel.setPlainText("\n".join(job.logs))

    def _create_parameter_widget(
        self,
        capability: CapabilityNode,
        parameter: dict[str, Any],
        node_params: dict[str, Any],
    ) -> QWidget:
        name = str(parameter["name"])
        value = node_params.get(name, parameter.get("default"))
        hint = str(parameter.get("control_hint") or "text")
        choices = list(parameter.get("choices") or [])
        type_name = str(parameter.get("type") or "")

        def updater(new_value: Any) -> None:
            if self._refreshing:
                return
            self.service.update_selected_param(name, new_value)
            self._refresh_chain_list()

        if choices or hint == "select":
            combo = QComboBox()
            combo.setObjectName(f"param_widget_{name}")
            for choice in choices:
                combo.addItem(str(choice), choice)
            current_index = combo.findText(str(value))
            if current_index >= 0:
                combo.setCurrentIndex(current_index)
            combo.currentIndexChanged.connect(lambda _idx, c=combo: updater(c.currentData()))
            return combo

        if hint in {"checkbox", "toggle"} or type_name in {"bool", "boolean"}:
            checkbox = QCheckBox()
            checkbox.setObjectName(f"param_widget_{name}")
            checkbox.setChecked(bool(value))
            checkbox.stateChanged.connect(lambda state: updater(is_checked_state(state)))
            return checkbox

        if hint == "number" or type_name in {"int", "integer", "float", "number"}:
            if type_name in {"int", "integer"}:
                spin = QSpinBox()
                spin.setObjectName(f"param_widget_{name}")
                minimum = parameter.get("min_value")
                spin.setRange(
                    int(minimum) if minimum is not None else -1_000_000_000, 1_000_000_000
                )
                if value is not None:
                    spin.setValue(int(value))
                spin.valueChanged.connect(updater)
                return spin
            spin = QDoubleSpinBox()
            spin.setObjectName(f"param_widget_{name}")
            minimum = parameter.get("min_value")
            spin.setRange(
                float(minimum) if minimum is not None else -1_000_000_000.0, 1_000_000_000.0
            )
            spin.setDecimals(4)
            if value is not None:
                spin.setValue(float(value))
            spin.valueChanged.connect(updater)
            return spin

        if hint == "path":
            return self._path_parameter_widget(name, value, updater)

        if hint == "key_value_list" or isinstance(value, (dict, list)):
            editor = QPlainTextEdit()
            editor.setObjectName(f"param_widget_{name}")
            editor.setPlainText(json.dumps(value if value is not None else {}, indent=2))
            editor.textChanged.connect(lambda e=editor: updater(_decode_json_text(e.toPlainText())))
            return editor

        line = QLineEdit()
        line.setObjectName(f"param_widget_{name}")
        line.setText("" if value is None else str(value))
        line.editingFinished.connect(lambda w=line: updater(w.text()))
        return line

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
        line = QLineEdit()
        line.setObjectName(f"param_widget_{name}_line")
        line.setText("" if value is None else str(value))
        line.editingFinished.connect(lambda w=line: updater(w.text()))
        layout.addWidget(line, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_parameter_path(line, updater))
        layout.addWidget(browse)
        return container

    def _add_browser_selection(self, *_args: object) -> None:
        item = self.capability_browser.currentItem()
        if item is None:
            return
        capability_id = item.data(0, USER_ROLE)
        if not capability_id:
            return
        self.service.add_node(str(capability_id))
        self.refresh_workspace()

    def _select_chain_item(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        if self._refreshing:
            return
        node_id = current.data(USER_ROLE) if current is not None else None
        self.service.select_node(str(node_id) if node_id else None)
        self._refresh_parameter_panel()
        self._refresh_chain_list()

    def _move_selected(self, delta: int) -> None:
        self.service.move_selected(delta)
        self.refresh_workspace()

    def _remove_selected(self) -> None:
        self.service.remove_selected()
        self.refresh_workspace()

    def _update_targets_from_text(self) -> None:
        targets = [part.strip() for part in self.target_input.text().split(";") if part.strip()]
        self.service.set_targets(targets)

    def _browse_targets(self) -> None:
        if self.test_safe:
            return
        paths, _selected_filter = QFileDialog.getOpenFileNames(self, "Select audio targets")
        if paths:
            self.service.set_targets(paths)
            self.refresh_workspace()

    def _browse_output(self) -> None:
        if self.test_safe:
            return
        path = QFileDialog.getExistingDirectory(self, "Select output directory")
        if path:
            self.service.set_output_path(path)
            self.refresh_workspace()

    def _browse_parameter_path(self, line: QLineEdit, updater: Callable[[Any], None]) -> None:
        if self.test_safe:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            line.setText(path)
            updater(path)

    def _run_chain(self) -> None:
        if self._run_thread is not None:
            return
        self._update_targets_from_text()
        self.service.set_output_path(self.output_input.text().strip())
        self.service.set_output_mode(self.output_mode.currentText())
        self.service.set_worker_count(self.worker_count.value())
        self.service.set_recursive(self.recursive_scan.isChecked())
        self.service.save_settings()
        base_request = self.service.make_execution_request()
        confirmation = self._destructive_confirmation_if_needed(base_request)
        if confirmation is False:
            return
        request = self.service.make_execution_request(
            destructive_confirmation=confirmation if isinstance(confirmation, dict) else None
        )
        try:
            request = self.service.prepare_execution_request(request)
        except AudioCLIError as exc:
            if not self.test_safe:
                QMessageBox.warning(self, "Chain validation", str(exc))
            self.refresh_workspace()
            return
        errors = self.service.start_execution(request)
        if errors:
            if not self.test_safe:
                QMessageBox.warning(
                    self, "Chain validation", errors[0].get("message", "Invalid run")
                )
            self.refresh_workspace()
            return

        from audiocli.gui.qt_bridge import WorkspaceChainWorker  # noqa: PLC0415

        thread = QThread(self)
        worker = WorkspaceChainWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_received.connect(self._on_worker_event)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.state_changed.connect(self._on_worker_state_changed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_worker_refs)
        self._run_thread = thread
        self._run_worker = worker
        self.refresh_workspace()
        thread.start()

    def _cancel_chain(self) -> None:
        if self._run_worker is None:
            self.service.request_cancel_execution()
            self.refresh_workspace()
            return
        self.service.request_cancel_execution(self._run_worker.cancel_token)
        self._run_worker.cancel()
        self._refresh_job_panels()

    def _on_worker_event(self, event: dict[str, Any]) -> None:
        self.service.apply_execution_event(event)
        self._refresh_job_panels()

    def _on_worker_finished(self, report: dict[str, Any]) -> None:
        self.service.finish_execution(report)
        self._refresh_job_panels()

    def _on_worker_failed(self, message: str) -> None:
        self.service.fail_execution(message)
        if not self.test_safe:
            QMessageBox.critical(self, "Run failed", message)
        self._refresh_job_panels()

    def _on_worker_state_changed(self, state: dict[str, Any]) -> None:
        if state.get("cancel_requested") and self.service.job.running:
            self.service.job.cancel_requested = True
            self.service.job.status = "cancelling"
        self._refresh_job_panels()

    def _clear_worker_refs(self) -> None:
        self._run_thread = None
        self._run_worker = None
        self._refresh_job_panels()

    def _destructive_confirmation_if_needed(self, request: Any) -> dict[str, Any] | bool | None:
        if request.output_mode != "destructive":
            return None
        try:
            impact = self.service.preview_destructive_impact(request)
        except AudioCLIError as exc:
            if not self.test_safe:
                QMessageBox.warning(self, "Chain validation", str(exc))
            self.refresh_workspace()
            return False
        affected_paths = list(impact.get("affected_paths") or [])
        if self.test_safe:
            return {"confirmed": False, "affected_paths": affected_paths}

        file_count = int(impact.get("affected_file_count") or len(affected_paths))
        directory_count = int(impact.get("affected_directory_count") or 0)
        message = (
            "Destructive mode overwrites/removes target files.\n\n"
            f"Scanned affected files: {file_count}\n"
            f"Directory targets expanded: {directory_count}\n\n"
            "Continue?"
        )
        answer = QMessageBox.warning(
            self,
            "Confirm destructive run",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.service.job.logs.append("Destructive run cancelled before start.")
            self.refresh_workspace()
            return False
        return {"confirmed": True, "affected_paths": affected_paths}

    def _run_fake_job(self) -> None:
        self._update_targets_from_text()
        self.service.set_output_path(self.output_input.text().strip())
        results = self.service.run_fake_job()
        if not self.test_safe and results and results[0].get("status") == "validation_error":
            QMessageBox.warning(
                self, "Chain validation", results[0].get("message", "Invalid chain")
            )
        self.refresh_workspace()

    def _cancel_fake_job(self) -> None:
        self.service.cancel_fake_job()
        self.refresh_workspace()

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override name
        self.service.save_settings()
        super().closeEvent(event)

    @staticmethod
    def _clear_form(form: QFormLayout) -> None:
        while form.count():
            item = form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()


def _decode_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def ensure_qapplication(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is not None:
        return app
    return QApplication([] if argv is None else argv)

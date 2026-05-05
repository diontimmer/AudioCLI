"""Visual theme helpers for the optional PySide6 workspace."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget


def apply_workspace_theme(app: QApplication) -> None:
    """Install AudioCLI's polished desktop theme on the Qt application."""

    if app.property("_audiocli_workspace_theme_applied"):
        return

    available_styles = QStyleFactory.keys()
    if "Fusion" in available_styles:
        app.setStyle("Fusion")

    base_font = _workspace_interface_font(app)
    point_size = base_font.pointSize()
    if point_size > 0:
        base_font.setPointSize(min(max(point_size, 11), 13))
    app.setFont(base_font)
    app.setPalette(_workspace_palette())
    app.setStyleSheet(WORKSPACE_STYLESHEET)
    app.setProperty("_audiocli_workspace_theme_applied", True)


def repolish(widget: QWidget) -> None:
    """Refresh style-sheet-backed dynamic properties on a widget."""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _workspace_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#252629"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#eee9dd"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1f2023"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#282a2d"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#eee9dd"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#33363c"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#eee9dd"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#8ea8c3"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#161719"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#34373d"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#eee9dd"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8f98"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#767d87"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#767d87"),
    )
    return palette


def _workspace_interface_font(app: QApplication) -> QFont:
    available_families = set(QFontDatabase.families())
    for family in (".AppleSystemUIFont", "Segoe UI", "Helvetica Neue", "Arial"):
        if family in available_families:
            return QFont(family)

    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if font.family():
        return font
    return app.font()


WORKSPACE_STYLESHEET = """
QMainWindow {
    background: #252629;
}

QWidget {
    color: #eee9dd;
    selection-background-color: #3b4655;
    selection-color: #eee9dd;
}

QMenuBar {
    background: #252629;
    border-bottom: 1px solid #34373d;
    padding: 2px 8px;
}

QMenuBar::item {
    background: transparent;
    border-radius: 5px;
    padding: 5px 10px;
}

QMenuBar::item:selected {
    background: #34373d;
}

QMenu {
    background: #252629;
    border: 1px solid #34373d;
    border-radius: 6px;
    padding: 6px;
}

QMenu::item {
    border-radius: 5px;
    padding: 7px 24px;
}

QMenu::item:selected {
    background: #34373d;
}

QToolBar#main_action_toolbar {
    background: #222326;
    border: 0;
    border-bottom: 1px solid #34373d;
    padding: 3px 6px;
    spacing: 4px;
}

QToolBar#main_action_toolbar::separator {
    background: #34373d;
    width: 1px;
    margin: 3px 6px;
}

QToolBar#main_action_toolbar QToolButton {
    border-radius: 4px;
    margin: 0;
    min-height: 18px;
    padding: 2px 7px;
}

QToolButton,
QPushButton {
    background: #33363c;
    border: 1px solid #555b66;
    border-radius: 5px;
    color: #eee9dd;
    font-weight: 600;
    min-height: 24px;
    padding: 5px 11px;
}

QToolButton:hover,
QPushButton:hover {
    background: #424751;
    border-color: #8ea8c3;
}

QToolButton:pressed,
QPushButton:pressed {
    background: #2c2f35;
    border-color: #c7a76c;
}

QToolButton::menu-indicator {
    image: none;
    width: 0;
}

QPushButton[role="primary"] {
    background: #8fbf9f;
    border-color: #a7c9b3;
    color: #101312;
}

QPushButton[role="primary"]:hover {
    background: #9bc9aa;
    border-color: #c7a76c;
    color: #101312;
}

QPushButton[role="accent"] {
    background: #56677f;
    border-color: #7c8ea8;
    color: #f4efe5;
}

QPushButton[role="accent"]:hover {
    background: #627591;
    border-color: #8ea8c3;
    color: #f4efe5;
}

QPushButton[role="danger"] {
    background: #8e4f56;
    border-color: #b0646b;
    color: #f7ede7;
}

QPushButton[role="danger"]:hover {
    background: #9d5a62;
    border-color: #c4777e;
    color: #f7ede7;
}

QPushButton[role="quiet"] {
    background: #30333a;
    border-color: #4a505b;
}

QPushButton[role="browse"] {
    min-width: 88px;
}

QPushButton[role="icon"],
QPushButton[role="iconPrimary"],
QPushButton[role="iconDanger"] {
    border-radius: 5px;
    font-weight: 500;
    min-height: 28px;
    min-width: 32px;
    padding: 3px;
}

QPushButton[role="icon"] {
    background: #2b2e34;
    border-color: #424852;
}

QPushButton[role="icon"]:hover {
    background: #343943;
    border-color: #8ea8c3;
}

QPushButton[role="iconPrimary"] {
    background: #8fbf9f;
    border-color: #a7c9b3;
}

QPushButton[role="iconPrimary"]:hover {
    background: #9bc9aa;
    border-color: #c7a76c;
}

QPushButton[role="iconDanger"] {
    background: #6d444a;
    border-color: #8e5960;
}

QPushButton[role="iconDanger"]:hover {
    background: #7d4e55;
    border-color: #b0646b;
}

QToolButton:disabled,
QPushButton:disabled {
    background: #2a2c31;
    border-color: #393c43;
    color: #767d87;
}

QGroupBox {
    background: transparent;
    border: 0;
    border-radius: 0;
    font-weight: 700;
    margin-top: 18px;
    padding: 7px 0 0 0;
}

QGroupBox::title {
    color: #eee9dd;
    left: 14px;
    padding: 0 6px;
    subcontrol-origin: margin;
    subcontrol-position: top left;
}

QLabel {
    color: #eee9dd;
}

QLabel[role="fieldLabel"] {
    color: #eee9dd;
    font-weight: 700;
}

QLabel[role="emptyState"] {
    color: #c7a76c;
    font-size: 14px;
    font-weight: 600;
    padding: 10px 4px;
}

QLabel#selected_capability_summary {
    background: #2c2e33;
    border: 1px solid #555b66;
    border-radius: 7px;
    color: #eee9dd;
    font-weight: 600;
    padding: 10px;
}

QLabel#chain_status,
QLabel#job_status {
    border-radius: 7px;
    font-weight: 600;
    padding: 9px 10px;
}

QLabel#chain_status[state="valid"],
QLabel#job_status[state="done"] {
    background: #203026;
    border: 1px solid #6f9f77;
    color: #b5d5b8;
}

QLabel#chain_status[state="warning"],
QLabel#job_status[state="warning"] {
    background: #332f22;
    border: 1px solid #b9975a;
    color: #ead497;
}

QLabel#job_status[state="failed"] {
    background: #34272a;
    border: 1px solid #a9646a;
    color: #e6b4b8;
}

QLabel#job_status[state="running"] {
    background: #23303b;
    border: 1px solid #8ea8c3;
    color: #b9cde1;
}

QLabel#job_status[state="idle"] {
    background: #252629;
    border: 1px solid #3c414a;
    color: #e5dfd2;
}

QLineEdit,
QPlainTextEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {
    background: #1f2023;
    border: 1px solid #3c414a;
    border-radius: 5px;
    color: #eee9dd;
    min-height: 26px;
    padding: 5px 8px;
}

QLineEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #8ea8c3;
}

QLineEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background: #252629;
    color: #767d87;
}

QComboBox::drop-down {
    border: 0;
    border-left: 1px solid #3c414a;
    width: 24px;
}

QComboBox QAbstractItemView {
    background: #252629;
    border: 1px solid #3c414a;
    border-radius: 6px;
    outline: 0;
    selection-background-color: #3b4655;
}

QSpinBox::up-button,
QDoubleSpinBox::up-button {
    background: #33363c;
    border: 0;
    border-left: 1px solid #555b66;
    border-top-right-radius: 6px;
    subcontrol-position: top right;
    width: 20px;
}

QSpinBox::down-button,
QDoubleSpinBox::down-button {
    background: #33363c;
    border: 0;
    border-bottom-right-radius: 6px;
    border-left: 1px solid #555b66;
    subcontrol-position: bottom right;
    width: 20px;
}

QCheckBox {
    color: #eee9dd;
    font-weight: 600;
    spacing: 8px;
}

QCheckBox::indicator {
    background: #1f2023;
    border: 1px solid #555b66;
    border-radius: 4px;
    height: 16px;
    width: 16px;
}

QCheckBox::indicator:checked {
    background: #8fbf9f;
    border-color: #c7a76c;
}

QTreeWidget#capability_browser,
QListWidget#chain_editor {
    background: #1f2023;
    border: 1px solid #3c414a;
    border-radius: 7px;
    outline: 0;
}

QHeaderView::section {
    background: #30333a;
    border: 0;
    border-bottom: 1px solid #4a505b;
    color: #eee9dd;
    font-weight: 700;
    padding: 7px 9px;
}

QTreeWidget::item,
QListWidget::item {
    border: 1px solid transparent;
    border-radius: 5px;
    min-height: 28px;
    padding: 5px 7px;
}

QTreeWidget::item:hover,
QListWidget::item:hover {
    background: #2e3239;
}

QTreeWidget::item:selected,
QListWidget::item:selected {
    background: #384453;
    border-color: #8ea8c3;
    color: #eee9dd;
}

QPlainTextEdit {
    color: #eee9dd;
    line-height: 1.25;
}

QProgressBar {
    background: #1f2023;
    border: 1px solid #3c414a;
    border-radius: 5px;
    color: transparent;
    height: 9px;
    text-align: center;
}

QProgressBar::chunk {
    background: #8fbf9f;
    border-radius: 4px;
}

QSplitter::handle {
    background: #30333a;
}

QSplitter::handle:horizontal {
    margin: 0;
    width: 4px;
}

QSplitter::handle:vertical {
    height: 4px;
    margin: 0;
}

QSplitter::handle:hover {
    background: #8ea8c3;
}

QScrollBar:vertical {
    background: transparent;
    border: 0;
    margin: 6px 2px 6px 0;
    width: 10px;
}

QScrollBar::handle:vertical {
    background: #3c414a;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background: #555b66;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    border: 0;
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    border: 0;
    height: 10px;
    margin: 0 6px 2px 6px;
}

QScrollBar::handle:horizontal {
    background: #3c414a;
    border-radius: 4px;
    min-width: 28px;
}

QScrollBar::handle:horizontal:hover {
    background: #555b66;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
    border: 0;
    width: 0;
}

QToolTip {
    background-color: #2d3036;
    border: 1px solid #596171;
    border-radius: 0;
    color: #eee9dd;
    font-size: 11px;
    font-weight: 500;
    padding: 3px 6px;
}
"""

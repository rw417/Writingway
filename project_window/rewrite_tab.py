#!/usr/bin/env python3
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QHBoxLayout
from PyQt5.QtCore import Qt
from .focus_mode import PlainTextEdit
from muse.prompt_panel import PromptPanel

# gettext '_' fallback for static analysis / standalone edits
_ = globals().get('_', lambda s: s)


class RewriteTab(QWidget):
    """Tab content for in-place rewrite operations."""

    def __init__(self, parent_stack):
        super().__init__(parent_stack)
        self.parent_stack = parent_stack
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel(_("Selected Text"))
        header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(header)

        self.selected_text_edit = PlainTextEdit()
        self.selected_text_edit.setReadOnly(True)
        self.selected_text_edit.setPlaceholderText(_("Select text in the scene editor to populate this field."))
        self.selected_text_edit.setFixedHeight(100)
        self.selected_text_edit.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.selected_text_edit)

        bottom_row_layout = QHBoxLayout()
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        self.prompt_panel = PromptPanel("Rewrite")
        self.prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.prompt_panel.setMaximumWidth(300)
        bottom_row_layout.addWidget(self.prompt_panel)
        bottom_row_layout.addStretch()
        layout.addLayout(bottom_row_layout)
        layout.addStretch()

    def set_selected_text(self, text: str):
        """Update the displayed selection text."""
        self.selected_text_edit.blockSignals(True)
        try:
            self.selected_text_edit.setPlainText(text or "")
        finally:
            self.selected_text_edit.blockSignals(False)

    def clear_selected_text(self):
        self.set_selected_text("")

    def get_selected_text(self) -> str:
        return self.selected_text_edit.toPlainText().strip()

    def set_dropdowns_enabled(self, enabled: bool):
        self.prompt_panel.prompt_combo.setEnabled(enabled)
        self.prompt_panel.provider_combo.setEnabled(True)
        self.prompt_panel.model_combo.setEnabled(True)

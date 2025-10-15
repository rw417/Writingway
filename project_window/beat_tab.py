#!/usr/bin/env python3
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt
from .focus_mode import PlainTextEdit
from muse.prompt_panel import PromptPanel

# gettext '_' fallback
_ = globals().get('_', lambda s: s)


class BeatTab(QWidget):
    """Separate module for the Beat (formerly Write) tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.prompt_input = PlainTextEdit()
        self.prompt_input.setPlaceholderText(_("Enter your action beats here..."))
        self.prompt_input.setFixedHeight(100)
        layout.addWidget(self.prompt_input)

        # bottom row with prompt panel anchored to bottom
        layout.addStretch()

        bottom_row_layout = QHBoxLayout()
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        self.prose_prompt_panel = PromptPanel("Prose")
        self.prose_prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.prose_prompt_panel.setMaximumWidth(250)
        bottom_row_layout.addWidget(self.prose_prompt_panel)
        bottom_row_layout.addStretch()
        layout.addLayout(bottom_row_layout)

    def get_user_input(self):
        return self.prompt_input.toPlainText().strip()

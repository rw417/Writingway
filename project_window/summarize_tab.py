#!/usr/bin/env python3
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt
from muse.prompt_panel import PromptPanel

# gettext '_' fallback
_ = globals().get('_', lambda s: s)


class SummarizeTab(QWidget):
    """Separate module for the Summarize tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        summary_box = QLabel(_("Summarize Current Scene"))
        summary_box.setAlignment(Qt.AlignCenter)
        summary_box.setStyleSheet("QLabel { border: 1px solid #888; padding: 8px; border-radius:4px; }")
        layout.addWidget(summary_box)

        # keep prompt panel at bottom
        layout.addStretch()
        self.summary_tab_prompt_panel = PromptPanel("Summary")
        self.summary_tab_prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.summary_tab_prompt_panel.setMaximumWidth(250)
        summary_prompt_layout = QHBoxLayout()
        summary_prompt_layout.setContentsMargins(0, 0, 0, 0)
        summary_prompt_layout.addWidget(self.summary_tab_prompt_panel)
        summary_prompt_layout.addStretch()
        layout.addLayout(summary_prompt_layout)

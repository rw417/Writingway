#!/usr/bin/env python3
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QStackedWidget,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QComboBox,
    QSizePolicy,
    QCheckBox,
    QLabel,
    QTabWidget,
)
from PyQt5.QtCore import Qt, QTimer

from settings.theme_manager import ThemeManager
from compendium.context_panel import ContextPanel
from project_window.tweaks_widget import TweaksWidget
from project_window.preview_editable_widget import PreviewEditableWidget
from project_window.preview_uneditable_widget import PreviewUneditableWidget
from project_window.rewrite_tab import RewriteTab
from project_window.beat_tab import BeatTab
from project_window.summarize_tab import SummarizeTab
from muse.prompt_panel import PromptPanel

_ = globals().get('_', lambda s: s)


class LLMPanel(QWidget):
    """Standalone widget containing the LLM interaction panel previously built inline."""

    def __init__(self, parent_stack):
        super().__init__(parent_stack)
        self.parent_stack = parent_stack
        self.controller = parent_stack.controller
        self.model = parent_stack.model
        self.tint_color = parent_stack.tint_color
        self.scene_editor = parent_stack.scene_editor

        self._build_ui()
        self._expose_to_parent()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Top control container (POV/Tense etc.) ---
        self.top_control_container = QWidget()
        top_control_layout = QVBoxLayout(self.top_control_container)
        top_control_layout.setContentsMargins(0, 0, 0, 0)

        top_row = QWidget()
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)

        self.pov_combo = QComboBox()
        self.pov_combo.addItems([
            _("1st Person"),
            _("2nd Person"),
            _("3rd Person Limited"),
            _("3rd Person Omniscient"),
            _("Custom..."),
        ])
        self.pov_combo.currentIndexChanged.connect(self.controller.handle_pov_change)

        self.pov_character_combo = QComboBox()
        self.pov_character_combo.addItems(["Alice", "Bob", "Charlie", _("Custom...")])
        self.pov_character_combo.currentIndexChanged.connect(
            self.controller.handle_pov_character_change
        )

        self.tense_combo = QComboBox()
        self.tense_combo.addItems([_('Past Tense'), _('Present Tense'), _('Custom...')])
        self.tense_combo.currentIndexChanged.connect(self.controller.handle_tense_change)

        pov_widget = QWidget()
        pov_widget_layout = QHBoxLayout(pov_widget)
        pov_widget_layout.setContentsMargins(0, 0, 0, 0)
        pov_widget_layout.addWidget(QLabel(_("POV: ")))
        pov_widget_layout.addWidget(self.pov_combo)
        pov_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        pov_char_widget = QWidget()
        pov_char_widget_layout = QHBoxLayout(pov_char_widget)
        pov_char_widget_layout.setContentsMargins(0, 0, 0, 0)
        pov_char_widget_layout.addWidget(QLabel(_("of: ")))
        pov_char_widget_layout.addWidget(self.pov_character_combo)
        pov_char_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        tense_widget = QWidget()
        tense_widget_layout = QHBoxLayout(tense_widget)
        tense_widget_layout.setContentsMargins(0, 0, 0, 0)
        tense_widget_layout.addWidget(QLabel(_("using: ")))
        tense_widget_layout.addWidget(self.tense_combo)
        tense_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        top_row_layout.addWidget(pov_widget)
        top_row_layout.addWidget(pov_char_widget)
        top_row_layout.addWidget(tense_widget)
        top_row_layout.addStretch()

        self.scene_summary_edit = QTextEdit()
        self.scene_summary_edit.setPlaceholderText(_("Enter a short scene summary..."))
        self.scene_summary_edit.setMinimumHeight(80)
        self.scene_summary_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        top_control_layout.addWidget(top_row)
        top_control_layout.addWidget(self.scene_summary_edit)

        layout.addWidget(self.top_control_container)

        # --- Shared preview stack ---
        self.preview_stack = QStackedWidget()

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText(_("LLM output preview will appear here..."))
        self.preview_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        try:
            sb = self.preview_text.verticalScrollBar()
            sb.setSingleStep(12)
        except Exception:
            pass
        self.preview_stack.addWidget(self.preview_text)

        self.tweak_tab_widget = QTabWidget()
        self.tweaks_widget = TweaksWidget()
        self.preview_editable_widget = PreviewEditableWidget()
        self.tweak_tab_widget.addTab(self.tweaks_widget, _("Tweaks"))
        self.tweak_tab_widget.addTab(self.preview_editable_widget, _("Edit Prompt"))
        self.preview_stack.addWidget(self.tweak_tab_widget)

        QTimer.singleShot(100, self.parent_stack._connect_edit_signals)

        self.preview_uneditable_widget = PreviewUneditableWidget()
        self.preview_stack.addWidget(self.preview_uneditable_widget)

        # --- Preview actions widget (apply + include checkbox) ---
        self.preview_actions_widget = QWidget()
        preview_actions_layout = QHBoxLayout(self.preview_actions_widget)
        preview_actions_layout.setContentsMargins(0, 0, 0, 0)

        self.apply_button = QPushButton()
        self.apply_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/save.svg", self.tint_color)
        )
        self.apply_button.setToolTip(_("Apply the LLM output into the editor"))
        self.apply_button.clicked.connect(self.parent_stack.apply_tab_preview)
        preview_actions_layout.addWidget(self.apply_button)

        self.include_prompt_checkbox = QCheckBox(_("Include Action Beats"))
        self.include_prompt_checkbox.setToolTip(
            _("Include the text from the Action Beats field in the scene text")
        )
        self.include_prompt_checkbox.setChecked(True)
        preview_actions_layout.addWidget(self.include_prompt_checkbox)
        preview_actions_layout.addStretch()

        # --- Controls container (buttons + tabs + context) ---
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        layout.addWidget(controls_container)

        self.prompt_controls_widget = QWidget()
        prompt_controls_layout = QHBoxLayout(self.prompt_controls_widget)
        prompt_controls_layout.setContentsMargins(0, 0, 0, 0)
        prompt_controls_layout.setSpacing(6)

        self.tweak_prompt_button = QPushButton()
        self.tweak_prompt_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/tool.svg", self.tint_color)
        )
        self.tweak_prompt_button.setToolTip(_("Tweak selected prompt"))
        self.tweak_prompt_button.setCheckable(True)
        self.tweak_prompt_button.clicked.connect(self.parent_stack.toggle_tweak_prompt)
        prompt_controls_layout.addWidget(self.tweak_prompt_button)

        self.preview_button = QPushButton()
        self.preview_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/eye.svg", self.tint_color)
        )
        self.preview_button.setToolTip(_("Preview the final prompt"))
        self.preview_button.setCheckable(True)
        self.preview_button.clicked.connect(self.parent_stack.toggle_preview)
        prompt_controls_layout.addWidget(self.preview_button)

        self.refresh_prompt_button = QPushButton()
        self.refresh_prompt_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg", self.tint_color)
        )
        self.refresh_prompt_button.setToolTip(_("Refresh prompt and discard changes"))
        self.refresh_prompt_button.clicked.connect(self.parent_stack.refresh_prompt)
        prompt_controls_layout.addWidget(self.refresh_prompt_button)

        self.send_button = QPushButton()
        self.send_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/send.svg", self.tint_color)
        )
        self.send_button.setToolTip(_("Send prompt to LLM"))
        self.send_button.clicked.connect(self.parent_stack.send_prompt_with_temp_config)
        prompt_controls_layout.addWidget(self.send_button)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg", self.tint_color)
        )
        self.stop_button.setToolTip(_("Interrupt the LLM response"))
        self.stop_button.clicked.connect(self.controller.stop_llm)
        prompt_controls_layout.addWidget(self.stop_button)

        self.context_toggle_button = QPushButton()
        self.context_toggle_button.setIcon(
            ThemeManager.get_tinted_icon("assets/icons/book.svg", self.tint_color)
        )
        self.context_toggle_button.setToolTip(_("Toggle context panel"))
        self.context_toggle_button.setCheckable(True)
        self.context_toggle_button.clicked.connect(self.parent_stack.toggle_context_panel)
        prompt_controls_layout.addWidget(self.context_toggle_button)

        prompt_controls_layout.addStretch()
        self.custom_edits_label = QLabel(_("Using Custom Prompt"))
        self.custom_edits_label.setStyleSheet(
            "QLabel { color: darkblue; padding: 0 8px; }"
        )
        self.custom_edits_label.setVisible(False)
        prompt_controls_layout.addWidget(self.custom_edits_label)

        # Tab widget with shared preview/actions embedded per-tab
        self.prompt_tab_widget = QTabWidget()
        self.prompt_tab_widget.setTabPosition(QTabWidget.South)
        self.prompt_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #888; border-radius: 4px; }"
        )
        self.prompt_tab_widget.tabBar().setStyleSheet(
            "QTabBar::tab { padding: 6px 12px; }\n"
            "QTabBar::tab:disabled { color: #888; }"
        )

        self.tab_layouts = {}

        beat_widget = BeatTab(self.parent_stack)
        self.prompt_input = beat_widget.prompt_input
        self.prompt_input.textChanged.connect(
            self.controller.on_prompt_input_text_changed
        )
        self.prose_prompt_panel = beat_widget.prose_prompt_panel
        self.tab_layouts['write'] = beat_widget.layout()
        self.write_tab_index = self.prompt_tab_widget.addTab(beat_widget, _("Beat"))

        self.rewrite_tab = RewriteTab(self.parent_stack)
        rewrite_container = QWidget()
        rewrite_layout = QVBoxLayout(rewrite_container)
        rewrite_layout.setContentsMargins(6, 6, 6, 6)
        rewrite_layout.setSpacing(6)
        rewrite_layout.addWidget(self.rewrite_tab)
        self.tab_layouts['rewrite'] = rewrite_layout
        self.rewrite_tab_index = self.prompt_tab_widget.addTab(
            rewrite_container, _("Rewrite")
        )

        summarize_widget = SummarizeTab(self)
        self.summary_tab_prompt_panel = summarize_widget.summary_tab_prompt_panel
        self.tab_layouts['summarize'] = summarize_widget.layout()
        self.summarize_tab_index = self.prompt_tab_widget.addTab(
            summarize_widget, _("Summarize")
        )

        controls_layout.addWidget(self.prompt_tab_widget)

        self.context_panel = ContextPanel(
            self.model.structure,
            self.model.project_name,
            self.controller,
            enhanced_window=self.controller.enhanced_window,
        )
        self.context_panel.setVisible(False)
        controls_layout.addWidget(self.context_panel)

        # Prompt state tracking for modes
        self.prompt_modes = {
            'write': {
                'prompt_panel': self.prose_prompt_panel,
                'original_prompt_config': None,
                'temporary_prompt_config': None,
                'has_custom_edits': False,
                'initialized': False,
            },
            'rewrite': {
                'prompt_panel': self.rewrite_tab.prompt_panel,
                'original_prompt_config': None,
                'temporary_prompt_config': None,
                'has_custom_edits': False,
                'initialized': False,
            },
            'summarize': {
                'prompt_panel': self.summary_tab_prompt_panel,
                'original_prompt_config': None,
                'temporary_prompt_config': None,
                'has_custom_edits': False,
                'initialized': False,
            },
        }

        # Signal wiring after state initialization
        self.prose_prompt_panel.prompt_combo.currentIndexChanged.connect(
            lambda: self.parent_stack.on_prompt_selected('write')
        )
        self.rewrite_tab.prompt_panel.prompt_combo.currentIndexChanged.connect(
            lambda: self.parent_stack.on_prompt_selected('rewrite')
        )
        self.prompt_tab_widget.currentChanged.connect(self.parent_stack._on_tab_changed)
        if self.summary_tab_prompt_panel:
            self.summary_tab_prompt_panel.prompt_combo.currentIndexChanged.connect(
                lambda: self.parent_stack.on_prompt_selected('summarize')
            )

        self.preview_text.textChanged.connect(self.parent_stack._on_shared_preview_changed)

    def _expose_to_parent(self):
        parent = self.parent_stack
        parent.llm_panel_widget = self

        # Shared widgets & controls
        parent.pov_combo = self.pov_combo
        parent.pov_character_combo = self.pov_character_combo
        parent.tense_combo = self.tense_combo
        parent.top_control_container = self.top_control_container
        parent.scene_summary_edit = self.scene_summary_edit
        parent.preview_stack = self.preview_stack
        parent.preview_text = self.preview_text
        parent.tweak_tab_widget = self.tweak_tab_widget
        parent.tweaks_widget = self.tweaks_widget
        parent.preview_editable_widget = self.preview_editable_widget
        parent.preview_uneditable_widget = self.preview_uneditable_widget
        parent.preview_actions_widget = self.preview_actions_widget
        parent.apply_button = self.apply_button
        parent.include_prompt_checkbox = self.include_prompt_checkbox
        parent.prompt_controls_widget = self.prompt_controls_widget
        parent.tweak_prompt_button = self.tweak_prompt_button
        parent.preview_button = self.preview_button
        parent.refresh_prompt_button = self.refresh_prompt_button
        parent.send_button = self.send_button
        parent.stop_button = self.stop_button
        parent.context_toggle_button = self.context_toggle_button
        parent.custom_edits_label = self.custom_edits_label
        parent.prompt_tab_widget = self.prompt_tab_widget
        parent.tab_layouts = self.tab_layouts
        parent.prompt_input = self.prompt_input
        parent.prose_prompt_panel = self.prose_prompt_panel
        # Live update of send button when Beats input changes
        try:
            self.prompt_input.textChanged.connect(parent._on_prompt_input_changed)
        except Exception:
            pass
        parent.rewrite_tab = self.rewrite_tab
        parent.rewrite_tab_index = self.rewrite_tab_index
        parent.write_tab_index = self.write_tab_index
        parent.summary_tab_prompt_panel = self.summary_tab_prompt_panel
        parent.summarize_tab_index = self.summarize_tab_index
        parent.context_panel = self.context_panel
        parent.prompt_modes = self.prompt_modes

        parent.current_shared_mode = None
        parent.active_mode = 'write'

        parent._embed_shared_widgets('write')

        if hasattr(parent.scene_editor, 'editor'):
            try:
                parent.scene_editor.editor.selectionChanged.connect(
                    parent._on_editor_selection_changed
                )
            except Exception:
                pass

        parent._on_editor_selection_changed()
        parent.reset_temporary_config('write')
        parent._apply_toggle_highlight_style()
        parent._on_tab_changed(parent.write_tab_index)

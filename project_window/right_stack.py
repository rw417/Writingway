#!/usr/bin/env python3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QStackedWidget, QHBoxLayout, QPushButton, 
                            QTextEdit, QComboBox, QSizePolicy,
                            QFormLayout, QSplitter, QCheckBox, QLineEdit, QLabel, QTabWidget, QTabBar)
from PyQt5.QtGui import QPainter
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QStyle, QStyleOptionTab
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QVariant
from settings.theme_manager import ThemeManager
from .focus_mode import PlainTextEdit
from compendium.context_panel import ContextPanel
from .summary_controller import SummaryController, SummaryMode
from .summary_model import SummaryModel
from muse.prompt_panel import PromptPanel
from muse.prompt_preview_dialog import PromptPreviewDialog
from muse.prompt_variables import get_prompt_variables
from project_window.tweaks_widget import TweaksWidget
from project_window.preview_editable_widget import PreviewEditableWidget
from project_window.preview_uneditable_widget import PreviewUneditableWidget
from project_window.rewrite_tab import RewriteTab
from copy import deepcopy

# gettext '_' fallback for static analysis / standalone edits
_ = globals().get('_', lambda s: s)

class RightStack(QWidget):
    """Stacked widget for summary and LLM panels."""
    def __init__(self, controller, model, tint_color=QColor("black")):
        super().__init__()
        self.controller = controller
        self.model = model
        self.tint_color = tint_color
        self.stack = QStackedWidget()
        self.scene_editor = controller.scene_editor
        self.summary_controller = SummaryController(
            SummaryModel(model.project_name),
            self,
            controller.project_tree
        )
        self.summary_controller.progress_updated.connect(self._update_progress)
        
        # Temporary prompt config management
        self._suspend_temp_sync = False
        
        self.init_ui()
        self.project_tree = controller.project_tree
        self.project_tree.tree.currentItemChanged.connect(self._update_summary_mode_visibility)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summary_panel = self.create_summary_panel()
        self.llm_panel = self.create_llm_panel()
        self.stack.addWidget(self.summary_panel)
        self.stack.addWidget(self.llm_panel)

    def create_summary_panel(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)

        self.summary_prompt_panel = PromptPanel("Summary")
        self.summary_prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.summary_prompt_panel.setMaximumWidth(250)
        layout.addWidget(self.summary_prompt_panel)

        self.summary_preview_button = QPushButton()
        self.summary_preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", self.tint_color))
        self.summary_preview_button.setToolTip(_("Preview the final prompt"))
        self.summary_preview_button.clicked.connect(self.summary_controller.preview_summary)
        layout.addWidget(self.summary_preview_button)
        
        layout.addStretch()
        self.summary_mode_combo = QComboBox()
        # Populate combo box with enum values and localized display names
        for mode in SummaryMode:
            self.summary_mode_combo.addItem(mode.display_name(), QVariant(mode))
        self.summary_mode_combo.setToolTip(_("Select summary generation mode"))
        self.summary_mode_combo.setVisible(False)  # Hidden by default
        layout.addWidget(self.summary_mode_combo)

        self.summary_start_button = QPushButton()
        self.summary_start_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", self.tint_color))
        self.summary_start_button.setToolTip(_("Start summary generation"))
        self.summary_start_button.clicked.connect(self._start_summary)
        layout.addWidget(self.summary_start_button)

        self.delete_summary_button = QPushButton()
        self.delete_summary_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/trash.svg", self.tint_color))
        self.delete_summary_button.setToolTip(_("Delete current summary"))
        self.delete_summary_button.clicked.connect(self.summary_controller.delete_summary)
        layout.addWidget(self.delete_summary_button)

        layout.addStretch()
        return panel

    def _start_summary(self):
        """Determine whether to create chapter or act summary based on selection."""
        current_item = self.project_tree.tree.currentItem()
        if not current_item:
            return
        level = self.project_tree.get_item_level(current_item)
        if level == 0:
            self.summary_controller.create_act_summary()
        elif level == 1:
            self.summary_controller.create_chapter_summary()

    def _update_summary_mode_visibility(self, current, previous):
        """Show/hide summary mode combo based on whether an Act is selected."""
        if not current:
            self.summary_mode_combo.setVisible(False)
            return
        level = self.project_tree.get_item_level(current)
        self.summary_mode_combo.setVisible(level == 0)

    def create_llm_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Top control container (POV/Tense etc.) ---
        top_control_container = QWidget()
        top_control_layout = QVBoxLayout(top_control_container)
        top_control_layout.setContentsMargins(0, 0, 0, 0)

        top_row = QWidget()
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)

        self.pov_combo = QComboBox()
        self.pov_combo.addItems([_("1st Person"), _("2nd Person"), _("3rd Person Limited"), _("3rd Person Omniscient"), _("Custom...")])
        self.pov_combo.currentIndexChanged.connect(self.controller.handle_pov_change)

        self.pov_character_combo = QComboBox()
        self.pov_character_combo.addItems(["Alice", "Bob", "Charlie", _("Custom...")])
        self.pov_character_combo.currentIndexChanged.connect(self.controller.handle_pov_character_change)

        self.tense_combo = QComboBox()
        self.tense_combo.addItems([_("Past Tense"), _("Present Tense"), _("Custom...")])
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

        self.top_control_container = top_control_container
        self.top_control_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.top_control_container.setMaximumHeight(350)
        layout.addWidget(self.top_control_container)

        # --- Shared preview stack ---
        self.preview_stack = QStackedWidget()

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText(_("LLM output preview will appear here..."))
        # Limit the preview area height so it doesn't dominate the UI
        self.preview_text.setMaximumHeight(350)
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

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._connect_edit_signals)

        self.preview_uneditable_widget = PreviewUneditableWidget()
        self.preview_stack.addWidget(self.preview_uneditable_widget)
        layout.addWidget(self.preview_stack)

        # --- Preview action row ---
        preview_buttons = QHBoxLayout()
        preview_buttons.setContentsMargins(0, 0, 0, 0)
        self.apply_button = QPushButton()
        self.apply_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/save.svg", self.tint_color))
        self.apply_button.setToolTip(_("Appends the LLM's output to your current scene"))
        self.apply_button.clicked.connect(self.controller.apply_preview)
        preview_buttons.addWidget(self.apply_button)

        self.include_prompt_checkbox = QCheckBox(_("Include Action Beats"))
        self.include_prompt_checkbox.setToolTip(_("Include the text from the Action Beats field in the scene text"))
        self.include_prompt_checkbox.setChecked(True)
        preview_buttons.addWidget(self.include_prompt_checkbox)
        preview_buttons.addStretch()
        layout.addLayout(preview_buttons)

        # --- Controls container (buttons + tabs + context) ---
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        layout.addWidget(controls_container)

        top_buttons_layout = QHBoxLayout()
        top_buttons_layout.setContentsMargins(0, 0, 0, 0)

        self.tweak_prompt_button = QPushButton()
        self.tweak_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/tool.svg", self.tint_color))
        self.tweak_prompt_button.setToolTip(_("Tweak selected prompt"))
        self.tweak_prompt_button.setCheckable(True)
        self.tweak_prompt_button.clicked.connect(self.toggle_tweak_prompt)
        top_buttons_layout.addWidget(self.tweak_prompt_button)

        self.refresh_prompt_button = QPushButton()
        self.refresh_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg", self.tint_color))
        self.refresh_prompt_button.setToolTip(_("Refresh prompt and discard changes"))
        self.refresh_prompt_button.clicked.connect(self.refresh_prompt)
        top_buttons_layout.addWidget(self.refresh_prompt_button)

        self.preview_button = QPushButton()
        self.preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", self.tint_color))
        self.preview_button.setToolTip(_("Preview the final prompt"))
        self.preview_button.setCheckable(True)
        self.preview_button.clicked.connect(self.toggle_preview)
        top_buttons_layout.addWidget(self.preview_button)

        self.send_button = QPushButton()
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", self.tint_color))
        self.send_button.setToolTip(_("Send prompt to LLM"))
        self.send_button.clicked.connect(self.send_prompt_with_temp_config)
        top_buttons_layout.addWidget(self.send_button)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg", self.tint_color))
        self.stop_button.setToolTip(_("Interrupt the LLM response"))
        self.stop_button.clicked.connect(self.controller.stop_llm)
        top_buttons_layout.addWidget(self.stop_button)

        self.context_toggle_button = QPushButton()
        self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book.svg", self.tint_color))
        self.context_toggle_button.setToolTip(_("Toggle context panel"))
        self.context_toggle_button.setCheckable(True)
        self.context_toggle_button.clicked.connect(self.toggle_context_panel)
        top_buttons_layout.addWidget(self.context_toggle_button)

        top_buttons_layout.addStretch()
        self.custom_edits_label = QLabel(_("Using Custom Prompt"))
        self.custom_edits_label.setStyleSheet("QLabel { color: darkblue; padding: 0 8px; }")
        self.custom_edits_label.setVisible(False)
        top_buttons_layout.addWidget(self.custom_edits_label)

        controls_layout.addLayout(top_buttons_layout)

        # Use standard top-positioned tabs (easier to read and consistent on most platforms)
        self.prompt_tab_widget = QTabWidget()
        self.prompt_tab_widget.setTabPosition(QTabWidget.North)

        write_tab = QWidget()
        write_layout = QVBoxLayout(write_tab)
        write_layout.setContentsMargins(0, 0, 0, 0)
        write_layout.setSpacing(6)

        self.prompt_input = PlainTextEdit()
        self.prompt_input.setPlaceholderText(_("Enter your action beats here..."))
        self.prompt_input.setFixedHeight(100)
        self.prompt_input.textChanged.connect(self.controller.on_prompt_input_text_changed)
        write_layout.addWidget(self.prompt_input)

        bottom_row_layout = QHBoxLayout()
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        self.prose_prompt_panel = PromptPanel("Prose")
        self.prose_prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.prose_prompt_panel.setMaximumWidth(250)
        bottom_row_layout.addWidget(self.prose_prompt_panel)
        bottom_row_layout.addStretch()
        write_layout.addLayout(bottom_row_layout)
        write_layout.addStretch()

        self.write_tab_index = self.prompt_tab_widget.addTab(write_tab, _("Write"))

        self.rewrite_tab = RewriteTab(self)
        self.rewrite_tab_index = self.prompt_tab_widget.addTab(self.rewrite_tab, _("Rewrite"))

        summarize_tab = QWidget()
        summarize_layout = QVBoxLayout(summarize_tab)
        summarize_layout.setContentsMargins(0, 0, 0, 0)
        summarize_layout.addStretch()
        placeholder = QLabel(_("Summary tools coming soon."))
        placeholder.setAlignment(Qt.AlignCenter)
        summarize_layout.addWidget(placeholder)
        summarize_layout.addStretch()
        self.summarize_tab_index = self.prompt_tab_widget.addTab(summarize_tab, _("Summarize"))

        controls_layout.addWidget(self.prompt_tab_widget)

        self.context_panel = ContextPanel(self.model.structure, self.model.project_name, self.controller, enhanced_window=self.controller.enhanced_window)
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
        }
        self.active_mode = 'write'

        # Signal wiring after state initialization
        self.prose_prompt_panel.prompt_combo.currentIndexChanged.connect(lambda: self.on_prompt_selected('write'))
        self.rewrite_tab.prompt_panel.prompt_combo.currentIndexChanged.connect(lambda: self.on_prompt_selected('rewrite'))
        self.prompt_tab_widget.currentChanged.connect(self._on_tab_changed)

        if hasattr(self.scene_editor, 'editor'):
            try:
                self.scene_editor.editor.selectionChanged.connect(self._on_editor_selection_changed)
            except Exception:
                pass
        self._on_editor_selection_changed()

        self.reset_temporary_config('write')
        self._apply_toggle_highlight_style()
        self._on_tab_changed(self.write_tab_index)
        return panel

    def add_combo(self, layout, label_text, items, callback):
        combo = QComboBox()
        combo.addItems(items)
        combo.currentIndexChanged.connect(callback)
        layout.addRow(f"{label_text}:", combo)
        return combo

    def _set_bottom_row_dropdowns_enabled(self, enabled: bool):
        """Enable/disable bottom row dropdowns except provider/model combos."""
        state = self._get_state()
        panel = state['prompt_panel'] if state else None

        if panel and hasattr(panel, 'prompt_combo') and panel.prompt_combo:
            panel.prompt_combo.setEnabled(enabled)

        if self.active_mode == 'write':
            for combo in (self.pov_combo, self.pov_character_combo, self.tense_combo):
                if combo:
                    combo.setEnabled(enabled)

        # Provider and model selectors remain enabled regardless of preview state
        if panel:
            for combo in (getattr(panel, 'provider_combo', None), getattr(panel, 'model_combo', None)):
                if combo:
                    combo.setEnabled(True)
    
    def _apply_toggle_highlight_style(self):
        """Apply a consistent theme-derived highlight color to toggle buttons."""
        highlight_color = ThemeManager.get_toggle_highlight_color()
        if not highlight_color:
            return

        rgba = f"rgba({highlight_color.red()}, {highlight_color.green()}, {highlight_color.blue()}, {highlight_color.alpha()})"
        highlight_style = f"QPushButton:checked {{ background-color: {rgba}; }}"

        for button in (getattr(self, 'tweak_prompt_button', None),
                       getattr(self, 'preview_button', None),
                       getattr(self, 'context_toggle_button', None)):
            if button and button.isCheckable():
                button.setStyleSheet(highlight_style)

    def update_top_control_height(self):
        """Update the height of the top control container to the smaller of 250px or 20% of this widget's height."""
        try:
            if not hasattr(self, 'top_control_container') or not self.top_control_container:
                return
            total_h = self.height()
            cap_by_percent = int(total_h * 0.20)
            target = min(250, cap_by_percent)
            # Ensure at least a small visible height
            target = max(80, target)
            self.top_control_container.setMaximumHeight(target)
        except Exception:
            pass

    def resizeEvent(self, event):
        # Update top control height on resize and pass the event up
        self.update_top_control_height()
        super().resizeEvent(event)

    def update_tint(self, tint_color):
        self.tint_color = tint_color
        self.apply_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/save.svg", tint_color))
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", tint_color))
        self.stop_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg", tint_color))
        self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon(
            "assets/icons/book-open.svg" if self.context_panel.isVisible() else "assets/icons/book.svg", tint_color))
        self.tweak_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/tool.svg", tint_color))
        self.refresh_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg", tint_color))
        self.preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", tint_color))
        self.summary_preview_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/eye.svg", tint_color))
        self.summary_start_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/play-circle.svg", tint_color))
        self.delete_summary_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/trash.svg", tint_color))
        if self.pov_combo:
            self.pov_combo.setToolTip(_("POV: {}").format(self.model.settings.get('global_pov', 'Third Person')))
        if self.pov_character_combo:
            self.pov_character_combo.setToolTip(_("POV Character: {}").format(self.model.settings.get('global_pov_character', 'Character')))
        if self.tense_combo:
            self.tense_combo.setToolTip(_("Tense: {}").format(self.model.settings.get('global_tense', 'Present Tense')))

        self._apply_toggle_highlight_style()

    def _update_progress(self, message):
        self.controller.statusBar().showMessage(message, 5000)

    def toggle_context_panel(self):
        context_panel = self.context_panel
        if context_panel.isVisible():
            context_panel.setVisible(False)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book.svg", self.tint_color))
        else:
            context_panel.build_project_tree()
            context_panel.build_compendium_tree()
            context_panel.setVisible(True)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg", self.tint_color))

    def get_additional_vars(self):
        """Get additional variables using the centralized variable system."""
        # The centralized system now handles all these variables automatically
        vars_dict = get_prompt_variables()
        
        # Merge in tweak values if they exist
        if hasattr(self, 'tweaks_widget'):
            tweak_values = self.tweaks_widget.get_tweak_values()
            vars_dict.update(tweak_values)

        if self.active_mode == 'rewrite' and hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            selected_text = self.rewrite_tab.get_selected_text()
            if selected_text:
                vars_dict['selectedText'] = selected_text
        
        return vars_dict
    
    def _connect_edit_signals(self):
        """Connect signals for tracking edits to tweaks and preview widgets."""
        try:
            if hasattr(self, 'tweaks_widget'):
                instructions_edit = self.tweaks_widget.findChild(QTextEdit, "additional_instructions_edit")
                word_count_combo = self.tweaks_widget.findChild(QComboBox, "output_word_count_combo")
                
                if instructions_edit:
                    instructions_edit.textChanged.connect(self.on_temp_config_edited)
                if word_count_combo:
                    word_count_combo.currentTextChanged.connect(self.on_temp_config_edited)
            
            if hasattr(self, 'preview_editable_widget'):
                self.preview_editable_widget.contentEdited.connect(self.on_temp_config_edited)
        except Exception as e:
            print(f"Error connecting edit signals: {e}")
    
    def _get_state(self, mode=None):
        mode = mode or self.active_mode
        return self.prompt_modes.get(mode)

    def _ensure_state_initialized(self, mode=None):
        state = self._get_state(mode)
        if not state or state['initialized']:
            return
        self.reset_temporary_config(mode)

    def _update_custom_edits_indicator(self):
        state = self._get_state()
        self.custom_edits_label.setVisible(bool(state and state['has_custom_edits']))

    def _get_user_input_for_mode(self, mode):
        if mode == 'rewrite' and hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            return self.rewrite_tab.get_selected_text()
        if mode == 'write' and hasattr(self, 'prompt_input') and self.prompt_input:
            return self.prompt_input.toPlainText().strip()
        return ""

    def get_selected_text_for_prompt(self) -> str:
        if hasattr(self, 'rewrite_tab') and self.active_mode == 'rewrite':
            text = self.rewrite_tab.get_selected_text()
            if text:
                return text

        try:
            cursor = self.scene_editor.editor.textCursor()
            if cursor and cursor.hasSelection():
                fragment = cursor.selection()
                return fragment.toPlainText().strip()
        except Exception:
            pass
        return ""

    def get_prompt_data(self):
        state = self._get_state()
        if not state:
            return {
                'user_input': "",
                'prompt_config': None,
                'overrides': {},
                'additional_vars': None,
                'current_scene_text': None,
                'extra_context': None,
            }

        prompt_config = None
        if state['has_custom_edits'] and state['temporary_prompt_config']:
            prompt_config = state['temporary_prompt_config']
        else:
            prompt_config = state['prompt_panel'].get_prompt()

        overrides = state['prompt_panel'].get_overrides() if hasattr(state['prompt_panel'], 'get_overrides') else {}
        user_input = self._get_user_input_for_mode(self.active_mode)
        additional_vars = self.get_additional_vars()

        return {
            'user_input': user_input,
            'prompt_config': prompt_config,
            'overrides': overrides,
            'additional_vars': additional_vars,
            'current_scene_text': None,
            'extra_context': None,
        }

    def get_include_block_text(self) -> str:
        if not self.include_prompt_checkbox.isChecked():
            return ""
        return self._get_user_input_for_mode(self.active_mode)

    def _on_tab_changed(self, index):
        if index == self.write_tab_index:
            mode = 'write'
        elif index == getattr(self, 'rewrite_tab_index', -1):
            mode = 'rewrite'
        else:
            mode = 'summarize'
        self._set_active_mode(mode)

    def _set_active_mode(self, mode):
        self.active_mode = mode
        is_prompt_mode = mode in self.prompt_modes

        for button in (self.tweak_prompt_button, self.refresh_prompt_button, self.preview_button, self.send_button):
            if button:
                button.setEnabled(is_prompt_mode)
                button.setChecked(False)

        self.preview_stack.setCurrentWidget(self.preview_text)
        self._set_bottom_row_dropdowns_enabled(True)

        # Keep the top control container always visible across modes
        try:
            self.top_control_container.setVisible(True)
        except Exception:
            pass

        if mode == 'write':
            self.include_prompt_checkbox.setText(_("Include Action Beats"))
            self.include_prompt_checkbox.setEnabled(True)
            self.include_prompt_checkbox.setToolTip(_("Include the text from the Action Beats field in the scene text"))
        elif mode == 'rewrite':
            self.include_prompt_checkbox.setText(_("Include Selected Text"))
            self.include_prompt_checkbox.setEnabled(True)
            self.include_prompt_checkbox.setToolTip(_("Include the original selection when applying the preview"))
        else:
            self.include_prompt_checkbox.setText(_("Include Action Beats"))
            self.include_prompt_checkbox.setEnabled(False)
            self.include_prompt_checkbox.setToolTip(_("Select a prompt tab to enable this option"))

        if is_prompt_mode:
            self._ensure_state_initialized(mode)
            self._update_custom_edits_indicator()
        else:
            self.custom_edits_label.setVisible(False)

    def _on_editor_selection_changed(self):
        if not hasattr(self, 'prompt_tab_widget') or not hasattr(self, 'rewrite_tab_index'):
            return

        has_selection = False
        selected_text = ""
        try:
            cursor = self.scene_editor.editor.textCursor()
            if cursor and cursor.hasSelection():
                has_selection = True
                fragment = cursor.selection()
                selected_text = fragment.toPlainText()
        except Exception:
            pass

        if hasattr(self, 'rewrite_tab') and self.rewrite_tab:
            if has_selection:
                self.rewrite_tab.set_selected_text(selected_text)
            else:
                self.rewrite_tab.clear_selected_text()

        self.prompt_tab_widget.setTabEnabled(self.rewrite_tab_index, has_selection)

        if not has_selection and self.active_mode == 'rewrite':
            self.prompt_tab_widget.setCurrentIndex(self.write_tab_index)
    def on_prompt_selected(self, mode='write'):
        """Called when user selects a prompt from the dropdown for the given mode."""
        self.reset_temporary_config(mode)
        if mode == self.active_mode:
            self.custom_edits_label.setVisible(False)
    
    def reset_temporary_config(self, mode=None):
        """Reset the temporary config to match the currently selected prompt for a mode."""
        mode = mode or self.active_mode
        state = self.prompt_modes.get(mode)
        if not state:
            return

        self._suspend_temp_sync = True
        panel = state['prompt_panel']
        state['original_prompt_config'] = panel.get_prompt()

        if not state['original_prompt_config'] or not state['original_prompt_config'].get("messages"):
            state['temporary_prompt_config'] = None
            state['has_custom_edits'] = False
            state['initialized'] = True
            if mode == self.active_mode:
                self.custom_edits_label.setVisible(False)
            self._suspend_temp_sync = False
            return

        state['temporary_prompt_config'] = deepcopy(state['original_prompt_config'])
        state['has_custom_edits'] = False
        state['initialized'] = True

        if hasattr(self, 'tweaks_widget'):
            self.tweaks_widget.clear_tweaks()

        if hasattr(self, 'preview_editable_widget'):
            self.preview_editable_widget.set_prompt_config(state['temporary_prompt_config'])

        if mode == self.active_mode:
            self.custom_edits_label.setVisible(False)

        self._suspend_temp_sync = False
    
    def on_temp_config_edited(self):
        """Called when user makes changes to tweaks or editable preview."""
        if self._suspend_temp_sync:
            return

        state = self._get_state()
        if not state:
            return

        if not state['has_custom_edits']:
            state['has_custom_edits'] = True
            if self.active_mode in self.prompt_modes:
                self.custom_edits_label.setVisible(True)
        
        # Note: We'll get the edited config from the widget when we need it
        # (when toggling preview or sending), not on every edit signal
        # This avoids unnecessary updates during typing
        self._sync_editable_prompt_changes()

    def _sync_editable_prompt_changes(self):
        """Persist editable prompt changes into the temporary config immediately."""
        if self._suspend_temp_sync:
            return

        state = self._get_state()
        if not state:
            return

        if not hasattr(self, 'preview_editable_widget') or not self.preview_editable_widget:
            return

        try:
            edited_config = self.preview_editable_widget.get_edited_config()
        except Exception:
            return

        if not edited_config:
            return

        state['temporary_prompt_config'] = edited_config
    
    def toggle_tweak_prompt(self):
        """Toggle the tweak prompt tabbed widget."""
        state = self._get_state()
        if not state:
            self.tweak_prompt_button.setChecked(False)
            return

        if self.tweak_prompt_button.isChecked():
            self.custom_edits_label.setVisible(True)
            if not state['temporary_prompt_config']:
                self.reset_temporary_config(self.active_mode)

            if not state['temporary_prompt_config']:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.tweak_prompt_button.setChecked(False)
                return
            
            self.preview_editable_widget.set_prompt_config(state['temporary_prompt_config'])
            
            # Set to Tweaks tab by default
            self.tweak_tab_widget.setCurrentIndex(0)
            
            # Hide other views
            self.preview_button.setChecked(False)
            self._set_bottom_row_dropdowns_enabled(True)
            
            self.preview_stack.setCurrentWidget(self.tweak_tab_widget)
        else:
            # Hide and return to default view
            self.preview_stack.setCurrentWidget(self.preview_text)
    
    def toggle_preview(self):
        """Toggle the uneditable preview widget."""
        state = self._get_state()
        if not state:
            self.preview_button.setChecked(False)
            self.preview_stack.setCurrentWidget(self.preview_text)
            return

        if self.preview_button.isChecked():
            # Show uneditable preview
            # Hide tweak widget if showing
            self.tweak_prompt_button.setChecked(False)
            
            # Get the config to use - if we have custom edits, get latest from editable widget
            if state['has_custom_edits']:
                edited_config = self.preview_editable_widget.get_edited_config()
                if edited_config:
                    state['temporary_prompt_config'] = edited_config
                config_to_use = state['temporary_prompt_config']
            else:
                config_to_use = state['prompt_panel'].get_prompt()
            
            # Validate we have a config
            if not config_to_use or not config_to_use.get("messages"):
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.preview_button.setChecked(False)
                self._set_bottom_row_dropdowns_enabled(True)
                return
            
            # Assemble and show final prompt
            user_input = self._get_user_input_for_mode(self.active_mode)
            additional_vars = self.get_additional_vars()
            
            self.preview_uneditable_widget.set_prompt_data(
                prompt_config=config_to_use,
                user_input=user_input,
                additional_vars=additional_vars,
                current_scene_text=self.scene_editor.editor.toPlainText(),
                extra_context=None
            )
            
            self._set_bottom_row_dropdowns_enabled(False)

            self.preview_stack.setCurrentWidget(self.preview_uneditable_widget)
        else:
            # Hide and return to default view
            self._set_bottom_row_dropdowns_enabled(True)
            self.preview_stack.setCurrentWidget(self.preview_text)
    
    def refresh_prompt(self):
        """Refresh prompt and discard all custom edits."""
        self.reset_temporary_config()
        state = self._get_state()
        if state:
            state['has_custom_edits'] = False
        self.custom_edits_label.setVisible(False)
        
        # Also hide any special views and return to default
        self.tweak_prompt_button.setChecked(False)
        self.preview_button.setChecked(False)
        self._set_bottom_row_dropdowns_enabled(True)
        self.preview_stack.setCurrentWidget(self.preview_text)
    
    def send_prompt_with_temp_config(self):
        """Send prompt using temporary config if it has custom edits."""
        # Always show the LLM output preview before sending
        if self.preview_button.isChecked():
            self.preview_button.setChecked(False)
        if self.tweak_prompt_button.isChecked():
            self.tweak_prompt_button.setChecked(False)
        self.preview_stack.setCurrentWidget(self.preview_text)
        self._set_bottom_row_dropdowns_enabled(True)

        state = self._get_state()
        if state and state['has_custom_edits'] and state['temporary_prompt_config']:
            edited_config = self.preview_editable_widget.get_edited_config()
            if edited_config:
                state['temporary_prompt_config'] = edited_config

        self.controller.send_prompt()
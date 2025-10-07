#!/usr/bin/env python3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QStackedWidget, QHBoxLayout, QPushButton, 
                            QTextEdit, QComboBox, QSizePolicy,
                            QFormLayout, QSplitter, QCheckBox, QLineEdit, QLabel, QTabWidget)
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
from muse.tweaks_widget import TweaksWidget
from muse.preview_editable_widget import PreviewEditableWidget
from muse.preview_uneditable_widget import PreviewUneditableWidget
from copy import deepcopy

# gettext '_' fallback for static analysis / standalone edits
try:
    _
except NameError:
    _ = lambda s: s

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
        self.original_prompt_config = None  # The selected prompt config
        self.temporary_prompt_config = None  # Modified version
        self.has_custom_edits = False  # Track if temp config differs from original
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
        self.summary_prompt_panel.setMaximumWidth(300)
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

        # Create stacked widget for swappable preview area
        self.preview_stack = QStackedWidget()
        
        # 1. Default preview text (LLM output)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText(_("LLM output preview will appear here..."))
        self.preview_stack.addWidget(self.preview_text)
        
        # 2. Tabbed widget for tweaks and editable preview
        self.tweak_tab_widget = QTabWidget()
        self.tweaks_widget = TweaksWidget()
        self.preview_editable_widget = PreviewEditableWidget()
        self.tweak_tab_widget.addTab(self.tweaks_widget, _("Tweaks"))
        self.tweak_tab_widget.addTab(self.preview_editable_widget, _("Edit Prompt"))
        self.preview_stack.addWidget(self.tweak_tab_widget)
        
        # Connect signals for edit tracking (will be connected after widgets are fully loaded)
        # We'll do this in a delayed fashion to ensure widgets are ready
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._connect_edit_signals)
        
        # 3. Uneditable preview widget (final assembled prompt)
        self.preview_uneditable_widget = PreviewUneditableWidget()
        self.preview_stack.addWidget(self.preview_uneditable_widget)
        
        # Preview buttons and checkbox
        preview_buttons = QHBoxLayout()
        self.apply_button = QPushButton()
        self.apply_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/save.svg", self.tint_color))
        self.apply_button.setToolTip(_("Appends the LLM's output to your current scene"))
        self.apply_button.clicked.connect(self.controller.apply_preview)
        self.include_prompt_checkbox = QCheckBox(_("Include Action Beats"))
        self.include_prompt_checkbox.setToolTip(_("Include the text from the Action Beats field in the scene text"))
        self.include_prompt_checkbox.setChecked(True)
        preview_buttons.addWidget(self.apply_button)
        preview_buttons.addWidget(self.include_prompt_checkbox)
        preview_buttons.addStretch()

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.prompt_input = PlainTextEdit()
        self.prompt_input.setPlaceholderText(_("Enter your action beats here..."))
        self.prompt_input.setFixedHeight(100)
        self.prompt_input.textChanged.connect(self.controller.on_prompt_input_text_changed)
        left_layout.addWidget(self.prompt_input)

        # Top button row (above prompt selector)
        top_buttons_layout = QHBoxLayout()
        
        # NEW: Tweak prompt button (leftmost)
        self.tweak_prompt_button = QPushButton()
        self.tweak_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/tool.svg", self.tint_color))
        self.tweak_prompt_button.setToolTip(_("Tweak selected prompt"))
        self.tweak_prompt_button.setCheckable(True)
        self.tweak_prompt_button.clicked.connect(self.toggle_tweak_prompt)
        top_buttons_layout.addWidget(self.tweak_prompt_button)
        
        # NEW: Refresh prompt button
        self.refresh_prompt_button = QPushButton()
        self.refresh_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-cw.svg", self.tint_color))
        self.refresh_prompt_button.setToolTip(_("Refresh prompt and discard changes"))
        self.refresh_prompt_button.clicked.connect(self.refresh_prompt)
        top_buttons_layout.addWidget(self.refresh_prompt_button)
        
        # Existing preview button (now toggleable)
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
        
        # NEW: Custom edits indicator label and add padding and use dark blue color
        self.custom_edits_label = QLabel(_("Using Custom Prompt"))
        self.custom_edits_label.setStyleSheet("QLabel { color: darkblue; padding: 0 8px; }")
        self.custom_edits_label.setVisible(False)
        top_buttons_layout.addWidget(self.custom_edits_label)
        
        left_layout.addLayout(top_buttons_layout)

        # Bottom row with prompt selector and dropdowns
        bottom_row_layout = QHBoxLayout()
        
        self.prose_prompt_panel = PromptPanel("Prose")
        self.prose_prompt_panel.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.prose_prompt_panel.setMaximumWidth(300)
        # Connect to handle prompt selection changes
        self.prose_prompt_panel.prompt_combo.currentIndexChanged.connect(self.on_prompt_selected)
        bottom_row_layout.addWidget(self.prose_prompt_panel)

        bottom_row_layout.addStretch()
        
        pulldown_widget = QWidget()
        pulldown_layout = QFormLayout(pulldown_widget)
        pulldown_layout.setContentsMargins(0, 0, 20, 0)
        pulldown_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.pov_combo = self.add_combo(pulldown_layout, _("POV"), [_("First Person"), _("Third Person Limited"), _("Omniscient"), _("Custom...")], self.controller.handle_pov_change)
        self.pov_character_combo = self.add_combo(pulldown_layout, _("POV Character"), ["Alice", "Bob", "Charlie", _("Custom...")], self.controller.handle_pov_character_change)
        self.tense_combo = self.add_combo(pulldown_layout, _("Tense"), [_("Past Tense"), _("Present Tense"), _("Custom...")], self.controller.handle_tense_change)
        bottom_row_layout.addWidget(pulldown_widget)

        left_layout.addLayout(bottom_row_layout)
        
        # Context panel below the buttons and dropdowns
        self.context_panel = ContextPanel(self.model.structure, self.model.project_name, self.controller, enhanced_window=self.controller.enhanced_window)
        self.context_panel.setVisible(False)
        left_layout.addWidget(self.context_panel)

        left_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        action_layout.addWidget(left_container)

        layout.addWidget(self.preview_stack)  # Changed from self.preview_text
        layout.addLayout(preview_buttons)
        layout.addLayout(action_layout)
        return panel

    def add_combo(self, layout, label_text, items, callback):
        combo = QComboBox()
        combo.addItems(items)
        combo.currentIndexChanged.connect(callback)
        layout.addRow(f"{label_text}:", combo)
        return combo

    def _set_bottom_row_dropdowns_enabled(self, enabled: bool):
        """Enable/disable bottom row dropdowns except provider/model combos."""
        combo_list = [
            getattr(self.prose_prompt_panel, 'prompt_combo', None),
            getattr(self, 'pov_combo', None),
            getattr(self, 'pov_character_combo', None),
            getattr(self, 'tense_combo', None),
        ]

        for combo in combo_list:
            if combo:
                combo.setEnabled(enabled)

        # Provider and model selectors remain enabled regardless of preview state
        for combo in [getattr(self.prose_prompt_panel, 'provider_combo', None),
                      getattr(self.prose_prompt_panel, 'model_combo', None)]:
            if combo:
                combo.setEnabled(True)
    
    def update_tint(self, tint_color):
        self.tint_color = tint_color
        self.apply_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/save.svg", tint_color))
        self.send_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/send.svg", tint_color))
        self.stop_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/x-octagon.svg", tint_color))
        self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon(
            "assets/icons/book-open.svg" if self.context_panel.isVisible() else "assets/icons/book.svg", tint_color))
        self.tweak_prompt_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/edit.svg", tint_color))
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

    def _update_progress(self, message):
        self.controller.statusBar().showMessage(message, 5000)

    def toggle_context_panel(self):
        context_panel = self.context_panel
        if context_panel.isVisible():
            context_panel.setVisible(False)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book.svg"))
        else:
            context_panel.build_project_tree()
            context_panel.build_compendium_tree()
            context_panel.setVisible(True)
            self.context_toggle_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/book-open.svg"))

    def get_additional_vars(self):
        """Get additional variables using the centralized variable system."""
        # The centralized system now handles all these variables automatically
        vars_dict = get_prompt_variables()
        
        # Merge in tweak values if they exist
        if hasattr(self, 'tweaks_widget'):
            tweak_values = self.tweaks_widget.get_tweak_values()
            vars_dict.update(tweak_values)
        
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
    
    def on_prompt_selected(self):
        """Called when user selects a prompt from the dropdown."""
        # Reset temporary config when a new prompt is selected
        self.reset_temporary_config()
        self.custom_edits_label.setVisible(False)
    
    def reset_temporary_config(self):
        """Reset the temporary config to match the currently selected prompt."""
        self._suspend_temp_sync = True
        self.original_prompt_config = self.prose_prompt_panel.get_prompt()
        
        # Check if we actually have a valid prompt config
        if not self.original_prompt_config or not self.original_prompt_config.get("messages"):
            self.temporary_prompt_config = None
            self.has_custom_edits = False
            self.custom_edits_label.setVisible(False)
            self._suspend_temp_sync = False
            return
        
        self.temporary_prompt_config = deepcopy(self.original_prompt_config)
        self.has_custom_edits = False
        self.custom_edits_label.setVisible(False)
        
        # Clear tweak widgets
        if hasattr(self, 'tweaks_widget'):
            self.tweaks_widget.clear_tweaks()
        
        # Reset preview editable widget with the temp config
        if hasattr(self, 'preview_editable_widget'):
            self.preview_editable_widget.set_prompt_config(self.temporary_prompt_config)

        self._suspend_temp_sync = False
    
    def on_temp_config_edited(self):
        """Called when user makes changes to tweaks or editable preview."""
        if self._suspend_temp_sync:
            return

        if not self.has_custom_edits:
            self.has_custom_edits = True
            self.custom_edits_label.setVisible(True)
        
        # Note: We'll get the edited config from the widget when we need it
        # (when toggling preview or sending), not on every edit signal
        # This avoids unnecessary updates during typing
        self._sync_editable_prompt_changes()

    def _sync_editable_prompt_changes(self):
        """Persist editable prompt changes into the temporary config immediately."""
        if self._suspend_temp_sync:
            return

        if not hasattr(self, 'preview_editable_widget') or not self.preview_editable_widget:
            return

        try:
            edited_config = self.preview_editable_widget.get_edited_config()
        except Exception:
            return

        if not edited_config:
            return

        self.temporary_prompt_config = edited_config
    
    def toggle_tweak_prompt(self):
        """Toggle the tweak prompt tabbed widget."""
        if self.tweak_prompt_button.isChecked():
            self.custom_edits_label.setVisible(True)
            # Show tweak tab widget
            # First ensure we have a temporary config
            if not self.temporary_prompt_config:
                self.reset_temporary_config()
            
            # If still no config, show error and uncheck button
            if not self.temporary_prompt_config:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.tweak_prompt_button.setChecked(False)
                return
            
            # Update the editable preview with current temp config
            self.preview_editable_widget.set_prompt_config(self.temporary_prompt_config)
            
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
        if self.preview_button.isChecked():
            # Show uneditable preview
            # Hide tweak widget if showing
            self.tweak_prompt_button.setChecked(False)
            
            # Get the config to use - if we have custom edits, get latest from editable widget
            if self.has_custom_edits:
                # Get the latest edited config from the editable widget
                edited_config = self.preview_editable_widget.get_edited_config()
                if edited_config:
                    self.temporary_prompt_config = edited_config
                config_to_use = self.temporary_prompt_config
            else:
                config_to_use = self.prose_prompt_panel.get_prompt()
            
            # Validate we have a config
            if not config_to_use or not config_to_use.get("messages"):
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, _("No Prompt Selected"), 
                                  _("Please select a prompt first."))
                self.preview_button.setChecked(False)
                self._set_bottom_row_dropdowns_enabled(True)
                return
            
            # Assemble and show final prompt
            action_beats = self.prompt_input.toPlainText().strip()
            additional_vars = self.get_additional_vars()
            
            self.preview_uneditable_widget.set_prompt_data(
                prompt_config=config_to_use,
                user_input=action_beats,
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

        # Get the config to send
        if self.has_custom_edits and self.temporary_prompt_config:
            # Apply any final edits from the editable widget
            edited_config = self.preview_editable_widget.get_edited_config()
            if edited_config:
                self.temporary_prompt_config = edited_config
            
            # Temporarily set this config in the prompt panel so send_prompt uses it
            original_prompt = self.prose_prompt_panel.prompt
            self.prose_prompt_panel.prompt = self.temporary_prompt_config
            
            try:
                self.controller.send_prompt()
            finally:
                # Restore original prompt (but keep temporary config for session)
                self.prose_prompt_panel.prompt = original_prompt
        else:
            # No custom edits, send normally
            self.controller.send_prompt()